import pytest

from custom_components.seamless_rename.engine.ids import is_valid_entity_id
from custom_components.seamless_rename.engine.models import Rename
from custom_components.seamless_rename.engine.planner import (
    order_renames,
    render_diff,
    resolve_pattern,
    run_preflight,
)


def _simulate(ids: set[str], ordered: list[Rename]) -> set[str]:
    """Apply renames one by one the way the registry would; fail on any conflict."""
    current = set(ids)
    for rename in ordered:
        assert rename.from_id in current, f"{rename.from_id} missing"
        assert rename.to_id not in current, f"{rename.to_id} already taken"
        current.remove(rename.from_id)
        current.add(rename.to_id)
    return current


def test_pattern_resolves_to_concrete_list() -> None:
    ids = ["media_player.snap_a", "media_player.snap_b", "sensor.other"]
    result = resolve_pattern(ids, r"^media_player\.snap_(.*)$", r"media_player.\1_snap", None)
    assert result == [
        Rename("media_player.snap_a", "media_player.a_snap"),
        Rename("media_player.snap_b", "media_player.b_snap"),
    ]


def test_pattern_domain_filter_and_unchanged_ids_skipped() -> None:
    ids = ["media_player.snap_a", "sensor.snap_a", "sensor.keep"]
    result = resolve_pattern(ids, r"snap_", "room_", "sensor")
    assert result == [Rename("sensor.snap_a", "sensor.room_a")]


def test_invalid_pattern_raises() -> None:
    with pytest.raises(ValueError, match="pattern"):
        resolve_pattern(["sensor.a"], "(", "x", None)


def test_chain_orders_target_free() -> None:
    renames = [Rename("sensor.a", "sensor.b"), Rename("sensor.b", "sensor.c")]
    ordered = order_renames(renames)
    assert ordered == [Rename("sensor.b", "sensor.c"), Rename("sensor.a", "sensor.b")]
    assert _simulate({"sensor.a", "sensor.b"}, ordered) == {"sensor.b", "sensor.c"}


def test_swap_uses_temp_id() -> None:
    renames = [Rename("sensor.a", "sensor.b"), Rename("sensor.b", "sensor.a")]
    ordered = order_renames(renames)
    assert len(ordered) == 3
    assert _simulate({"sensor.a", "sensor.b"}, ordered) == {"sensor.a", "sensor.b"}
    temp_ids = {r.to_id for r in ordered} - {"sensor.a", "sensor.b"}
    assert len(temp_ids) == 1
    assert all(is_valid_entity_id(i) for i in temp_ids)


def test_three_cycle_and_independent_rename() -> None:
    renames = [
        Rename("sensor.a", "sensor.b"),
        Rename("sensor.b", "sensor.c"),
        Rename("sensor.c", "sensor.a"),
        Rename("light.x", "light.y"),
    ]
    ordered = order_renames(renames)
    start = {"sensor.a", "sensor.b", "sensor.c", "light.x"}
    assert _simulate(start, ordered) == {"sensor.a", "sensor.b", "sensor.c", "light.y"}
    assert all(is_valid_entity_id(r.to_id) for r in ordered)


def _blockers(
    renames: list[Rename], registry: set[str], states: set[str] | None = None
) -> list[str]:
    return run_preflight(renames, registry, registry if states is None else states).blockers


def test_blocker_target_exists_including_suffix_id() -> None:
    registry = {"sensor.foo", "sensor.foo_2"}
    assert _blockers([Rename("sensor.foo", "sensor.foo_2")], registry)


def test_blocker_target_taken_only_in_state_machine() -> None:
    registry = {"sensor.foo"}
    assert _blockers([Rename("sensor.foo", "sensor.bar")], registry, {"sensor.foo", "sensor.bar"})


def test_blocker_domain_change() -> None:
    assert _blockers([Rename("sensor.foo", "light.foo")], {"sensor.foo"})


def test_blocker_missing_source() -> None:
    assert _blockers([Rename("sensor.foo", "sensor.bar")], set())


def test_blocker_invalid_new_id() -> None:
    assert _blockers([Rename("sensor.foo", "sensor.Bar")], {"sensor.foo"})


def test_blocker_duplicate_target_and_duplicate_source() -> None:
    registry = {"sensor.a", "sensor.b"}
    assert _blockers([Rename("sensor.a", "sensor.c"), Rename("sensor.b", "sensor.c")], registry)
    assert _blockers([Rename("sensor.a", "sensor.c"), Rename("sensor.a", "sensor.d")], registry)


def test_blocker_unchanged_id() -> None:
    assert _blockers([Rename("sensor.a", "sensor.a")], {"sensor.a"})


def test_target_is_other_from_in_same_plan_is_allowed() -> None:
    registry = {"sensor.a", "sensor.b"}
    renames = [Rename("sensor.a", "sensor.b"), Rename("sensor.b", "sensor.c")]
    assert _blockers(renames, registry) == []


def test_warning_for_source_without_state() -> None:
    result = run_preflight([Rename("sensor.a", "sensor.b")], {"sensor.a"}, set())
    assert result.blockers == []
    assert result.warnings


def test_diff_is_unified_and_empty_when_equal() -> None:
    diff = render_diff("automations.yaml", "a: sensor.foo\nb: 1\n", "a: sensor.bar\nb: 1\n")
    assert diff.startswith("--- a/automations.yaml\n+++ b/automations.yaml\n")
    assert "-a: sensor.foo\n+a: sensor.bar\n" in diff
    assert render_diff("x.yaml", "same\n", "same\n") == ""
