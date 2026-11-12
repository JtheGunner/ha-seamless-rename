from unittest.mock import AsyncMock, patch

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


async def test_panel_is_skipped_without_frontend(hass: HomeAssistant) -> None:
    with patch(REGISTER, new=AsyncMock()) as register:
        assert await async_setup_component(hass, DOMAIN, {})
    register.assert_not_awaited()
