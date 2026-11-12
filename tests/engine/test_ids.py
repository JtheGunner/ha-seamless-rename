import pytest

from custom_components.entity_rename_safe.engine.ids import (
    build_token_pattern,
    is_valid_entity_id,
    object_id,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("sensor.foo", True),
        ("media_player.snapcast_client_1", True),
        ("sensor.Foo", False),
        ("sensor.", False),
        ("sensor", False),
        ("sensor.foo.bar", False),
        ("sensor._foo", False),
        ("sensor.foo_", False),
        ("sensor.a__b", False),
        ("1sensor.foo", True),
    ],
)
def test_valid_ids(value: str, expected: bool) -> None:
    assert is_valid_entity_id(value) is expected


def test_object_id() -> None:
    assert object_id("sensor.foo_bar") == "foo_bar"


@pytest.mark.parametrize(
    "text", ["sensor.foo_2", "sensor.foo_22", "binary_sensor.foo", "xsensor.foo"]
)
def test_pattern_does_not_match_suffix_or_prefix(text: str) -> None:
    assert build_token_pattern(["sensor.foo"]).search(text) is None


def test_pattern_matches_dotted_states_access() -> None:
    match = build_token_pattern(["sensor.foo"]).search("{{ states.sensor.foo.state }}")
    assert match is not None
    assert match.group(0).endswith("sensor.foo")


def test_pattern_rejects_other_prefix_before_states() -> None:
    assert build_token_pattern(["sensor.foo"]).search("other_states.sensor.foo") is None


@pytest.mark.parametrize("text", ["sensor.foo", "'sensor.foo'", "- sensor.foo\n", "a,sensor.foo,b"])
def test_pattern_matches_plain_occurrences(text: str) -> None:
    assert build_token_pattern(["sensor.foo"]).search(text) is not None


def test_longest_first() -> None:
    pattern = build_token_pattern(["sensor.foo", "sensor.foo_bar"])
    assert [m.group("id") for m in pattern.finditer("sensor.foo_bar sensor.foo")] == [
        "sensor.foo_bar",
        "sensor.foo",
    ]
