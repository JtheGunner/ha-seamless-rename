import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component

from custom_components.entity_rename_safe import repairs
from custom_components.entity_rename_safe.const import DOMAIN, WORK_DIR_NAME
from custom_components.entity_rename_safe.engine.models import Rename
from custom_components.entity_rename_safe.ha import api, recovery
from custom_components.entity_rename_safe.ha.api import PlanRequest

from .conftest import add_entity


def _issues(hass: HomeAssistant) -> list[str]:
    return sorted(issue_id for (domain, issue_id) in ir.async_get(hass).issues if domain == DOMAIN)


async def _crashed_apply(hass: HomeAssistant, config_dir: Path, *pairs: tuple[str, str]) -> str:
    """Run an apply that dies right after the first registry rename, like a crash would."""
    plan = await api.plan(hass, PlanRequest(renames=tuple(Rename(a, b) for a, b in pairs)))
    real = api.rename_entity
    calls = {"n": 0}

    def crash(hass_: HomeAssistant, old: str, new: str) -> None:
        calls["n"] += 1
        real(hass_, old, new)
        if calls["n"] == 1:
            raise KeyboardInterrupt  # not an Exception: no rollback runs, like a killed process

    with (
        patch.object(api, "rename_entity", crash),
        # a killed process runs no rollback and writes no final manifest status
        patch.object(api, "_undo_registry", return_value=[]),
        patch.object(api, "restore_files"),
        patch.object(api, "_finish_manifest"),
        pytest.raises(KeyboardInterrupt),
    ):
        await api.apply(hass, plan.plan_id)
    backups = config_dir / WORK_DIR_NAME / "backups"
    (apply_dir,) = list(backups.iterdir())
    return apply_dir.name


def _mark_in_progress(config_dir: Path, apply_id: str) -> None:
    manifest = config_dir / WORK_DIR_NAME / "backups" / apply_id / "manifest.json"
    data = json.loads(manifest.read_text())
    data["status"] = "in_progress"
    manifest.write_text(json.dumps(data))


async def test_in_progress_manifest_creates_repair(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    (config_dir / "a.yaml").write_text("x: sensor.foo\n")
    apply_id = await _crashed_apply(hass, config_dir, ("sensor.foo", "sensor.bar"))
    _mark_in_progress(config_dir, apply_id)

    await recovery.check_incomplete_applies(hass)

    assert _issues(hass) == [f"incomplete_apply_{apply_id}"]
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"incomplete_apply_{apply_id}")
    assert issue is not None and issue.is_fixable
    assert issue.translation_placeholders == {"apply_id": apply_id}


