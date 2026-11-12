"""The e2e scenario without a container: the sample config through plan, apply, audit, undo."""

import hashlib
import shutil
from pathlib import Path

from homeassistant.core import HomeAssistant

from custom_components.entity_rename_safe.engine.models import Rename
from custom_components.entity_rename_safe.ha import api
from custom_components.entity_rename_safe.ha.api import PlanRequest

from ..e2e.test_roundtrip import NEW_ID, OLD_ID, YAML_FILES
from .conftest import add_entity

SAMPLE = Path(__file__).parents[1] / "e2e" / "sample_config"


def _hashes(directory: Path) -> dict[str, str]:
    return {n: hashlib.sha256((directory / n).read_bytes()).hexdigest() for n in YAML_FILES}


async def test_sample_config_roundtrip(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    shutil.copytree(SAMPLE, config_dir, dirs_exist_ok=True)
    add_entity(hass, OLD_ID)
    add_entity(hass, "sensor.snap_kitchen_label")
    originals = _hashes(config_dir)

    plan = await api.plan(hass, PlanRequest(renames=(Rename(OLD_ID, NEW_ID),)))
    assert plan.blockers == []
    assert set(plan.summary["files"]) == {
        "templates.yaml",
        "automations.yaml",
        "scripts.yaml",
        "ui_lovelace_minimalist.yaml",
    }
    assert _hashes(config_dir) == originals

    applied = await api.apply(hass, plan.plan_id)
    assert applied.status == "completed"
    assert (await api.audit(hass)).dead == {}
    assert NEW_ID in (config_dir / "scripts.yaml").read_text()
    assert OLD_ID not in (config_dir / "ui_lovelace_minimalist.yaml").read_text()

    await api.undo(hass, applied.apply_id)
    assert _hashes(config_dir) == originals
