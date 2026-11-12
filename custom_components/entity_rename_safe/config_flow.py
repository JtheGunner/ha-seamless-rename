"""Config flow: a single instance, plus an options step for external search folders."""

from pathlib import Path
from typing import Any

import probatio as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig

from .const import CONF_EXTERNAL_PATHS, DOMAIN


class EntityRenameSafeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create the single config entry."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return EntityRenameSafeOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="Entity Rename Safe", data={})


class EntityRenameSafeOptionsFlow(OptionsFlow):
    """Folders outside the configuration that are searched and reported, never edited."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            paths = [
                path.strip() for path in user_input.get(CONF_EXTERNAL_PATHS, []) if path.strip()
            ]
            if all(Path(path).is_absolute() for path in paths):
                return self.async_create_entry(data={CONF_EXTERNAL_PATHS: paths})
            errors["base"] = "invalid_path"
        current = list(self.config_entry.options.get(CONF_EXTERNAL_PATHS, []))
        schema = vol.Schema(
            {
                vol.Optional(CONF_EXTERNAL_PATHS, default=current): TextSelector(
                    TextSelectorConfig(multiple=True)
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
