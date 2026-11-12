from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component

from custom_components.entity_rename_safe.const import DEFAULT_EXCLUDES, DOMAIN, WORK_DIR_NAME


def test_domain_constants() -> None:
    assert DOMAIN == "entity_rename_safe"
    assert WORK_DIR_NAME == ".entity_rename_safe"
    for excluded in (".storage", ".git", "custom_components", "secrets.yaml"):
        assert excluded in DEFAULT_EXCLUDES


async def test_integration_setup_loads(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})


async def test_config_flow_creates_single_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.CREATE_ENTRY

    second = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert second["type"] is FlowResultType.ABORT
