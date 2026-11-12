import json
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant

from custom_components.entity_rename_safe.const import WORK_DIR_NAME
from custom_components.entity_rename_safe.engine.models import Rename
from custom_components.entity_rename_safe.ha import api
from custom_components.entity_rename_safe.ha.api import PatternSpec, PlanRequest

from .conftest import add_entity

AUTOMATIONS = (
    "- alias: Music\n"
    "  trigger:\n"
    "    - platform: state\n"
    "      entity_id: sensor.foo\n"
    "  action:\n"
    "    - service: notify.notify\n"
    "      data: {message: \"{{ states('sensor.foo') }}\"}\n"
    "  # note about sensor.foo stays untouched\n"
)


def _request(*pairs: tuple[str, str], **kwargs: object) -> PlanRequest:
    return PlanRequest(renames=tuple(Rename(a, b) for a, b in pairs), **kwargs)  # type: ignore[arg-type]


async def test_plan_writes_json_and_diff(hass: HomeAssistant, config_dir: Path) -> None:
    add_entity(hass, "sensor.foo")
    (config_dir / "automations.yaml").write_text(AUTOMATIONS)

    result = await api.plan(hass, _request(("sensor.foo", "sensor.bar")))

    assert result.blockers == []
    work = config_dir / WORK_DIR_NAME / "plans"
    assert (work / f"{result.plan_id}.json").is_file()
    diff = (work / f"{result.plan_id}.diff").read_text()
    assert "-      entity_id: sensor.foo" in diff
    assert "+      entity_id: sensor.bar" in diff
    assert result.summary["files"] == {
        "automations.yaml": {"certain": 1, "likely": 1, "uncertain": 1}
    }
    assert (config_dir / "automations.yaml").read_text() == AUTOMATIONS  # plan never writes


async def test_plan_with_blocker_is_saved_but_not_applicable(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    add_entity(hass, "sensor.foo_2")
    result = await api.plan(hass, _request(("sensor.foo", "sensor.foo_2")))
    assert result.blockers
    with pytest.raises(api.PlanBlocked):
        await api.apply(hass, result.plan_id)


async def test_plan_from_pattern_resolves_concrete_renames(
    hass: HomeAssistant, config_dir: Path
) -> None:
    add_entity(hass, "sensor.snap_a")
    add_entity(hass, "sensor.snap_b")
    add_entity(hass, "light.keep")
    request = PlanRequest(pattern=PatternSpec(match="snap_", replace="room_", domain="sensor"))
    result = await api.plan(hass, request)
    assert [(r.from_id, r.to_id) for r in result.renames] == [
        ("sensor.snap_a", "sensor.room_a"),
        ("sensor.snap_b", "sensor.room_b"),
    ]


async def test_plan_request_needs_exactly_one_form(hass: HomeAssistant, config_dir: Path) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        await api.plan(hass, PlanRequest())


async def test_plan_reports_pattern_warnings(hass: HomeAssistant, config_dir: Path) -> None:
    add_entity(hass, "sensor.foo")
    (config_dir / "t.yaml").write_text(
        "v: \"{{ states.sensor | selectattr('entity_id') | list }}\"\n"
    )
    result = await api.plan(hass, _request(("sensor.foo", "sensor.bar")))
    assert any("pattern reference" in w for w in result.warnings)


async def test_plan_skips_excluded_and_unreadable_files(
    hass: HomeAssistant, config_dir: Path
) -> None:
    add_entity(hass, "sensor.foo")
    (config_dir / "secrets.yaml").write_text("k: sensor.foo\n")
    (config_dir / "binary.yaml").write_bytes(b"\xff\xfe\x00bad")
    result = await api.plan(hass, _request(("sensor.foo", "sensor.bar")))
    assert result.summary["files"] == {}
    assert any("binary.yaml" in w for w in result.warnings)


async def test_stored_plan_is_valid_json_with_hash(hass: HomeAssistant, config_dir: Path) -> None:
    add_entity(hass, "sensor.foo")
    result = await api.plan(hass, _request(("sensor.foo", "sensor.bar")))
    data = json.loads((config_dir / WORK_DIR_NAME / "plans" / f"{result.plan_id}.json").read_text())
    assert data["plan_hash"] and data["plan_id"] == result.plan_id
