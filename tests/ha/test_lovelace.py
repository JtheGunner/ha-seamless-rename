import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.dashboard import LovelaceStorage
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from custom_components.seamless_rename.const import WORK_DIR_NAME
from custom_components.seamless_rename.engine.models import Rename
from custom_components.seamless_rename.ha import api, lovelace
from custom_components.seamless_rename.ha.api import PlanRequest
from custom_components.seamless_rename.ha.lovelace import AdapterUnavailable, DashboardRef

from .conftest import add_entity

DASHBOARD: dict[str, Any] = {
    "views": [
        {
            "title": "Home",
            "cards": [
                {"type": "entities", "entities": ["sensor.foo", "light.keep"]},
                {"type": "markdown", "content": "{{ states('sensor.foo') }}"},
            ],
        }
    ]
}


def _fresh() -> dict[str, Any]:
    return json.loads(json.dumps(DASHBOARD))


async def _setup(hass: HomeAssistant, *, default: bool = True, named: bool = False) -> None:
    assert await async_setup_component(hass, "lovelace", {})
    dashboards = hass.data[LOVELACE_DATA].dashboards
    if default:
        await dashboards[None].async_save(_fresh())
    if named:
        item = {"id": "kitchen", "url_path": "kitchen", "mode": "storage", "title": "Kitchen"}
        dashboards["kitchen"] = LovelaceStorage(hass, item)
        await dashboards["kitchen"].async_save(_fresh())


async def _plan(hass: HomeAssistant) -> api.PlanResult:
    return await api.plan(hass, PlanRequest(renames=(Rename("sensor.foo", "sensor.bar"),)))


async def test_plan_includes_storage_dashboard_edits(hass: HomeAssistant, config_dir: Path) -> None:
    add_entity(hass, "sensor.foo")
    await _setup(hass)

    result = await _plan(hass)

    assert result.summary["dashboards"] == {"default": {"certain": 1, "likely": 1, "uncertain": 0}}
    assert "lovelace/default.json" in result.diff
    assert '"sensor.bar"' in result.diff
    assert "sensor.bar" in "".join(
        line for line in result.diff.splitlines() if line.startswith("+")
    )


