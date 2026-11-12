"""Rename Home Assistant entity IDs and update all consumers safely."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import CONF_SHOW_PANEL, DATA_PANEL_URL, DOMAIN
from .ha.recovery import check_incomplete_applies
from .panel import async_hide_panel, async_register_scripts, async_show_panel
from .services import async_register_services
from .websocket import async_register_websocket

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration and register its services."""
    hass.data.setdefault(DOMAIN, {})
    async_register_services(hass)
    async_register_websocket(hass)
    hass.data[DOMAIN][DATA_PANEL_URL] = await async_register_scripts(hass)
    await check_incomplete_applies(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Show the sidebar panel unless the options hide it; reload when the options change."""
    module_url = hass.data[DOMAIN].get(DATA_PANEL_URL)
    if module_url and entry.options.get(CONF_SHOW_PANEL, True):
        await async_show_panel(hass, module_url)
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_options_change))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Remove the sidebar panel; services and websocket stay until HA stops."""
    async_hide_panel(hass)
    return True


async def _async_reload_on_options_change(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
