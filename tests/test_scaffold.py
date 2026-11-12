from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.seamless_rename.const import DEFAULT_EXCLUDES, DOMAIN, WORK_DIR_NAME


def test_domain_constants() -> None:
    assert DOMAIN == "seamless_rename"
    assert WORK_DIR_NAME == ".seamless_rename"
    for excluded in (".storage", ".git", "custom_components", "secrets.yaml"):
        assert excluded in DEFAULT_EXCLUDES


async def test_integration_setup_loads(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})


async def test_config_flow_creates_single_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.CREATE_ENTRY

    second = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert second["type"] is FlowResultType.ABORT


async def test_config_entry_sets_up_and_unloads(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN)
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
