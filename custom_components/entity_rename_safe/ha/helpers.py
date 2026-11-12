"""Config-entry helpers (Min/Max, groups, ...) whose ``options`` hold entity IDs.

Only ``options`` is rewritten, through ``config_entries.async_update_entry``. Hits in
``data`` are reported for manual follow-up. Helpers that store the registry UUID contain no
ID text, so they never show up here. Helpers that follow a rename on their own are handled
by scanning again after the registry rename: whatever is already updated has no hit left.
Every call into Home Assistant is guarded and turns into ``AdapterUnavailable``.
"""

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from ..const import DOMAIN
from ..engine.json_scan import rewrite_json, scan_json
from ..engine.models import Confidence, Finding
from .files import write_atomic
from .lovelace import AdapterUnavailable, config_hash

SNAPSHOT_DIR = "helpers"
_SNAPSHOT_NAME_RE = re.compile(rf"{SNAPSHOT_DIR}/[0-9a-f]{{16}}\.json")


@dataclass(frozen=True)
class HelperPlan:
    """The references found in one config entry."""

    entry_id: str
    domain: str
    title: str
    base_hash: str
    options: dict[str, Any]
    findings: list[Finding] = field(default_factory=list)
    manual: list[Finding] = field(default_factory=list)


def _tree(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a plain, JSON-shaped copy of an options or data mapping."""
    try:
        copy: dict[str, Any] = json.loads(json.dumps(dict(value)))
    except (TypeError, ValueError) as error:
        raise AdapterUnavailable(f"entry options are not JSON-shaped: {error}") from error
    return copy


def _entries(hass: HomeAssistant) -> list[Any]:
    try:
        return [e for e in hass.config_entries.async_entries() if e.domain != DOMAIN]
    except (AttributeError, TypeError) as error:
        raise AdapterUnavailable(f"config entries are not readable: {error!r}") from error


async def scan_entries(hass: HomeAssistant, mapping: Mapping[str, str]) -> list[HelperPlan]:
    """Scan the options of every config entry; hits in ``data`` are marked manual."""
    plans: list[HelperPlan] = []
    for entry in _entries(hass):
        try:
            options = _tree(entry.options)
            data = _tree(entry.data)
            location = f"helper:{entry.domain}:{entry.entry_id}"
            findings = scan_json(options, mapping, location)
            manual = scan_json(data, mapping, f"{location}:data")
            plans_entry = HelperPlan(
                entry_id=entry.entry_id,
                domain=entry.domain,
                title=entry.title,
                base_hash=config_hash(options),
                options=options,
                findings=findings,
                manual=manual,
            )
        except AttributeError as error:
            raise AdapterUnavailable(f"unexpected config entry layout: {error!r}") from error
        if findings or manual:
            plans.append(plans_entry)
    return plans


def current_options(hass: HomeAssistant, entry_id: str) -> tuple[dict[str, Any], str]:
    """Return an entry's options and their hash."""
    try:
        entry = hass.config_entries.async_get_entry(entry_id)
    except AttributeError as error:
        raise AdapterUnavailable(f"config entries are not readable: {error!r}") from error
    if entry is None:
        raise AdapterUnavailable(f"config entry {entry_id} no longer exists")
    options = _tree(entry.options)
    return options, config_hash(options)


def set_options(hass: HomeAssistant, entry_id: str, options: dict[str, Any]) -> None:
    """Replace an entry's options."""
    try:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            raise AdapterUnavailable(f"config entry {entry_id} no longer exists")
        hass.config_entries.async_update_entry(entry, options=options)
    except AdapterUnavailable:
        raise
    except Exception as error:
        raise AdapterUnavailable(f"updating entry {entry_id} failed: {error!r}") from error


async def apply_entry_edits(
    hass: HomeAssistant,
    edits: Sequence[HelperPlan],
    replace: set[Confidence],
    changed: list[tuple[str, dict[str, Any]]] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Rewrite the options of the given entries; return ``(entry_id, options_before)``.

    Each change is also appended to ``changed`` as it happens, so a caller can roll back the
    entries already written if a later one fails.

    Entries whose options no longer change (already following the rename, or already
    rewritten) are skipped.
    """
    changed = [] if changed is None else changed
    for plan in edits:
        if not plan.findings:
            continue
        before, _ = current_options(hass, plan.entry_id)
        after = rewrite_json(before, plan.findings, replace)
        if after == before:
            continue
        set_options(hass, plan.entry_id, after)
        changed.append((plan.entry_id, before))
    return changed


def snapshot_name(entry_id: str) -> str:
    """File name of an entry's snapshot inside the backup folder."""
    return f"{SNAPSHOT_DIR}/{hashlib.sha256(entry_id.encode()).hexdigest()[:16]}.json"


def write_snapshot(
    backup_dir: Path, entry_id: str, domain: str, before: dict[str, Any], after: dict[str, Any]
) -> str:
    """Store an entry's options before and after the apply; return the file name."""
    name = snapshot_name(entry_id)
    payload = {
        "entry_id": entry_id,
        "domain": domain,
        "before": before,
        "sha256_before": config_hash(before),
        "after": after,
        "sha256_after": config_hash(after),
    }
    write_atomic(backup_dir / name, (json.dumps(payload, indent=2) + "\n").encode())
    return name


def read_snapshot(backup_dir: Path, name: str) -> dict[str, Any]:
    """Read a snapshot written by ``write_snapshot``."""
    if not _SNAPSHOT_NAME_RE.fullmatch(name):
        raise ValueError(f"invalid snapshot name: {name!r}")
    try:
        data = json.loads((backup_dir / name).read_text())
        data["entry_id"], data["before"], data["after"], data["sha256_after"]  # noqa: B018
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f"snapshot {name} is unreadable: {error}") from error
    if not isinstance(data, dict):
        raise ValueError(f"snapshot {name} is not an object")
    return data


async def scan_helpers(
    hass: HomeAssistant, mapping: Mapping[str, str]
) -> tuple[list[HelperPlan], list[str]]:
    """Scan for the plan; never raises. Problems and manual hits become warnings."""
    try:
        plans = await scan_entries(hass, mapping)
    except AdapterUnavailable as error:
        return [], [f"helpers were not scanned, check them manually ({error})"]
    warnings = [
        f"helper {plan.domain} '{plan.title}' stores entity IDs in its data and must be "
        f"changed manually ({len(plan.manual)} hit(s))"
        for plan in plans
        if plan.manual
    ]
    return [plan for plan in plans if plan.findings], warnings
