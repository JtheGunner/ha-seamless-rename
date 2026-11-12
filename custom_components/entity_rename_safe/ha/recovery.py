"""Detect applies that were interrupted by a crash or restart and offer to undo them."""

import json
import logging
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from ..const import DOMAIN, WORK_DIR_NAME

_LOGGER = logging.getLogger(__name__)
ISSUE_PREFIX = "incomplete_apply_"


def _in_progress_apply_ids(work_dir: Path) -> list[str]:
    """Return the IDs of all backups whose manifest still says ``in_progress``."""
    found: list[str] = []
    for manifest_path in sorted((work_dir / "backups").glob("*/manifest.json")):
        try:
            data = json.loads(manifest_path.read_text())
        except (OSError, ValueError) as error:
            _LOGGER.warning(
                "unreadable manifest %s, cannot check it for recovery: %s", manifest_path, error
            )
            continue
        if isinstance(data, dict) and data.get("status") == "in_progress":
            found.append(manifest_path.parent.name)
    return found


async def check_incomplete_applies(hass: HomeAssistant) -> None:
    """Create one fixable repair issue per interrupted apply; clear issues that are resolved."""
    work_dir = Path(hass.config.config_dir) / WORK_DIR_NAME
    interrupted = await hass.async_add_executor_job(_in_progress_apply_ids, work_dir)
    registry = ir.async_get(hass)
    wanted = {f"{ISSUE_PREFIX}{apply_id}" for apply_id in interrupted}
    for (domain, issue_id), _ in list(registry.issues.items()):
        if domain == DOMAIN and issue_id.startswith(ISSUE_PREFIX) and issue_id not in wanted:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
    for apply_id in interrupted:
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"{ISSUE_PREFIX}{apply_id}",
            is_fixable=True,
            severity=ir.IssueSeverity.ERROR,
            translation_key="incomplete_apply",
            translation_placeholders={"apply_id": apply_id},
            data={"apply_id": apply_id},
        )
