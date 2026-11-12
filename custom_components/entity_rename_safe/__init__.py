"""Rename Home Assistant entity IDs and update all consumers safely."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .ha.recovery import check_incomplete_applies
from .panel import async_register_panel
from .services import async_register_services
from .websocket import async_register_websocket

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration and register its services."""
    hass.data.setdefault(DOMAIN, {})
    async_register_services(hass)
    async_register_websocket(hass)
    await async_register_panel(hass)
    await check_incomplete_applies(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Accept the config entry; services, websocket and panel are registered in ``async_setup``."""
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the config entry; integration-wide registrations stay until HA stops."""
    return True
