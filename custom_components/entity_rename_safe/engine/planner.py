"""Plan renames: resolve bulk patterns, order them safely, check blockers, render diffs."""

import difflib
import re
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field

from .ids import is_valid_entity_id
from .models import Rename

TEMP_ID_PREFIX = "rename_safe_tmp_"


@dataclass(frozen=True)
class Preflight:
    """Result of the pre-apply checks. A plan with blockers must not be applied."""

    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _domain(entity_id: str) -> str:
    return entity_id.split(".", 1)[0]


def resolve_pattern(
    registry_ids: Collection[str], match: str, replace: str, domain: str | None
) -> list[Rename]:
    """Turn a regex rename rule into the concrete list of renames it causes.

    The pattern is applied to the full entity ID (``re.sub`` semantics). IDs that stay
    unchanged are skipped. A rule that changes the domain is not rejected here; the
    preflight reports it as a blocker.
    """
    try:
        regex = re.compile(match)
        renames = []
        for entity_id in sorted(registry_ids):
            if domain is not None and _domain(entity_id) != domain:
                continue
            new_id = regex.sub(replace, entity_id)
            if new_id != entity_id:
                renames.append(Rename(entity_id, new_id))
    except re.error as error:
        raise ValueError(f"invalid rename pattern: {error}") from error
    return renames


def order_renames(renames: Sequence[Rename]) -> list[Rename]:
    """Order renames so that every target is free when its rename runs.

    A rename is ready once its target is no longer the source of a pending rename, so
    chains (a->b, b->c) run back to front. A pure cycle (a<->b) is broken by moving one
    entity to a temporary ID first. The returned list may therefore be longer than the
    input and contains one extra entry per broken cycle: ``a->tmp`` now and ``tmp->b``
    later. Text replacement always uses the original renames, never the temporary ones.
    """
    pending = list(renames)
    ordered: list[Rename] = []
    temp_counter = 0
    while pending:
        sources = {rename.from_id for rename in pending}
        ready = [rename for rename in pending if rename.to_id not in sources]
        if ready:
            ordered.extend(ready)
            pending = [rename for rename in pending if rename not in ready]
            continue
        first = pending[0]
        temp_counter += 1
        temp_id = f"{_domain(first.from_id)}.{TEMP_ID_PREFIX}{temp_counter}"
        ordered.append(Rename(first.from_id, temp_id))
        pending[0] = Rename(temp_id, first.to_id)
    return ordered


def run_preflight(
    renames: Sequence[Rename], registry_ids: Collection[str], state_ids: Collection[str]
) -> Preflight:
    """Check the renames against the registry and the state machine."""
    blockers: list[str] = []
    warnings: list[str] = []
    sources = Counter(rename.from_id for rename in renames)
    targets = Counter(rename.to_id for rename in renames)

    for rename in renames:
        old, new = rename.from_id, rename.to_id
        if old == new:
            blockers.append(f"{old}: the new ID is identical to the old ID")
            continue
        if not is_valid_entity_id(new):
            blockers.append(f"{old}: '{new}' is not a valid entity ID")
            continue
        if _domain(old) != _domain(new):
            blockers.append(f"{old}: the domain cannot change ('{new}')")
        if old not in registry_ids:
            blockers.append(
                f"{old}: not in the entity registry (a YAML entity without unique_id "
                "cannot be renamed automatically)"
            )
        elif old not in state_ids:
            warnings.append(f"{old}: has no state (disabled or unavailable)")
        if new not in sources and (new in registry_ids or new in state_ids):
            blockers.append(f"{old}: the target '{new}' already exists")
        if sources[old] > 1:
            blockers.append(f"{old}: renamed more than once in the same plan")
        if targets[new] > 1:
            blockers.append(f"{new}: is the target of more than one rename")
    return Preflight(blockers=list(dict.fromkeys(blockers)), warnings=warnings)


def render_diff(path: str, old: str, new: str) -> str:
    """Return a unified diff of one file, or an empty string if nothing changed."""
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )
