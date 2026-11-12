"""Entity ID validation and the shared token pattern used by every scanner."""

import re
from collections.abc import Iterable

# Mirrors Home Assistant's valid_entity_id without importing it (engine stays HA-free).
_ENTITY_ID_RE = re.compile(r"^(?!.+__)(?!_)[\da-z_]+(?<!_)\.(?!_)[\da-z_]+(?<!_)$")

_NEVER_MATCHES = re.compile(r"(?!)")


def is_valid_entity_id(value: str) -> bool:
    """Return True if ``value`` is a syntactically valid entity ID."""
    return _ENTITY_ID_RE.match(value) is not None


def object_id(entity_id: str) -> str:
    """Return the part of an entity ID after the domain."""
    return entity_id.split(".", 1)[1]


def build_token_pattern(old_ids: Iterable[str]) -> re.Pattern[str]:
    """Build a pattern that finds exactly the given IDs, never a longer ID.

    - No word character directly before or after the ID.
    - A preceding dot is only allowed for dotted access (``states.<id>``).
    - Longest IDs are tried first so ``sensor.foo_bar`` wins over ``sensor.foo``.
    The matched ID is available as the named group ``id``.
    """
    ordered = sorted(set(old_ids), key=len, reverse=True)
    if not ordered:
        return _NEVER_MATCHES
    alternation = "|".join(re.escape(entity_id) for entity_id in ordered)
    return re.compile(
        rf"(?:(?<![\w.])states\.|(?<![\w.]))(?P<id>{alternation})(?!\w)",
    )
