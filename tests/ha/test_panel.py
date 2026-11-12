from unittest.mock import AsyncMock, patch

from homeassistant.components.http import HomeAssistantHTTP
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.seamless_rename.const import DOMAIN
from custom_components.seamless_rename.panel import PANEL_FILE

REGISTER = "custom_components.seamless_rename.panel.panel_custom.async_register_panel"


async def test_panel_is_registered_admin_only(hass: HomeAssistant) -> None:
    hass.config.components.add("frontend")
    with patch(REGISTER, new=AsyncMock()) as register:
        assert await async_setup_component(hass, DOMAIN, {})
    register.assert_awaited_once()
    kwargs = register.await_args.kwargs
    assert kwargs["require_admin"] is True
    assert kwargs["webcomponent_name"] == "seamless-rename-panel"
    assert kwargs["module_url"].endswith("seamless-rename-panel.js")
    assert PANEL_FILE.is_file()


async def test_every_panel_script_is_served(hass: HomeAssistant) -> None:
    """The panel imports ``./i18n.js``, so every script next to it must be served."""
    hass.config.components.add("frontend")
    served: list[str] = []

    async def register_static_paths(self: HomeAssistantHTTP, configs: list) -> None:
        served.extend(config.url_path for config in configs)

    with (
        patch.object(HomeAssistantHTTP, "async_register_static_paths", new=register_static_paths),
        patch(REGISTER, new=AsyncMock()),
    ):
        assert await async_setup_component(hass, DOMAIN, {})
    scripts = {file.name for file in PANEL_FILE.parent.glob("*.js")}
    assert {url.rsplit("/", 1)[1] for url in served} == scripts
    assert "i18n.js" in scripts


async def test_panel_is_skipped_without_frontend(hass: HomeAssistant) -> None:
    with patch(REGISTER, new=AsyncMock()) as register:
        assert await async_setup_component(hass, DOMAIN, {})
    register.assert_not_awaited()
