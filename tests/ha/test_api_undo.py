from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.seamless_rename.engine.models import Rename
from custom_components.seamless_rename.ha import api
from custom_components.seamless_rename.ha.api import PlanRequest

from .conftest import add_entity

ORIGINAL = "trigger:\n  entity_id: sensor.foo  # keep\n"


async def _apply(hass: HomeAssistant, config_dir: Path) -> api.ApplyResult:
    add_entity(hass, "sensor.foo")
    (config_dir / "a.yaml").write_text(ORIGINAL)
    plan = await api.plan(hass, PlanRequest(renames=(Rename("sensor.foo", "sensor.bar"),)))
    return await api.apply(hass, plan.plan_id)


async def test_undo_restores_files_byte_identical_and_registry(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    result = await _apply(hass, config_dir)
    undone = await api.undo(hass, result.apply_id)
    assert undone.status == "undone"
    assert (config_dir / "a.yaml").read_bytes() == ORIGINAL.encode()
    assert er.async_get(hass).async_get("sensor.foo") is not None
    assert er.async_get(hass).async_get("sensor.bar") is None


async def test_undo_refuses_when_file_changed_unless_forced(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    result = await _apply(hass, config_dir)
    (config_dir / "a.yaml").write_text("changed by the user\n")
    with pytest.raises(api.UndoRefused, match="changed"):
        await api.undo(hass, result.apply_id)
    assert er.async_get(hass).async_get("sensor.bar") is not None

    await api.undo(hass, result.apply_id, force=True)
    assert (config_dir / "a.yaml").read_bytes() == ORIGINAL.encode()


async def test_undo_twice_is_refused(hass: HomeAssistant, config_dir: Path, check_ok: None) -> None:
    result = await _apply(hass, config_dir)
    await api.undo(hass, result.apply_id)
    with pytest.raises(api.UndoRefused, match="status"):
        await api.undo(hass, result.apply_id)


async def test_undo_unknown_or_malicious_id(hass: HomeAssistant, config_dir: Path) -> None:
    with pytest.raises(api.PlanNotFound):
        await api.undo(hass, "apply-missing")
    with pytest.raises(api.PlanNotFound):
        await api.undo(hass, "../x")


async def test_undo_registry_failure_reverts_partial_work(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    result = await _apply(hass, config_dir)
    with (
        patch.object(api, "rename_entity", side_effect=ValueError("boom")),
        pytest.raises(api.UndoRefused, match="boom"),
    ):
        await api.undo(hass, result.apply_id)
    assert (config_dir / "a.yaml").read_text() == "trigger:\n  entity_id: sensor.bar  # keep\n"
    assert er.async_get(hass).async_get("sensor.bar") is not None


async def test_undo_with_damaged_backup_leaves_registry_alone(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    result = await _apply(hass, config_dir)
    files = config_dir / ".seamless_rename" / "backups" / result.apply_id / "files"
    for copy in files.iterdir():
        copy.write_text("damaged")
    with pytest.raises(api.UndoRefused):
        await api.undo(hass, result.apply_id)
    assert er.async_get(hass).async_get("sensor.bar") is not None
    assert er.async_get(hass).async_get("sensor.foo") is None


async def test_undo_corrupt_manifest_is_refused(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    result = await _apply(hass, config_dir)
    manifest = config_dir / ".seamless_rename" / "backups" / result.apply_id / "manifest.json"
    manifest.write_text("{bad")
    with pytest.raises(api.UndoRefused):
        await api.undo(hass, result.apply_id)
