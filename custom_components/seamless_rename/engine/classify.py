"""Confidence rules shared by the YAML and JSON scanners (spec section 4.4)."""

import re

from .models import Confidence

_JINJA_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)


def inside_jinja(
    text: str, start: int, end: int, region_start: int = 0, region_end: int | None = None
) -> bool:
    """True if the span ``start:end`` lies within a Jinja expression or statement.

    ``region_start`` / ``region_end`` restrict the search to one scalar inside a larger text.
    """
    stop = len(text) if region_end is None else region_end
    return any(
        region.start() <= start and end <= region.end()
        for region in _JINJA_RE.finditer(text, region_start, stop)
    )


def _quoted_literal(value: str, old_id: str) -> bool:
    """True if the ID appears as a quoted SQL string literal, as in ``entity_id = 'sensor.x'``."""
    return f"'{old_id}'" in value or f'"{old_id}"' in value


def classify(value: str, old_id: str, key: str | None, jinja: bool) -> Confidence:
    """Classify one hit of ``old_id`` inside the scalar ``value`` stored under ``key``."""
    if value.strip() == old_id:
        return Confidence.CERTAIN
    if key == "entity_id" and old_id in (part.strip() for part in value.split(",")):
        return Confidence.CERTAIN
    if jinja or (key == "query" and _quoted_literal(value, old_id)):
        return Confidence.LIKELY
    return Confidence.UNCERTAIN
