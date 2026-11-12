"""Service handlers: thin wrappers that validate input and call ``ha/api.py``."""

from typing import Any

import probatio as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service

from .const import DOMAIN
from .ha import api

SERVICE_PLAN = "plan"
SERVICE_APPLY = "apply"
SERVICE_UNDO = "undo"
SERVICE_AUDIT = "audit"
SERVICE_REFERENCES = "references"

PLAN_SCHEMA = vol.Schema(
    vol.All(
        {
            vol.Optional("from"): cv.entity_id,
            vol.Optional("to"): cv.entity_id,
            vol.Optional("include_uncertain", default=False): cv.boolean,
            vol.Optional("pattern"): vol.Schema(
                {
                    vol.Required("match"): cv.string,
                    vol.Required("replace"): cv.string,
                    vol.Optional("domain"): cv.string,
                }
            ),
        },
        cv.has_at_least_one_key("from", "pattern"),
    )
)
APPLY_SCHEMA = vol.Schema(
    {vol.Required("plan_id"): cv.string, vol.Optional("exclude", default=list): [cv.string]}
)
UNDO_SCHEMA = vol.Schema(
    {vol.Required("apply_id"): cv.string, vol.Optional("force", default=False): cv.boolean}
)


AUDIT_SCHEMA = vol.Schema({})
REFERENCES_SCHEMA = vol.Schema({vol.Required("entity_id"): cv.entity_id})


def _wrap(error: api.RenameError) -> HomeAssistantError:
    return ServiceValidationError(str(error))


async def _plan(call: ServiceCall) -> dict[str, Any]:
    data = call.data
    try:
        request = api.build_plan_request(
            data.get("from"), data.get("to"), data.get("pattern"), data["include_uncertain"]
        )
        result = await api.plan(call.hass, request)
    except ValueError as error:
        raise ServiceValidationError(str(error)) from error
    return result.to_response()


async def _apply(call: ServiceCall) -> dict[str, Any]:
    try:
        result = await api.apply(call.hass, call.data["plan_id"], call.data["exclude"])
    except api.RenameError as error:
        raise _wrap(error) from error
    return result.to_response()


async def _undo(call: ServiceCall) -> dict[str, Any]:
    try:
        result = await api.undo(call.hass, call.data["apply_id"], force=call.data["force"])
    except api.RenameError as error:
        raise _wrap(error) from error
    return result.to_response()


async def _audit(call: ServiceCall) -> dict[str, Any]:
    return (await api.audit(call.hass)).to_response()


async def _references(call: ServiceCall) -> dict[str, Any]:
    try:
        findings = await api.references(call.hass, call.data["entity_id"])
    except ValueError as error:
        raise ServiceValidationError(str(error)) from error
    return {"references": api.findings_response(findings)}


def async_register_services(hass: HomeAssistant) -> None:
    """Register the admin-only services."""
    for name, handler, schema in (
        (SERVICE_PLAN, _plan, PLAN_SCHEMA),
        (SERVICE_APPLY, _apply, APPLY_SCHEMA),
        (SERVICE_UNDO, _undo, UNDO_SCHEMA),
        (SERVICE_AUDIT, _audit, AUDIT_SCHEMA),
        (SERVICE_REFERENCES, _references, REFERENCES_SCHEMA),
    ):
        async_register_admin_service(
            hass, DOMAIN, name, handler, schema, supports_response=SupportsResponse.ONLY
        )
