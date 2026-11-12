import json
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.check_config import HomeAssistantConfig

from custom_components.seamless_rename.const import WORK_DIR_NAME
from custom_components.seamless_rename.engine.models import Rename
from custom_components.seamless_rename.ha import api
from custom_components.seamless_rename.ha.api import PlanRequest

from .conftest import CHECK_PATH, add_entity

AUTOMATIONS = (
    "- alias: Music\n"
    "  trigger:\n"
    "    - platform: state\n"
    "      entity_id: sensor.foo\n"
    "  # note about sensor.foo stays untouched\n"
)


def _request(*pairs: tuple[str, str]) -> PlanRequest:
    return PlanRequest(renames=tuple(Rename(a, b) for a, b in pairs))


async def _plan(hass: HomeAssistant, *pairs: tuple[str, str]) -> str:
    return (await api.plan(hass, _request(*pairs))).plan_id


async def test_apply_rewrites_files_and_registry(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    target = config_dir / "automations.yaml"
    target.write_text(AUTOMATIONS)
    plan_id = await _plan(hass, ("sensor.foo", "sensor.bar"))

    result = await api.apply(hass, plan_id)

    assert result.status == "completed"
    assert result.changed_files == ["automations.yaml"]
    assert "entity_id: sensor.bar" in target.read_text()
    assert "note about sensor.foo stays untouched" in target.read_text()
    assert er.async_get(hass).async_get("sensor.bar") is not None
    assert er.async_get(hass).async_get("sensor.foo") is None
    manifest = json.loads(
        (config_dir / WORK_DIR_NAME / "backups" / result.apply_id / "manifest.json").read_text()
    )
    assert manifest["status"] == "completed"
    assert manifest["files"][0]["sha256_after"]


async def test_apply_without_references_renames_registry_only(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    plan_id = await _plan(hass, ("sensor.foo", "sensor.bar"))
    with patch(CHECK_PATH, side_effect=AssertionError("config check must not run")):
        result = await api.apply(hass, plan_id)
    assert result.changed_files == []
    assert er.async_get(hass).async_get("sensor.bar") is not None
    backup = config_dir / WORK_DIR_NAME / "backups" / result.apply_id
    assert list((backup / "files").iterdir()) == []


async def test_config_check_failure_restores_files_and_keeps_registry(
    hass: HomeAssistant, config_dir: Path
) -> None:
    add_entity(hass, "sensor.foo")
    target = config_dir / "automations.yaml"
    target.write_text(AUTOMATIONS)
    plan_id = await _plan(hass, ("sensor.foo", "sensor.bar"))

    with (
        patch(CHECK_PATH, return_value=HomeAssistantConfig().add_error("invalid config")),
        pytest.raises(api.ConfigCheckFailed, match="invalid config"),
    ):
        await api.apply(hass, plan_id)

    assert target.read_text() == AUTOMATIONS
    assert er.async_get(hass).async_get("sensor.foo") is not None


async def test_registry_failure_rolls_back_files_and_earlier_renames(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.a")
    add_entity(hass, "sensor.b")
    target = config_dir / "t.yaml"
    target.write_text("x: sensor.a\ny: sensor.b\n")
    plan_id = await _plan(hass, ("sensor.a", "sensor.a2"), ("sensor.b", "sensor.b2"))

    real = api.rename_entity
    calls = {"n": 0}

    def flaky(hass_: HomeAssistant, old: str, new: str) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValueError("boom")
        real(hass_, old, new)

    with patch.object(api, "rename_entity", flaky), pytest.raises(api.ApplyFailed):
        await api.apply(hass, plan_id)

    assert target.read_text() == "x: sensor.a\ny: sensor.b\n"
    registry = er.async_get(hass)
    assert registry.async_get("sensor.a") is not None
    assert registry.async_get("sensor.b") is not None


async def test_apply_refuses_when_file_changed_after_plan(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    target = config_dir / "automations.yaml"
    target.write_text(AUTOMATIONS)
    plan_id = await _plan(hass, ("sensor.foo", "sensor.bar"))
    target.write_text(AUTOMATIONS + "# edited\n")
    with pytest.raises(api.PlanStale):
        await api.apply(hass, plan_id)
    assert er.async_get(hass).async_get("sensor.foo") is not None


async def test_apply_refuses_expired_plan(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    plan_id = await _plan(hass, ("sensor.foo", "sensor.bar"))
    plan_file = config_dir / WORK_DIR_NAME / "plans" / f"{plan_id}.json"
    data = json.loads(plan_file.read_text())
    data["created_at"] = "2020-01-01T00:00:00+00:00"
    data["plan_hash"] = api._canonical_hash(data)
    plan_file.write_text(json.dumps(data))
    with pytest.raises(api.PlanExpired):
        await api.apply(hass, plan_id)


async def test_apply_detects_tampered_plan(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    plan_id = await _plan(hass, ("sensor.foo", "sensor.bar"))
    plan_file = config_dir / WORK_DIR_NAME / "plans" / f"{plan_id}.json"
    data = json.loads(plan_file.read_text())
    data["renames"][0]["to"] = "sensor.evil"
    plan_file.write_text(json.dumps(data))
    with pytest.raises(api.PlanStale):
        await api.apply(hass, plan_id)


async def test_apply_unknown_or_malicious_plan_id(hass: HomeAssistant, config_dir: Path) -> None:
    with pytest.raises(api.PlanNotFound):
        await api.apply(hass, "plan-missing")
    with pytest.raises(api.PlanNotFound):
        await api.apply(hass, "../../etc/passwd")


async def test_swap_uses_temporary_id_and_ends_swapped(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.a")
    add_entity(hass, "sensor.b")
    (config_dir / "t.yaml").write_text("x: sensor.a\ny: sensor.b\n")
    plan_id = await _plan(hass, ("sensor.a", "sensor.b"), ("sensor.b", "sensor.a"))
    await api.apply(hass, plan_id)
    registry = er.async_get(hass)
    assert registry.async_get("sensor.a").unique_id == "uid-sensor.b"  # type: ignore[union-attr]
    assert registry.async_get("sensor.b").unique_id == "uid-sensor.a"  # type: ignore[union-attr]
    assert (config_dir / "t.yaml").read_text() == "x: sensor.b\ny: sensor.a\n"


async def test_apply_blocks_when_temporary_id_is_taken(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.a")
    add_entity(hass, "sensor.b")
    add_entity(hass, "sensor.rename_safe_tmp_1")
    plan_id = await _plan(hass, ("sensor.a", "sensor.b"), ("sensor.b", "sensor.a"))
    with pytest.raises(api.PlanBlocked, match="temporary"):
        await api.apply(hass, plan_id)
    assert er.async_get(hass).async_get("sensor.a") is not None


async def test_write_failure_midway_restores_all_files(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    (config_dir / "a.yaml").write_text("x: sensor.foo\n")
    (config_dir / "b.yaml").write_text("y: sensor.foo\n")
    plan_id = await _plan(hass, ("sensor.foo", "sensor.bar"))
    real = api.write_atomic
    calls = {"n": 0}

    def flaky(path: Path, data: bytes) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        real(path, data)

    with patch.object(api, "write_atomic", flaky), pytest.raises(api.ApplyFailed):
        await api.apply(hass, plan_id)

    assert (config_dir / "a.yaml").read_text() == "x: sensor.foo\n"
    assert (config_dir / "b.yaml").read_text() == "y: sensor.foo\n"
    assert er.async_get(hass).async_get("sensor.foo") is not None


async def test_config_check_exception_restores_files(hass: HomeAssistant, config_dir: Path) -> None:
    add_entity(hass, "sensor.foo")
    target = config_dir / "a.yaml"
    target.write_text("x: sensor.foo\n")
    plan_id = await _plan(hass, ("sensor.foo", "sensor.bar"))
    with (
        patch(CHECK_PATH, side_effect=RuntimeError("checker crashed")),
        pytest.raises(api.ApplyFailed, match="checker crashed"),
    ):
        await api.apply(hass, plan_id)
    assert target.read_text() == "x: sensor.foo\n"


async def test_failed_rollback_still_restores_files_and_is_reported(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.a")
    add_entity(hass, "sensor.b")
    target = config_dir / "t.yaml"
    target.write_text("x: sensor.a\ny: sensor.b\n")
    plan_id = await _plan(hass, ("sensor.a", "sensor.a2"), ("sensor.b", "sensor.b2"))
    real = api.rename_entity
    calls = {"n": 0}

    def flaky(hass_: HomeAssistant, old: str, new: str) -> None:
        calls["n"] += 1
        if calls["n"] >= 2:
            raise ValueError("boom")
        real(hass_, old, new)

    with (
        patch.object(api, "rename_entity", flaky),
        pytest.raises(api.ApplyFailed, match="manual repair"),
    ):
        await api.apply(hass, plan_id)
    assert target.read_text() == "x: sensor.a\ny: sensor.b\n"


async def test_reload_failure_keeps_completed_status_and_asks_for_restart(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    (config_dir / "automations.yaml").write_text(AUTOMATIONS)
    plan_id = await _plan(hass, ("sensor.foo", "sensor.bar"))
    with patch.object(api, "reload_domains", side_effect=RuntimeError("reload broke")):
        result = await api.apply(hass, plan_id)
    assert result.status == "completed"
    assert result.restart_required
    assert any("reload failed" in w for w in result.warnings)
    manifest = json.loads(
        (config_dir / WORK_DIR_NAME / "backups" / result.apply_id / "manifest.json").read_text()
    )
    assert manifest["status"] == "completed"


async def test_apply_rejects_plan_naming_protected_files(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    plan_id = await _plan(hass, ("sensor.foo", "sensor.bar"))
    plan_file = config_dir / WORK_DIR_NAME / "plans" / f"{plan_id}.json"
    data = json.loads(plan_file.read_text())
    data["base_hashes"] = {"../outside.yaml": "x", ".storage/core.yaml": "y"}
    data["plan_hash"] = api._canonical_hash(data)
    plan_file.write_text(json.dumps(data))
    with pytest.raises(api.PlanStale, match="must not be written"):
        await api.apply(hass, plan_id)


async def test_apply_corrupt_plan_json_is_a_plan_error(
    hass: HomeAssistant, config_dir: Path
) -> None:
    add_entity(hass, "sensor.foo")
    plan_id = await _plan(hass, ("sensor.foo", "sensor.bar"))
    (config_dir / WORK_DIR_NAME / "plans" / f"{plan_id}.json").write_text("{truncated")
    with pytest.raises(api.PlanStale):
        await api.apply(hass, plan_id)


async def test_config_check_result_with_content_but_no_errors_passes(
    hass: HomeAssistant, config_dir: Path
) -> None:
    """The real check returns the parsed configuration, which is truthy even when it is valid."""
    add_entity(hass, "sensor.foo")
    target = config_dir / "automations.yaml"
    target.write_text(AUTOMATIONS)
    plan_id = await _plan(hass, ("sensor.foo", "sensor.bar"))
    parsed = HomeAssistantConfig()
    parsed["homeassistant"] = {"name": "Sample Home"}

    with patch(CHECK_PATH, return_value=parsed):
        result = await api.apply(hass, plan_id)

    assert result.status == "completed"
    assert "sensor.bar" in target.read_text()
