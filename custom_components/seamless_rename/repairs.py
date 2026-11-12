"""Repair flow that rolls back an interrupted apply."""

import logging
from typing import Any

import probatio as vol
from homeassistant.components.repairs import RepairsFlow, RepairsFlowResult
from homeassistant.core import HomeAssistant

from .ha import api
from .ha.recovery import ISSUE_PREFIX

_LOGGER = logging.getLogger(__name__)


class IncompleteApplyRepairFlow(RepairsFlow):
    """Ask for confirmation, then restore the state from before the interrupted apply."""

    def __init__(self, apply_id: str) -> None:
        self._apply_id = apply_id

    async def async_step_init(self, user_input: dict[str, str] | None = None) -> RepairsFlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                description_placeholders={"apply_id": self._apply_id},
            )
        try:
            await api.undo(self.hass, self._apply_id)
        except Exception as error:
            if not isinstance(error, api.RenameError):
                _LOGGER.exception("rolling back interrupted apply %s failed", self._apply_id)
            return self.async_abort(
                reason="undo_failed", description_placeholders={"error": str(error)}
            )
        return self.async_create_entry(data={})


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None
) -> RepairsFlow:
    """Create the fix flow for an ``incomplete_apply_*`` issue."""
    apply_id = (data or {}).get("apply_id") or issue_id.removeprefix(ISSUE_PREFIX)
    return IncompleteApplyRepairFlow(str(apply_id))
