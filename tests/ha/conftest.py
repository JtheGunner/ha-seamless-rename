"""Fixtures for the Home Assistant layer tests."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.check_config import HomeAssistantConfig

CHECK_PATH = "custom_components.entity_rename_safe.ha.api.async_check_ha_config_file"


@pytest.fixture
def config_dir(hass: HomeAssistant, tmp_path: Path) -> Path:
    """Point Home Assistant at a throw-away config directory."""
    directory = tmp_path / "config"
    directory.mkdir()
    hass.config.config_dir = str(directory)
    return directory


@pytest.fixture
def check_ok() -> Iterator[None]:
    """Make the configuration check pass."""
    with patch(CHECK_PATH, return_value=HomeAssistantConfig()):
        yield


def add_entity(hass: HomeAssistant, entity_id: str, state: str = "on") -> None:
    """Create a registry entry and a state for ``entity_id``."""
    domain, object_id = entity_id.split(".")
    er.async_get(hass).async_get_or_create(
        domain, "test", f"uid-{entity_id}", suggested_object_id=object_id
    )
    hass.states.async_set(entity_id, state)


@pytest.fixture(autouse=True)
def move_state_on_rename(hass: HomeAssistant) -> None:
    """Mimic a real entity: its state follows the entity ID after a registry rename."""

    @callback
    def _move(event: Event) -> None:
        old = event.data.get("old_entity_id")
        if event.data.get("action") != "update" or not old:
            return
        state = hass.states.get(old)
        if state is None:
            return
        hass.states.async_remove(old)
        hass.states.async_set(event.data["entity_id"], state.state)

    hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, _move)
