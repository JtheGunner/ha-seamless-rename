from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant

from custom_components.seamless_rename.engine.models import Rename
from custom_components.seamless_rename.ha import api
from custom_components.seamless_rename.ha.api import PlanRequest

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


def _request(include_uncertain: bool = False) -> PlanRequest:
    return PlanRequest(
        renames=(Rename("sensor.foo", "sensor.bar"),), include_uncertain=include_uncertain
    )


async def test_plan_lists_findings_with_default_selection(
    hass: HomeAssistant, config_dir: Path
) -> None:
    add_entity(hass, "sensor.foo")
    (config_dir / "automations.yaml").write_text(AUTOMATIONS)

    result = await api.plan(hass, _request())

    by_level = {row["confidence"]: row for row in result.findings}
    assert set(by_level) == {"certain", "likely", "uncertain"}
    assert by_level["certain"]["selected"] is True
    assert by_level["likely"]["selected"] is True
    assert by_level["uncertain"]["selected"] is False
    assert all(
        row["kind"] == "file" and row["source"] == "automations.yaml" for row in by_level.values()
    )
    assert result.to_response()["findings"] == result.findings


async def test_include_uncertain_rewrites_the_comment(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    target = config_dir / "automations.yaml"
    target.write_text(AUTOMATIONS)

    plan = await api.plan(hass, _request(include_uncertain=True))
    assert all(row["selected"] for row in plan.findings)
    await api.apply(hass, plan.plan_id)

    assert "sensor.foo" not in target.read_text()


async def test_apply_leaves_excluded_findings_untouched(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    target = config_dir / "automations.yaml"
    target.write_text(AUTOMATIONS)
    plan = await api.plan(hass, _request())
    likely = next(row for row in plan.findings if row["confidence"] == "likely")

    result = await api.apply(hass, plan.plan_id, exclude=[likely["finding_id"]])

    text = target.read_text()
    assert "entity_id: sensor.bar" in text
    assert "states('sensor.foo')" in text
    manifest = next((config_dir / ".seamless_rename" / "backups").glob("*/manifest.json"))
    assert likely["finding_id"] in manifest.read_text()
    undone = await api.undo(hass, result.apply_id)
    assert undone.status == "undone"
    assert target.read_text() == AUTOMATIONS


async def test_excluding_every_finding_changes_no_file(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    target = config_dir / "automations.yaml"
    target.write_text(AUTOMATIONS)
    plan = await api.plan(hass, _request())

    result = await api.apply(
        hass, plan.plan_id, exclude=[row["finding_id"] for row in plan.findings]
    )

    assert result.changed_files == []
    assert target.read_text() == AUTOMATIONS


async def test_unknown_excluded_finding_is_rejected(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    (config_dir / "automations.yaml").write_text(AUTOMATIONS)
    plan = await api.plan(hass, _request())

    with pytest.raises(api.UnknownFinding, match="nope"):
        await api.apply(hass, plan.plan_id, exclude=["nope"])
