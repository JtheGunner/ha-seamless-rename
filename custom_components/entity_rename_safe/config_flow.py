"""Config flow: a single instance without user input."""

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class EntityRenameSafeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create the single config entry."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="Entity Rename Safe", data={})
