"""Register the admin-only sidebar panel. The panel itself is a plain web component."""

import hashlib
import logging
from collections.abc import Sequence
from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.components.http.server import StaticPathConfig
from homeassistant.core import HomeAssistant

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PANEL_URL_PATH = "seamless-rename"
WEBCOMPONENT_NAME = "seamless-rename-panel"
STATIC_URL = f"/{DOMAIN}_static"
PANEL_FILE = Path(__file__).parent / "seamless-rename-panel.js"
VERSION_LENGTH = 12


def content_hash(scripts: Sequence[Path]) -> str:
    """Return a short hash over the names and contents of the panel scripts."""
    digest = hashlib.sha256()
    for script in scripts:
        digest.update(script.name.encode())
        digest.update(script.read_bytes())
    return digest.hexdigest()[:VERSION_LENGTH]


def scan_scripts() -> tuple[list[Path], str]:
    """List the panel scripts and their version. Blocking: run it in the executor."""
    scripts = sorted(PANEL_FILE.parent.glob("*.js"))
    return scripts, content_hash(scripts)


async def async_register_panel(hass: HomeAssistant) -> None:
    """Serve the panel scripts and add the panel for administrators.

    The scripts are served below a folder named after their content hash. The panel imports its
    sibling scripts (``./i18n.js``), so a changed script gets a new URL for all of them and the
    browser never keeps an old copy. Skipped when the frontend is not loaded (headless installs),
    so setup never fails on it.
    """
    if "frontend" not in hass.config.components or hass.http is None:
        _LOGGER.debug("frontend not loaded, panel not registered")
        return
    scripts, version = await hass.async_add_executor_job(scan_scripts)
    base_url = f"{STATIC_URL}/{version}"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(f"{base_url}/{script.name}", str(script)) for script in scripts]
    )
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=WEBCOMPONENT_NAME,
        module_url=f"{base_url}/{PANEL_FILE.name}",
        sidebar_title="Seamless Rename",
        sidebar_icon="mdi:form-textbox",
        require_admin=True,
    )
