from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.entity_rename_safe.engine.models import Rename
from custom_components.entity_rename_safe.ha import api, helpers
from custom_components.entity_rename_safe.ha.api import PlanRequest
from custom_components.entity_rename_safe.ha.lovelace import AdapterUnavailable

from .conftest import add_entity


def _entry(
    hass: HomeAssistant, domain: str, *, options: dict[str, Any], data: dict[str, Any] | None = None
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=domain, title=f"{domain} helper", options=options, data=data or {}
    )
    entry.add_to_hass(hass)
    return entry


async def _plan(hass: HomeAssistant) -> api.PlanResult:
    return await api.plan(hass, PlanRequest(renames=(Rename("sensor.foo", "sensor.bar"),)))


async def test_min_max_entity_ids_rewritten(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    entry = _entry(
        hass, "min_max", options={"entity_ids": ["sensor.foo", "sensor.other"], "type": "max"}
    )
    plan = await _plan(hass)
    assert plan.summary["helpers"] == {
        f"min_max:{entry.entry_id}": {"certain": 1, "likely": 0, "uncertain": 0}
    }
    assert f"helpers/min_max-{entry.entry_id}.json" in plan.diff

    result = await api.apply(hass, plan.plan_id)

    assert result.changed_helpers == [entry.entry_id]
    assert dict(entry.options) == {"entity_ids": ["sensor.bar", "sensor.other"], "type": "max"}


async def test_ui_group_entities_rewritten(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    entry = _entry(hass, "group", options={"entities": ["sensor.foo"], "group_type": "sensor"})
    result = await api.apply(hass, (await _plan(hass)).plan_id)
    assert result.changed_helpers == [entry.entry_id]
    assert list(entry.options["entities"]) == ["sensor.bar"]


async def test_data_hit_is_report_only(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    entry = _entry(hass, "custom_thing", options={}, data={"source": "sensor.foo"})
    plan = await _plan(hass)
    assert plan.summary["helpers"] == {}
    assert any("custom_thing" in w and "manually" in w for w in plan.warnings)

    result = await api.apply(hass, plan.plan_id)

    assert result.changed_helpers == []
    assert dict(entry.data) == {"source": "sensor.foo"}


async def test_uuid_storing_helper_untouched(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    uuid = er.async_get(hass).async_get("sensor.foo").id  # type: ignore[union-attr]
    entry = _entry(hass, "threshold", options={"entity_id": uuid, "upper": 5})
    plan = await _plan(hass)
    assert plan.summary["helpers"] == {}
    result = await api.apply(hass, plan.plan_id)
    assert result.changed_helpers == []
    assert dict(entry.options) == {"entity_id": uuid, "upper": 5}


async def test_self_following_helper_not_double_edited(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    entry = _entry(hass, "derivative", options={"source": "sensor.foo"})
    updates: list[dict[str, Any]] = []

    @callback
    def follow(event: Event) -> None:
        if event.data.get("old_entity_id") == "sensor.foo":
            options = {"source": event.data["entity_id"]}
            updates.append(options)
            hass.config_entries.async_update_entry(entry, options=options)

    hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, follow)
    plan = await _plan(hass)
    assert list(plan.summary["helpers"]) == [f"derivative:{entry.entry_id}"]

    result = await api.apply(hass, plan.plan_id)

    assert updates == [{"source": "sensor.bar"}]  # the helper edited itself exactly once
    assert result.changed_helpers == []  # verified, not edited by the adapter
    assert dict(entry.options) == {"source": "sensor.bar"}

    await api.undo(hass, result.apply_id)
    assert dict(entry.options) == {"source": "sensor.foo"}


async def test_undo_restores_helper_options_unless_changed(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    entry = _entry(hass, "min_max", options={"entity_ids": ["sensor.foo"]})
    result = await api.apply(hass, (await _plan(hass)).plan_id)

    hass.config_entries.async_update_entry(entry, options={"entity_ids": ["sensor.edited"]})
    with pytest.raises(api.UndoRefused, match="helper"):
        await api.undo(hass, result.apply_id)

    await api.undo(hass, result.apply_id, force=True)
    assert list(entry.options["entity_ids"]) == ["sensor.foo"]


async def test_apply_refuses_when_helper_changed_after_plan(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    entry = _entry(hass, "min_max", options={"entity_ids": ["sensor.foo"]})
    plan = await _plan(hass)
    hass.config_entries.async_update_entry(entry, options={"entity_ids": ["sensor.foo", "x.y"]})
    with pytest.raises(api.PlanStale, match="helper"):
        await api.apply(hass, plan.plan_id)
    assert er.async_get(hass).async_get("sensor.foo") is not None


async def test_helper_failure_rolls_back_everything(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    target = config_dir / "a.yaml"
    target.write_text("x: sensor.foo\n")
    first = _entry(hass, "min_max", options={"entity_ids": ["sensor.foo"]})
    second = _entry(hass, "group", options={"entities": ["sensor.foo"]})
    plan = await _plan(hass)
    real = helpers.set_options
    calls = {"n": 0}

    def flaky(hass_: HomeAssistant, entry_id: str, options: dict[str, Any]) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise AdapterUnavailable("boom")
        real(hass_, entry_id, options)

    with patch.object(helpers, "set_options", flaky), pytest.raises(api.ApplyFailed):
        await api.apply(hass, plan.plan_id)

    assert list(first.options["entity_ids"]) == ["sensor.foo"]
    assert list(second.options["entities"]) == ["sensor.foo"]
    assert target.read_text() == "x: sensor.foo\n"
    assert er.async_get(hass).async_get("sensor.foo") is not None


async def test_adapter_unavailable_falls_back_to_report_only(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    (config_dir / "a.yaml").write_text("x: sensor.foo\n")
    entry = _entry(hass, "min_max", options={"entity_ids": ["sensor.foo"]})
    with patch.object(helpers, "scan_entries", side_effect=AdapterUnavailable("API changed")):
        plan = await _plan(hass)
    assert any("helpers were not scanned" in w for w in plan.warnings)
    result = await api.apply(hass, plan.plan_id)
    assert result.changed_files == ["a.yaml"]
    assert list(entry.options["entity_ids"]) == ["sensor.foo"]


async def test_own_entry_is_never_scanned(hass: HomeAssistant, config_dir: Path) -> None:
    add_entity(hass, "sensor.foo")
    _entry(hass, "entity_rename_safe", options={"note": "sensor.foo"})
    assert (await _plan(hass)).summary["helpers"] == {}


async def test_snapshot_names_are_validated(config_dir: Path) -> None:
    with pytest.raises(ValueError, match="invalid snapshot"):
        helpers.read_snapshot(config_dir, "../x.json")


async def test_helper_not_in_plan_is_not_edited_but_reported(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    planned = _entry(hass, "min_max", options={"entity_ids": ["sensor.foo"]})
    plan = await _plan(hass)
    late = _entry(hass, "group", options={"entities": ["sensor.foo"]})

    result = await api.apply(hass, plan.plan_id)

    assert result.changed_helpers == [planned.entry_id]
    assert list(late.options["entities"]) == ["sensor.foo"]
    assert any(late.entry_id in w and "not in the plan" in w for w in result.warnings)


async def test_malformed_plan_sections_are_a_plan_error(
    hass: HomeAssistant, config_dir: Path
) -> None:
    import json

    add_entity(hass, "sensor.foo")
    plan = await _plan(hass)
    plan_file = config_dir / ".entity_rename_safe" / "plans" / f"{plan.plan_id}.json"
    data = json.loads(plan_file.read_text())
    data["helpers"] = [{"entry_id": "x"}]
    data["plan_hash"] = api._canonical_hash(data)
    plan_file.write_text(json.dumps(data))
    with pytest.raises(api.PlanStale, match="malformed"):
        await api.apply(hass, plan.plan_id)


async def test_undo_rejects_unknown_snapshot_names(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    import json

    add_entity(hass, "sensor.foo")
    result = await api.apply(hass, (await _plan(hass)).plan_id)
    manifest = config_dir / ".entity_rename_safe" / "backups" / result.apply_id / "manifest.json"
    data = json.loads(manifest.read_text())
    data["snapshots"] = ["other/evil.json"]
    manifest.write_text(json.dumps(data))
    with pytest.raises(api.UndoRefused, match="unknown snapshots"):
        await api.undo(hass, result.apply_id)
