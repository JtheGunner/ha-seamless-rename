import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

from homeassistant.components.http import HomeAssistantHTTP
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.seamless_rename import panel
from custom_components.seamless_rename.const import CONF_SHOW_PANEL, DOMAIN
from custom_components.seamless_rename.panel import PANEL_FILE, PANEL_URL_PATH, content_hash

REGISTER = "custom_components.seamless_rename.panel.panel_custom.async_register_panel"
VERSIONED_URL = re.compile(r"^/seamless_rename_static/[0-9a-f]{12}/(?P<file>[\w.-]+\.js)$")


async def _setup_entry(hass: HomeAssistant, options: dict | None = None) -> bool:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, options=options or {})
    entry.add_to_hass(hass)
    return await hass.config_entries.async_setup(entry.entry_id)


async def test_panel_is_registered_admin_only(hass: HomeAssistant) -> None:
    hass.config.components.add("frontend")
    with patch(REGISTER, new=AsyncMock()) as register:
        assert await _setup_entry(hass)
    register.assert_awaited_once()
    kwargs = register.await_args.kwargs
    assert kwargs["require_admin"] is True
    assert kwargs["webcomponent_name"] == "seamless-rename-panel"
    match = VERSIONED_URL.match(kwargs["module_url"])
    assert match and match["file"] == "seamless-rename-panel.js"
    assert PANEL_FILE.is_file()


async def test_every_panel_script_is_served_under_the_same_version(hass: HomeAssistant) -> None:
    """The panel imports ``./i18n.js``, so it must sit in the versioned folder of the panel."""
    hass.config.components.add("frontend")
    served: list[str] = []

    async def register_static_paths(self: HomeAssistantHTTP, configs: list) -> None:
        served.extend(config.url_path for config in configs)

    with (
        patch.object(HomeAssistantHTTP, "async_register_static_paths", new=register_static_paths),
        patch(REGISTER, new=AsyncMock()) as register,
    ):
        assert await _setup_entry(hass)
    scripts = {file.name for file in PANEL_FILE.parent.glob("*.js")}
    assert {VERSIONED_URL.match(url)["file"] for url in served} == scripts
    assert "i18n.js" in scripts
    folders = {url.rsplit("/", 1)[0] for url in served}
    assert folders == {register.await_args.kwargs["module_url"].rsplit("/", 1)[0]}


async def test_panel_scripts_are_read_outside_the_event_loop(hass: HomeAssistant) -> None:
    hass.config.components.add("frontend")
    with (
        patch.object(hass, "async_add_executor_job", wraps=hass.async_add_executor_job) as spy,
        patch(REGISTER, new=AsyncMock()),
    ):
        assert await _setup_entry(hass)
    assert any(call.args[0] is panel.scan_scripts for call in spy.call_args_list)


def test_version_changes_with_the_content_of_a_script(tmp_path: Path) -> None:
    script = tmp_path / "panel.js"
    script.write_text("one")
    before = content_hash([script])
    assert content_hash([script]) == before
    script.write_text("two")
    assert content_hash([script]) != before


def test_version_changes_when_a_script_is_added(tmp_path: Path) -> None:
    first = tmp_path / "panel.js"
    first.write_text("one")
    second = tmp_path / "i18n.js"
    second.write_text("one")
    assert content_hash([first]) != content_hash([first, second])


async def test_panel_is_skipped_without_frontend(hass: HomeAssistant) -> None:
    with patch(REGISTER, new=AsyncMock()) as register:
        assert await _setup_entry(hass)
    register.assert_not_awaited()


async def test_panel_is_hidden_when_the_option_is_off(hass: HomeAssistant) -> None:
    hass.config.components.add("frontend")
    with patch(REGISTER, new=AsyncMock()) as register:
        assert await _setup_entry(hass, {CONF_SHOW_PANEL: False})
    register.assert_not_awaited()


async def test_panel_is_removed_on_unload(hass: HomeAssistant) -> None:
    hass.config.components.add("frontend")
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    hass.data[panel.DATA_PANELS] = {PANEL_URL_PATH: object()}
    with (
        patch(REGISTER, new=AsyncMock()),
        patch("custom_components.seamless_rename.panel.frontend.async_remove_panel") as remove,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        assert await hass.config_entries.async_unload(entry.entry_id)
    remove.assert_called_once_with(hass, PANEL_URL_PATH)


async def test_toggling_the_option_reloads_and_shows_or_hides_the_panel(
    hass: HomeAssistant,
) -> None:
    hass.config.components.add("frontend")
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, options={CONF_SHOW_PANEL: False})
    entry.add_to_hass(hass)
    with (
        patch(REGISTER, new=AsyncMock()) as register,
        patch("custom_components.seamless_rename.panel.frontend.async_remove_panel") as remove,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        register.assert_not_awaited()

        hass.config_entries.async_update_entry(entry, options={CONF_SHOW_PANEL: True})
        await hass.async_block_till_done()
        register.assert_awaited_once()

        hass.data[panel.DATA_PANELS] = {PANEL_URL_PATH: object()}
        hass.config_entries.async_update_entry(entry, options={CONF_SHOW_PANEL: False})
        await hass.async_block_till_done()
        remove.assert_called_once_with(hass, PANEL_URL_PATH)
        assert register.await_count == 1


async def test_options_flow_stores_the_panel_choice_and_defaults_to_shown(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema_keys = {str(key): key for key in result["data_schema"].schema}
    assert schema_keys[CONF_SHOW_PANEL].default() is True

    created = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SHOW_PANEL: False}
    )
    assert created["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SHOW_PANEL] is False
