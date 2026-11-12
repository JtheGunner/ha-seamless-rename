"""Rename Home Assistant entity IDs and update all consumers safely."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration; services are registered by later tickets."""
    hass.data.setdefault(DOMAIN, {})
    return True
