"""Storage-mode dashboards, reached only through Home Assistant's Lovelace Python API.

The Lovelace internals are not a public API. Every call into them is guarded: if anything
unexpected happens, ``AdapterUnavailable`` is raised and the caller falls back to
report-only for dashboards. Nothing in here touches ``.storage`` directly.
"""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from ..engine.json_scan import scan_json
from ..engine.models import Finding
from .files import write_atomic

SNAPSHOT_DIR = "dashboards"
DEFAULT_LABEL = "default"
_SNAPSHOT_NAME_RE = re.compile(rf"{SNAPSHOT_DIR}/[0-9a-f]{{16}}\.json")


class AdapterUnavailable(Exception):
    """The Lovelace API is missing or behaves differently than expected."""


class DashboardNotConfigured(AdapterUnavailable):
    """The dashboard has no saved configuration, so there is nothing to scan or rewrite."""


@dataclass(frozen=True)
class DashboardRef:
    """A storage-mode dashboard; ``url_path`` is ``None`` for the default dashboard."""

    url_path: str | None

    @property
    def label(self) -> str:
        return self.url_path or DEFAULT_LABEL


@dataclass(frozen=True)
class DashboardEdit:
    """The references found in one dashboard, tied to the hash they were found in."""

    ref: DashboardRef
    base_hash: str
    findings: list[Finding]
    config: dict[str, Any]


def config_hash(config: Mapping[str, Any]) -> str:
    """Return a stable SHA-256 of a dashboard configuration."""
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def render_config(config: Mapping[str, Any]) -> str:
    """Return the dashboard as indented JSON, the text form used for plan diffs."""
    return json.dumps(config, indent=2, ensure_ascii=False) + "\n"


def _lovelace_data(hass: HomeAssistant) -> Any | None:
    try:
        from homeassistant.components.lovelace.const import LOVELACE_DATA
    except ImportError as error:
        raise AdapterUnavailable(f"Lovelace API not importable: {error}") from error
    return hass.data.get(LOVELACE_DATA)


def _is_config_not_found(error: Exception) -> bool:
    try:
        from homeassistant.components.lovelace.const import ConfigNotFound
    except ImportError:
        return False
    return isinstance(error, ConfigNotFound)


def _dashboard(hass: HomeAssistant, ref: DashboardRef) -> Any:
    data = _lovelace_data(hass)
    if data is None:
        raise AdapterUnavailable("Lovelace is not loaded")
    try:
        return data.dashboards[ref.url_path]
    except (AttributeError, KeyError, TypeError) as error:
        raise AdapterUnavailable(f"dashboard {ref.label} not found: {error!r}") from error


async def list_dashboards(hass: HomeAssistant) -> list[DashboardRef]:
    """Return every storage-mode dashboard. Empty when Lovelace is not loaded."""
    data = _lovelace_data(hass)
    if data is None:
        return []
    try:
        return sorted(
            (
                DashboardRef(url_path)
                for url_path, dashboard in data.dashboards.items()
                if dashboard.mode == "storage"
            ),
            key=lambda ref: ref.label,
        )
    except (AttributeError, TypeError) as error:
        raise AdapterUnavailable(f"unexpected Lovelace data layout: {error!r}") from error


async def load_dashboard(hass: HomeAssistant, ref: DashboardRef) -> tuple[dict[str, Any], str]:
    """Return a dashboard's configuration and its hash."""
    dashboard = _dashboard(hass, ref)
    try:
        config = await dashboard.async_load(False)
    except Exception as error:
        if _is_config_not_found(error):
            raise DashboardNotConfigured(f"{ref.label} has no saved configuration") from error
        raise AdapterUnavailable(f"loading {ref.label} failed: {error!r}") from error
    if not isinstance(config, dict):
        raise AdapterUnavailable(f"{ref.label} is not a dictionary")
    return config, config_hash(config)


async def save_dashboard(hass: HomeAssistant, ref: DashboardRef, config: dict[str, Any]) -> None:
    """Replace a dashboard's configuration."""
    dashboard = _dashboard(hass, ref)
    try:
        await dashboard.async_save(config)
    except Exception as error:
        raise AdapterUnavailable(f"saving {ref.label} failed: {error!r}") from error


async def scan_dashboards(
    hass: HomeAssistant, mapping: Mapping[str, str]
) -> tuple[list[DashboardEdit], list[str]]:
    """Scan all storage dashboards; return edits and warnings. Never raises.

    A dashboard that cannot be read becomes a warning, so the plan stays usable and the
    user is told to check dashboards by hand (report-only).
    """
    try:
        refs = await list_dashboards(hass)
    except AdapterUnavailable as error:
        return [], [f"dashboards were not scanned, check them manually ({error})"]
    edits: list[DashboardEdit] = []
    warnings: list[str] = []
    for ref in refs:
        try:
            config, digest = await load_dashboard(hass, ref)
        except DashboardNotConfigured:
            continue
        except AdapterUnavailable as error:
            warnings.append(f"dashboard {ref.label} was not scanned, check it manually ({error})")
            continue
        findings = scan_json(config, mapping, f"lovelace:{ref.label}")
        if findings:
            edits.append(DashboardEdit(ref, digest, findings, config))
    return edits, warnings


def snapshot_name(ref: DashboardRef) -> str:
    """File name of a dashboard's snapshot inside the backup folder."""
    return f"{SNAPSHOT_DIR}/{hashlib.sha256(ref.label.encode()).hexdigest()[:16]}.json"


def write_snapshot(
    backup_dir: Path, ref: DashboardRef, before: dict[str, Any], after: dict[str, Any]
) -> str:
    """Store a dashboard's configuration before and after the apply; return the file name."""
    name = snapshot_name(ref)
    payload = {
        "url_path": ref.url_path,
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
        data["before"], data["after"], data["sha256_after"]  # noqa: B018 - shape check
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f"snapshot {name} is unreadable: {error}") from error
    if not isinstance(data, dict):
        raise ValueError(f"snapshot {name} is not an object")
    return data
