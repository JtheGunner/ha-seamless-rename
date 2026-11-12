"""plan -> apply -> audit -> undo against a real Home Assistant container."""

import hashlib
from pathlib import Path

from .harness import HaClient

OLD_ID = "sensor.snap_kitchen_volume"
NEW_ID = "sensor.room_kitchen_volume"
YAML_FILES = (
    "configuration.yaml",
    "templates.yaml",
    "automations.yaml",
    "scripts.yaml",
    "ui_lovelace_minimalist.yaml",
)


def _hashes(config_dir: Path) -> dict[str, str]:
    return {
        name: hashlib.sha256((config_dir / name).read_bytes()).hexdigest() for name in YAML_FILES
    }


def test_plan_apply_audit_undo_roundtrip(ha: HaClient, e2e_config_dir: Path) -> None:
    originals = _hashes(e2e_config_dir)
    ha.wait_for_state(OLD_ID, present=True)

    plan = ha.call_service("seamless_rename", "plan", {"from": OLD_ID, "to": NEW_ID})
    assert plan["blockers"] == []
    assert set(plan["summary"]["files"]) >= {
        "templates.yaml",
        "automations.yaml",
        "scripts.yaml",
        "ui_lovelace_minimalist.yaml",
    }
    assert _hashes(e2e_config_dir) == originals  # a plan never writes

    applied = ha.call_service("seamless_rename", "apply", {"plan_id": plan["plan_id"]})
    assert applied["status"] == "completed"
    ha.wait_for_state(NEW_ID, present=True)
    ha.wait_for_state(OLD_ID, present=False)
    for name in (
        "templates.yaml",
        "automations.yaml",
        "scripts.yaml",
        "ui_lovelace_minimalist.yaml",
    ):
        text = (e2e_config_dir / name).read_text()
        assert OLD_ID not in text, name
        assert NEW_ID in text, name

    audit = ha.call_service("seamless_rename", "audit", {})
    assert audit["dead"] == {}

    undone = ha.call_service("seamless_rename", "undo", {"apply_id": applied["apply_id"]})
    assert undone["status"] == "undone"
    assert _hashes(e2e_config_dir) == originals
    ha.wait_for_state(OLD_ID, present=True)