async def test_apply_rewrites_dashboard_and_snapshot_allows_undo(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    await _setup(hass, named=True)
    plan = await _plan(hass)

    applied = await api.apply(hass, plan.plan_id)

    assert sorted(applied.changed_dashboards) == ["default", "kitchen"]
    dashboards = hass.data[LOVELACE_DATA].dashboards
    for key in (None, "kitchen"):
        saved = await dashboards[key].async_load(False)
        assert saved["views"][0]["cards"][0]["entities"] == ["sensor.bar", "light.keep"]
        assert saved["views"][0]["cards"][1]["content"] == "{{ states('sensor.bar') }}"
    backup = config_dir / WORK_DIR_NAME / "backups" / applied.apply_id
    assert len(list((backup / "dashboards").iterdir())) == 2

    undone = await api.undo(hass, applied.apply_id)

    assert undone.status == "undone"
    for key in (None, "kitchen"):
        assert await dashboards[key].async_load(False) == DASHBOARD
    assert er.async_get(hass).async_get("sensor.foo") is not None


async def test_undo_refuses_when_dashboard_changed_unless_forced(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    await _setup(hass)
    applied = await api.apply(hass, (await _plan(hass)).plan_id)
    dashboards = hass.data[LOVELACE_DATA].dashboards
    await dashboards[None].async_save({"views": []})

    with pytest.raises(api.UndoRefused, match="dashboard default"):
        await api.undo(hass, applied.apply_id)
    await api.undo(hass, applied.apply_id, force=True)
    assert await dashboards[None].async_load(False) == DASHBOARD


async def test_default_dashboard_handled(hass: HomeAssistant, config_dir: Path) -> None:
    await _setup(hass)
    refs = await lovelace.list_dashboards(hass)
    assert refs == [DashboardRef(None)]
    config, digest = await lovelace.load_dashboard(hass, refs[0])
    assert config == DASHBOARD
    assert digest == lovelace.config_hash(DASHBOARD)
    await lovelace.save_dashboard(hass, refs[0], {"views": []})
    assert (await lovelace.load_dashboard(hass, refs[0]))[0] == {"views": []}


async def test_adapter_unavailable_falls_back_to_report_only(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    (config_dir / "a.yaml").write_text("x: sensor.foo\n")
    await _setup(hass)

    with patch.object(lovelace, "list_dashboards", side_effect=AdapterUnavailable("API changed")):
        plan = await _plan(hass)
    assert plan.summary["dashboards"] == {}
    assert any("dashboards were not scanned" in w for w in plan.warnings)

    applied = await api.apply(hass, plan.plan_id)  # the YAML part still applies
    assert applied.changed_files == ["a.yaml"]
    assert applied.changed_dashboards == []
    saved = await hass.data[LOVELACE_DATA].dashboards[None].async_load(False)
    assert saved == DASHBOARD


async def test_unreadable_single_dashboard_becomes_warning(
    hass: HomeAssistant, config_dir: Path
) -> None:
    add_entity(hass, "sensor.foo")
    await _setup(hass, named=True)
    real = lovelace.load_dashboard

    async def flaky(hass_: HomeAssistant, ref: DashboardRef) -> Any:
        if ref.url_path == "kitchen":
            raise AdapterUnavailable("boom")
        return await real(hass_, ref)

    with patch.object(lovelace, "load_dashboard", flaky):
        plan = await _plan(hass)
    assert list(plan.summary["dashboards"]) == ["default"]
    assert any("kitchen" in w for w in plan.warnings)


async def test_dashboard_without_saved_config_is_skipped_without_warning(
    hass: HomeAssistant, config_dir: Path
) -> None:
    add_entity(hass, "sensor.foo")
    await _setup(hass, default=False, named=True)  # the default dashboard was never customised

    plan = await _plan(hass)
    assert list(plan.summary["dashboards"]) == ["kitchen"]
    assert not any("default" in w for w in plan.warnings)


async def test_without_lovelace_plan_has_no_dashboards(
    hass: HomeAssistant, config_dir: Path
) -> None:
    add_entity(hass, "sensor.foo")
    plan = await _plan(hass)
    assert plan.summary["dashboards"] == {}
    assert not any("dashboards" in w for w in plan.warnings)


async def test_apply_refuses_when_dashboard_changed_after_plan(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    await _setup(hass)
    plan = await _plan(hass)
    await hass.data[LOVELACE_DATA].dashboards[None].async_save({"views": []})
    with pytest.raises(api.PlanStale, match="dashboard default"):
        await api.apply(hass, plan.plan_id)
    assert er.async_get(hass).async_get("sensor.foo") is not None


async def test_dashboard_save_failure_rolls_back_everything(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    target = config_dir / "a.yaml"
    target.write_text("x: sensor.foo\n")
    await _setup(hass, named=True)
    plan = await _plan(hass)
    real = lovelace.save_dashboard
    calls = {"n": 0}

    async def flaky(hass_: HomeAssistant, ref: DashboardRef, config: dict[str, Any]) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise AdapterUnavailable("disk full")
        await real(hass_, ref, config)

    with patch.object(api, "save_dashboard", flaky), pytest.raises(api.ApplyFailed):
        await api.apply(hass, plan.plan_id)

    dashboards = hass.data[LOVELACE_DATA].dashboards
    for key in (None, "kitchen"):
        assert await dashboards[key].async_load(False) == DASHBOARD
    assert target.read_text() == "x: sensor.foo\n"
    assert er.async_get(hass).async_get("sensor.foo") is not None


async def test_snapshot_names_are_validated(config_dir: Path) -> None:
    with pytest.raises(ValueError, match="invalid snapshot"):
        lovelace.read_snapshot(config_dir, "../../etc/passwd")
