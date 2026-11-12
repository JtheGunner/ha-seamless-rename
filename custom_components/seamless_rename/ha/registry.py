"""Entity registry access: the only place that renames an entity ID."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


def registry_entity_ids(hass: HomeAssistant) -> set[str]:
    """Return every entity ID that has a registry entry."""
    return set(er.async_get(hass).entities)


def state_entity_ids(hass: HomeAssistant) -> set[str]:
    """Return every entity ID that currently has a state."""
    return set(hass.states.async_entity_ids())


def rename_entity(hass: HomeAssistant, from_id: str, to_id: str) -> None:
    """Rename one registry entry; Home Assistant moves its state and history link."""
    er.async_get(hass).async_update_entity(from_id, new_entity_id=to_id)


def registry_uuids(hass: HomeAssistant, entity_ids: list[str]) -> dict[str, str]:
    """Map each entity ID that has a registry entry to that entry's stable UUID."""
    registry = er.async_get(hass)
    return {
        entity_id: entry.id
        for entity_id in entity_ids
        if (entry := registry.async_get(entity_id)) is not None
    }


def current_entity_id(hass: HomeAssistant, registry_uuid: str) -> str | None:
    """Return the entity ID the registry entry with this UUID has right now."""
    entry = er.async_get(hass).async_get(registry_uuid)
    return entry.entity_id if entry is not None else None