async def test_completed_manifest_creates_none(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    plan = await api.plan(hass, PlanRequest(renames=(Rename("sensor.foo", "sensor.bar"),)))
    await api.apply(hass, plan.plan_id)
    await recovery.check_incomplete_applies(hass)
    assert _issues(hass) == []


async def test_setup_runs_the_check_and_stale_issues_are_cleared(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    apply_id = await _crashed_apply(hass, config_dir, ("sensor.foo", "sensor.bar"))
    _mark_in_progress(config_dir, apply_id)
    assert await async_setup_component(hass, DOMAIN, {})
    assert _issues(hass) == [f"incomplete_apply_{apply_id}"]

    ir.async_create_issue(
        hass,
        DOMAIN,
        "incomplete_apply_gone",
        is_fixable=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key="incomplete_apply",
    )
    await recovery.check_incomplete_applies(hass)
    assert _issues(hass) == [f"incomplete_apply_{apply_id}"]


async def test_garbage_manifests_are_ignored(hass: HomeAssistant, config_dir: Path) -> None:
    bad = config_dir / WORK_DIR_NAME / "backups" / "apply-bad"
    bad.mkdir(parents=True)
    (bad / "manifest.json").write_text("{not json")
    await recovery.check_incomplete_applies(hass)
    assert _issues(hass) == []


async def test_repair_fix_runs_undo(hass: HomeAssistant, config_dir: Path, check_ok: None) -> None:
    add_entity(hass, "sensor.a")
    add_entity(hass, "sensor.b")
    target = config_dir / "t.yaml"
    target.write_text("x: sensor.a\ny: sensor.b\n")
    apply_id = await _crashed_apply(
        hass, config_dir, ("sensor.a", "sensor.a2"), ("sensor.b", "sensor.b2")
    )
    # the crash left the files rewritten and only the first entity renamed
    assert target.read_text() == "x: sensor.a2\ny: sensor.b2\n"
    registry = er.async_get(hass)
    assert (
        registry.async_get("sensor.a2") is not None and registry.async_get("sensor.b") is not None
    )
    _mark_in_progress(config_dir, apply_id)
    await recovery.check_incomplete_applies(hass)

    flow = await repairs.async_create_fix_flow(
        hass, f"incomplete_apply_{apply_id}", {"apply_id": apply_id}
    )
    flow.hass = hass
    form = await flow.async_step_init()
    assert form["type"] == "form" and form["step_id"] == "confirm"
    result = await flow.async_step_confirm({})

    assert result["type"] == "create_entry"
    assert target.read_text() == "x: sensor.a\ny: sensor.b\n"
    assert registry.async_get("sensor.a") is not None and registry.async_get("sensor.b") is not None
    assert registry.async_get("sensor.a2") is None
    manifest = json.loads(
        (config_dir / WORK_DIR_NAME / "backups" / apply_id / "manifest.json").read_text()
    )
    assert manifest["status"] == "rolled_back"
    await recovery.check_incomplete_applies(hass)
    assert _issues(hass) == []


async def test_recovery_repairs_a_swap_stopped_midway(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.a")
    add_entity(hass, "sensor.b")
    apply_id = await _crashed_apply(
        hass, config_dir, ("sensor.a", "sensor.b"), ("sensor.b", "sensor.a")
    )
    registry = er.async_get(hass)
    assert registry.async_get("sensor.a") is None  # a sits on a temporary ID now
    _mark_in_progress(config_dir, apply_id)

    await api.undo(hass, apply_id)

    assert registry.async_get("sensor.a").unique_id == "uid-sensor.a"  # type: ignore[union-attr]
    assert registry.async_get("sensor.b").unique_id == "uid-sensor.b"  # type: ignore[union-attr]


async def test_repair_flow_reports_a_failed_undo(hass: HomeAssistant, config_dir: Path) -> None:
    flow = await repairs.async_create_fix_flow(hass, "incomplete_apply_apply-missing", None)
    flow.hass = hass
    result = await flow.async_step_confirm({})
    assert result["type"] == "abort" and result["reason"] == "undo_failed"


async def test_undo_refuses_other_statuses(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    plan = await api.plan(hass, PlanRequest(renames=(Rename("sensor.foo", "sensor.bar"),)))
    applied = await api.apply(hass, plan.plan_id)
    manifest = config_dir / WORK_DIR_NAME / "backups" / applied.apply_id / "manifest.json"
    data = json.loads(manifest.read_text())
    data["status"] = "failed"
    manifest.write_text(json.dumps(data))
    with pytest.raises(api.UndoRefused, match="interrupted"):
        await api.undo(hass, applied.apply_id)


async def test_recovery_refuses_files_edited_after_the_crash_unless_forced(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    target = config_dir / "t.yaml"
    target.write_text("x: sensor.foo\n")
    apply_id = await _crashed_apply(hass, config_dir, ("sensor.foo", "sensor.bar"))
    target.write_text("x: sensor.bar\n# edited after the crash\n")

    with pytest.raises(api.UndoRefused, match="changed since"):
        await api.undo(hass, apply_id)
    assert "edited after the crash" in target.read_text()

    await api.undo(hass, apply_id, force=True)
    assert target.read_text() == "x: sensor.foo\n"


async def test_recovery_accepts_untouched_and_apply_written_files(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    target = config_dir / "t.yaml"
    target.write_text("x: sensor.foo\n")
    apply_id = await _crashed_apply(hass, config_dir, ("sensor.foo", "sensor.bar"))
    target.write_text("x: sensor.foo\n")  # the write never happened: still pristine
    await api.undo(hass, apply_id)
    assert target.read_text() == "x: sensor.foo\n"


async def test_recovery_warns_about_entities_it_cannot_locate(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    apply_id = await _crashed_apply(hass, config_dir, ("sensor.foo", "sensor.bar"))
    manifest_path = config_dir / WORK_DIR_NAME / "backups" / apply_id / "manifest.json"
    data = json.loads(manifest_path.read_text())
    data["entity_registry_ids"] = {}
    manifest_path.write_text(json.dumps(data))

    result = await api.undo(hass, apply_id)

    assert result.status == "rolled_back"
    assert any("sensor.foo could not be located" in w for w in result.warnings)


async def test_undo_refuses_an_apply_that_is_still_running(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    apply_id = await _crashed_apply(hass, config_dir, ("sensor.foo", "sensor.bar"))
    api._running_applies(hass).add(apply_id)
    try:
        with pytest.raises(api.UndoRefused, match="still running"):
            await api.undo(hass, apply_id)
    finally:
        api._running_applies(hass).discard(apply_id)
    assert api._running_applies(hass) == set()


async def test_repair_flow_aborts_on_unexpected_errors(
    hass: HomeAssistant, config_dir: Path
) -> None:
    flow = await repairs.async_create_fix_flow(hass, "incomplete_apply_x", {"apply_id": "x"})
    flow.hass = hass
    with patch.object(api, "undo", side_effect=OSError("disk gone")):
        result = await flow.async_step_confirm({})
    assert result["type"] == "abort" and result["reason"] == "undo_failed"


async def test_unreadable_manifest_is_logged(
    hass: HomeAssistant, config_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    bad = config_dir / WORK_DIR_NAME / "backups" / "apply-bad"
    bad.mkdir(parents=True)
    (bad / "manifest.json").write_text("{not json")
    caplog.set_level(logging.WARNING, logger=recovery.__name__)
    await recovery.check_incomplete_applies(hass)
    assert "unreadable manifest" in caplog.text
