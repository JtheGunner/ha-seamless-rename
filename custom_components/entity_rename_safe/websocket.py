"""Websocket commands for the panel: thin admin-only wrappers over ``ha/api.py``."""

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

import probatio as vol
from homeassistant.components.websocket_api import async_register_command
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.components.websocket_api.decorators import (
    async_response,
    require_admin,
    websocket_command,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .ha import api

ERR_REJECTED = "rename_rejected"
ERR_INVALID = "invalid_request"

Handler = Callable[[HomeAssistant, ActiveConnection, dict[str, Any]], Awaitable[None]]


def _guarded(handler: Handler) -> Handler:
    """Report ``RenameError`` and ``ValueError`` to the client instead of crashing the command."""

    @wraps(handler)
    async def wrapper(
        hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
    ) -> None:
        try:
            await handler(hass, connection, msg)
        except api.RenameError as error:
            connection.send_error(msg["id"], ERR_REJECTED, str(error))
        except ValueError as error:
            connection.send_error(msg["id"], ERR_INVALID, str(error))

    return wrapper


@websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/plan",
        vol.Optional("from"): cv.entity_id,
        vol.Optional("to"): cv.entity_id,
        vol.Optional("pattern"): vol.Schema(
            {
                vol.Required("match"): cv.string,
                vol.Required("replace"): cv.string,
                vol.Optional("domain"): cv.string,
            }
        ),
    }
)
@require_admin
@async_response
@_guarded
async def ws_plan(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    request = api.build_plan_request(msg.get("from"), msg.get("to"), msg.get("pattern"))
    result = await api.plan(hass, request)
    connection.send_result(msg["id"], {**result.to_response(), "diff": result.diff})


@websocket_command({vol.Required("type"): f"{DOMAIN}/apply", "plan_id": cv.string})
@require_admin
@async_response
@_guarded
async def ws_apply(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    result = await api.apply(hass, msg["plan_id"])
    connection.send_result(msg["id"], result.to_response())


@websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/undo",
        vol.Required("apply_id"): cv.string,
        vol.Optional("force", default=False): cv.boolean,
    }
)
@require_admin
@async_response
@_guarded
async def ws_undo(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    result = await api.undo(hass, msg["apply_id"], force=msg["force"])
    connection.send_result(msg["id"], result.to_response())


@websocket_command({vol.Required("type"): f"{DOMAIN}/history"})
@require_admin
@async_response
@_guarded
async def ws_history(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    connection.send_result(
        msg["id"], {"history": [item.to_response() for item in await api.history(hass)]}
    )


@websocket_command({vol.Required("type"): f"{DOMAIN}/audit"})
@require_admin
@async_response
@_guarded
async def ws_audit(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    connection.send_result(msg["id"], (await api.audit(hass)).to_response())


@websocket_command(
    {vol.Required("type"): f"{DOMAIN}/references", vol.Required("entity_id"): cv.entity_id}
)
@require_admin
@async_response
@_guarded
async def ws_references(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    findings = await api.references(hass, msg["entity_id"])
    connection.send_result(msg["id"], {"references": api.findings_response(findings)})


def async_register_websocket(hass: HomeAssistant) -> None:
    """Register all websocket commands."""
    for command in (ws_plan, ws_apply, ws_undo, ws_history, ws_audit, ws_references):
        async_register_command(hass, command)
