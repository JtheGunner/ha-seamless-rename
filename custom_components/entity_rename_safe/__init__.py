"""Rename Home Assistant entity IDs and update all consumers safely."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .ha.recovery import check_incomplete_applies
from .panel import async_register_panel
from .services import async_register_services
from .websocket import async_register_websocket


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration and register its services."""
    hass.data.setdefault(DOMAIN, {})
    async_register_services(hass)
    async_register_websocket(hass)
    await async_register_panel(hass)
    await check_incomplete_applies(hass)
    return True
