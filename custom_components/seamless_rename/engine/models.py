"""Data models shared by the rename engine."""

from dataclasses import dataclass
from enum import StrEnum


class Confidence(StrEnum):
    """How sure the scanner is that a hit is an entity reference."""

    CERTAIN = "certain"
    LIKELY = "likely"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class Rename:
    """One entity ID rename."""

    from_id: str
    to_id: str


@dataclass(frozen=True)
class Finding:
    """One reference to an old entity ID, with where it is and how to replace it.

    Text files carry ``offset`` and ``length`` (absolute span in the source text).
    Tree-shaped sources (dashboards, helper options) carry ``json_path`` instead.
    """

    finding_id: str
    location: str
    line: int
    old: str
    new: str
    confidence: Confidence
    offset: int | None = None
    length: int | None = None
    json_path: str | None = None
