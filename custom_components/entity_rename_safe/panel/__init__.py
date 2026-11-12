"""Register the admin-only sidebar panel. The panel itself is a plain web component."""

import logging
from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.components.http.server import StaticPathConfig
from homeassistant.core import HomeAssistant

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PANEL_URL_PATH = "entity-rename-safe"
WEBCOMPONENT_NAME = "entity-rename-safe-panel"
STATIC_URL = f"/{DOMAIN}_static"
PANEL_FILE = Path(__file__).parent / "entity-rename-safe-panel.js"


async def async_register_panel(hass: HomeAssistant) -> None:
    """Serve the panel script and add the panel for administrators.

    Skipped when the frontend is not loaded (headless installs), so setup never fails on it.
    """
    if "frontend" not in hass.config.components or hass.http is None:
        _LOGGER.debug("frontend not loaded, panel not registered")
        return
    module_url = f"{STATIC_URL}/{PANEL_FILE.name}"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(module_url, str(PANEL_FILE), cache_headers=False)]
    )
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=WEBCOMPONENT_NAME,
        module_url=module_url,
        sidebar_title="Seamless Rename",
        sidebar_icon="mdi:form-textbox",
        require_admin=True,
    )
