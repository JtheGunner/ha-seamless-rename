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
from homeassistant.helpers.selector import BooleanSelector, TextSelector, TextSelectorConfig

from .const import CONF_EXTERNAL_PATHS, CONF_SHOW_PANEL, DOMAIN, WORK_DIR_NAME


class SeamlessRenameConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create the single config entry."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SeamlessRenameOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="Seamless Rename", data={})


class SeamlessRenameOptionsFlow(OptionsFlow):
    """Folders outside the configuration that are searched and reported, never edited."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            paths = [
                path.strip() for path in user_input.get(CONF_EXTERNAL_PATHS, []) if path.strip()
            ]
            if not all(Path(path).is_absolute() for path in paths):
                errors["base"] = "invalid_path"
            else:
                errors.update(await self._check_folders(paths))
            if not errors:
                return self.async_create_entry(
                    data={
                        CONF_EXTERNAL_PATHS: paths,
                        CONF_SHOW_PANEL: user_input.get(CONF_SHOW_PANEL, True),
                    }
                )
        current = list(self.config_entry.options.get(CONF_EXTERNAL_PATHS, []))
        schema = vol.Schema(
            {
                vol.Optional(CONF_EXTERNAL_PATHS, default=current): TextSelector(
                    TextSelectorConfig(multiple=True)
                ),
                vol.Optional(
                    CONF_SHOW_PANEL, default=self.config_entry.options.get(CONF_SHOW_PANEL, True)
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)

    async def _check_folders(self, paths: list[str]) -> dict[str, str]:
        """Return an error if a path is no folder or lies in a protected part of the config."""
        config_dir = Path(self.hass.config.config_dir)
        protected = (config_dir / ".storage", config_dir / WORK_DIR_NAME)

        def check() -> dict[str, str]:
            for path in paths:
                real = Path(path).resolve()
                if not real.is_dir():
                    return {"base": "not_a_directory"}
                if any(real.is_relative_to(guard.resolve()) for guard in protected):
                    return {"base": "protected_path"}
            return {}

        return await self.hass.async_add_executor_job(check)
