"""Core API: plan, apply and undo a rename. Services and websocket only wrap this."""

import hashlib
import json
import logging
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.check_config import async_check_ha_config_file
from homeassistant.util import dt as dt_util

from ..const import DEFAULT_EXCLUDES, WORK_DIR_NAME
from ..engine.ids import build_domain_pattern, is_valid_entity_id
from ..engine.jinja_scan import find_pattern_warnings
from ..engine.json_scan import rewrite_json
from ..engine.models import Confidence, Finding, Rename
from ..engine.planner import (
    TEMP_ID_PREFIX,
    order_renames,
    render_diff,
    resolve_pattern,
    run_preflight,
)
from ..engine.rewrite import apply_edits
from ..engine.yaml_scan import scan_yaml
from . import helpers
from .backup import (
    FileRecord,
    Manifest,
    create_backup,
    read_manifest,
    restore_files,
    write_manifest,
)
from .files import discover_yaml_files, sha256_of, write_atomic
from .lovelace import (
    AdapterUnavailable,
    DashboardRef,
    load_dashboard,
    read_snapshot,
    render_config,
    save_dashboard,
    scan_dashboards,
    write_snapshot,
)
from .registry import registry_entity_ids, rename_entity, state_entity_ids
from .reload import domains_for_files, reload_domains

PLAN_TTL = timedelta(hours=24)
DEFAULT_REPLACE = (Confidence.CERTAIN, Confidence.LIKELY)
_LOGGER = logging.getLogger(__name__)
_ID_RE = re.compile(r"[A-Za-z0-9_.-]+")


class RenameError(Exception):
    """Base class for every error the core API raises on purpose."""


class PlanNotFound(RenameError):
    """No stored plan or backup has this ID."""


class PlanBlocked(RenameError):
    """The plan has blockers and cannot be applied."""


class PlanStale(RenameError):
    """A file changed since the plan was made, or the plan file was altered."""


class PlanExpired(RenameError):
    """The plan is older than the allowed age."""


class ConfigCheckFailed(RenameError):
    """Home Assistant rejected the rewritten configuration; files were restored."""


class ApplyFailed(RenameError):
    """The apply failed and everything was rolled back."""


class UndoRefused(RenameError):
    """The undo is not allowed in the current state."""


@dataclass(frozen=True)
class PatternSpec:
    """A bulk rename rule: ``re.sub(match, replace, entity_id)`` for matching entities."""

    match: str
    replace: str
    domain: str | None = None


@dataclass(frozen=True)
class PlanRequest:
    """Either explicit renames or a pattern, never both."""

    renames: tuple[Rename, ...] = ()
    pattern: PatternSpec | None = None


@dataclass
class PlanResult:
    plan_id: str
    renames: list[Rename]
    blockers: list[str]
    warnings: list[str]
    summary: dict[str, Any]
    diff: str = ""


@dataclass
class ApplyResult:
    apply_id: str
    status: str
    changed_files: list[str] = field(default_factory=list)
    changed_dashboards: list[str] = field(default_factory=list)
    changed_helpers: list[str] = field(default_factory=list)
    restart_required: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class AuditReport:
    """References to entities that exist neither in the registry nor in the state machine."""

    dead: dict[str, list[Finding]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_response(self) -> dict[str, Any]:
        return {
            "dead": {entity_id: findings_response(items) for entity_id, items in self.dead.items()},
            "warnings": self.warnings,
        }


def findings_response(findings: list[Finding]) -> list[dict[str, Any]]:
    return [
        {
            "file": finding.location,
            "line": finding.line,
            "confidence": finding.confidence.value,
            "text": finding.old,
        }
        for finding in findings
    ]


def _work_dir(hass: HomeAssistant) -> Path:
    return Path(hass.config.config_dir) / WORK_DIR_NAME


def _check_id(value: str, kind: str) -> None:
    if not _ID_RE.fullmatch(value) or value in {".", ".."}:
        raise PlanNotFound(f"invalid {kind} id: {value!r}")


def _canonical_hash(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "plan_hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def _finding_from_dict(data: dict[str, Any]) -> Finding:
    return Finding(**{**data, "confidence": Confidence(data["confidence"])})


def _scan_files(
    config_dir: Path, mapping: dict[str, str], pattern: re.Pattern[str] | None = None
) -> tuple[dict[str, list[Finding]], dict[str, str], list[str]]:
    """Scan every YAML file; return findings, base hashes and warnings per relative path."""
    root = config_dir.resolve()
    findings: dict[str, list[Finding]] = {}
    hashes: dict[str, str] = {}
    warnings: list[str] = []
    for path in discover_yaml_files(root, DEFAULT_EXCLUDES):
        relative = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as error:
            warnings.append(f"{relative}: could not be read and was skipped ({error})")
            continue
        found = scan_yaml(text, relative, mapping, pattern)
        for warning in find_pattern_warnings(text, list(mapping)):
            warnings.append(f"{relative}: {warning}")
        if found:
            findings[relative] = found
            hashes[relative] = sha256_of(path)
    return findings, hashes, list(dict.fromkeys(warnings))


def _render_all(
    config_dir: Path, findings: dict[str, list[Finding]], replace: set[Confidence]
) -> tuple[dict[str, str], str]:
    """Return the new text per file that really changes, and the combined diff."""
    root = config_dir.resolve()
    new_texts: dict[str, str] = {}
    diffs: list[str] = []
    for relative, items in findings.items():
        old = (root / relative).read_text(encoding="utf-8")
        new = apply_edits(old, items, replace)
        if new != old:
            new_texts[relative] = new
            diffs.append(render_diff(relative, old, new))
    return new_texts, "".join(diffs)


def _write_plan_files(work_dir: Path, plan_id: str, payload: dict[str, Any], diff: str) -> None:
    plans = work_dir / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    write_atomic(plans / f"{plan_id}.json", (json.dumps(payload, indent=2) + "\n").encode())
    write_atomic(plans / f"{plan_id}.diff", diff.encode())


async def plan(hass: HomeAssistant, request: PlanRequest) -> PlanResult:
    """Scan the config, store a plan and its diff, and report blockers. Writes no config."""
    if bool(request.renames) == (request.pattern is not None):
        raise ValueError("give exactly one of renames or pattern")
    registry_ids = registry_entity_ids(hass)
    state_ids = state_entity_ids(hass)
    if request.pattern is not None:
        spec = request.pattern
        renames = resolve_pattern(registry_ids, spec.match, spec.replace, spec.domain)
    else:
        renames = list(request.renames)

    preflight = run_preflight(renames, registry_ids, state_ids)
    mapping = {rename.from_id: rename.to_id for rename in renames}
    config_dir = Path(hass.config.config_dir)
    findings, hashes, scan_warnings = await hass.async_add_executor_job(
        _scan_files, config_dir, mapping
    )
    _, diff = await hass.async_add_executor_job(
        _render_all, config_dir, findings, set(DEFAULT_REPLACE)
    )
    dashboard_edits, dashboard_warnings = await scan_dashboards(hass, mapping)
    for edit in dashboard_edits:
        new_config = rewrite_json(edit.config, edit.findings, set(DEFAULT_REPLACE))
        diff += render_diff(
            f"lovelace/{edit.ref.label}.json", render_config(edit.config), render_config(new_config)
        )
    helper_plans, helper_warnings = await helpers.scan_helpers(hass, mapping)
    for helper in helper_plans:
        new_options = rewrite_json(helper.options, helper.findings, set(DEFAULT_REPLACE))
        diff += render_diff(
            f"helpers/{helper.domain}-{helper.entry_id}.json",
            render_config(helper.options),
            render_config(new_options),
        )

    plan_id = f"plan-{uuid.uuid4().hex[:12]}"
    warnings = [*preflight.warnings, *scan_warnings, *dashboard_warnings, *helper_warnings]
    summary: dict[str, Any] = {
        "files": {
            relative: {
                level.value: sum(1 for item in items if item.confidence is level)
                for level in Confidence
            }
            for relative, items in findings.items()
        },
        "dashboards": {
            edit.ref.label: {
                level.value: sum(1 for item in edit.findings if item.confidence is level)
                for level in Confidence
            }
            for edit in dashboard_edits
        },
        "helpers": {
            f"{plan.domain}:{plan.entry_id}": {
                level.value: sum(1 for item in plan.findings if item.confidence is level)
                for level in Confidence
            }
            for plan in helper_plans
        },
        "renames": len(renames),
    }
    payload: dict[str, Any] = {
        "plan_id": plan_id,
        "created_at": dt_util.utcnow().isoformat(),
        "renames": [{"from": r.from_id, "to": r.to_id} for r in renames],
        "replace": [level.value for level in DEFAULT_REPLACE],
        "base_hashes": hashes,
        "findings": {rel: [asdict(item) for item in items] for rel, items in findings.items()},
        "helpers": [
            {
                "entry_id": plan.entry_id,
                "domain": plan.domain,
                "base_hash": plan.base_hash,
                "findings": [asdict(item) for item in plan.findings],
            }
            for plan in helper_plans
        ],
        "lovelace": [
            {
                "url_path": edit.ref.url_path,
                "base_hash": edit.base_hash,
                "findings": [asdict(item) for item in edit.findings],
            }
            for edit in dashboard_edits
        ],
        "blockers": preflight.blockers,
        "warnings": warnings,
        "summary": summary,
    }
    payload["plan_hash"] = _canonical_hash(payload)
    await hass.async_add_executor_job(_write_plan_files, _work_dir(hass), plan_id, payload, diff)
    return PlanResult(plan_id, renames, preflight.blockers, warnings, summary, diff)


def _is_safe_relative(relative: str) -> bool:
    """True for a YAML path inside the config folder that no exclude pattern covers."""
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or not relative.endswith((".yaml", ".yml")):
        return False
    return not any(
        fnmatchcase(part, pattern) for part in path.parts for pattern in DEFAULT_EXCLUDES
    )


def _load_plan(work_dir: Path, plan_id: str) -> dict[str, Any]:
    _check_id(plan_id, "plan")
    path = work_dir / "plans" / f"{plan_id}.json"
    if not path.is_file():
        raise PlanNotFound(f"no plan {plan_id}")
    try:
        payload: dict[str, Any] = json.loads(path.read_text())
        if payload.get("plan_hash") != _canonical_hash(payload):
            raise PlanStale(f"plan {plan_id} was altered after it was created")
        for key in (
            "blockers",
            "created_at",
            "renames",
            "replace",
            "findings",
            "base_hashes",
            "lovelace",
            "helpers",
        ):
            if key not in payload:
                raise PlanStale(f"plan {plan_id} is incomplete: '{key}' is missing")
    except (OSError, ValueError, AttributeError) as error:
        raise PlanStale(f"plan {plan_id} could not be read: {error}") from error
    unsafe = [
        rel for rel in (*payload["base_hashes"], *payload["findings"]) if not _is_safe_relative(rel)
    ]
    if unsafe:
        raise PlanStale(f"plan {plan_id} names files that must not be written: {unsafe}")
    return payload


def _load_manifest(work_dir: Path, apply_id: str) -> tuple[Manifest, Path]:
    _check_id(apply_id, "apply")
    backup_dir = work_dir / "backups" / apply_id
    if not backup_dir.is_dir():
        raise PlanNotFound(f"no apply {apply_id}")
    try:
        return read_manifest(backup_dir), backup_dir
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise UndoRefused(f"manifest of {apply_id} could not be read: {error}") from error


def _verify_base(config_dir: Path, base_hashes: dict[str, str]) -> None:
    root = config_dir.resolve()
    for relative, expected in base_hashes.items():
        path = root / relative
        if not path.is_file() or sha256_of(path) != expected:
            raise PlanStale(f"{relative} changed since the plan was created; plan again")


def _write_texts(config_dir: Path, new_texts: dict[str, str]) -> None:
    root = config_dir.resolve()
    for relative, text in new_texts.items():
        write_atomic(root / relative, text.encode("utf-8"))


def _hash_files(config_dir: Path, relatives: list[str]) -> dict[str, str]:
    root = config_dir.resolve()
    return {relative: sha256_of(root / relative) for relative in relatives}


def _finish_manifest(backup_dir: Path, manifest: Manifest, status: str) -> None:
    manifest.status = status
    manifest.finished_at = dt_util.utcnow().isoformat()
    write_manifest(backup_dir, manifest)


def _reject_taken_temp_ids(
    hass: HomeAssistant, renames: list[Rename], ordered: list[Rename]
) -> None:
    taken = registry_entity_ids(hass) | state_entity_ids(hass)
    original = {rename.from_id for rename in renames}
    clashes = sorted(
        rename.to_id
        for rename in ordered
        if f".{TEMP_ID_PREFIX}" in rename.to_id
        and rename.to_id in taken
        and rename.to_id not in original
    )
    if clashes:
        raise PlanBlocked(f"temporary entity IDs already exist: {', '.join(clashes)}")


def _rename_in_registry(hass: HomeAssistant, ordered: list[Rename], done: list[Rename]) -> None:
    for rename in ordered:
        rename_entity(hass, rename.from_id, rename.to_id)
        done.append(rename)


def _undo_registry(hass: HomeAssistant, done: list[Rename]) -> list[str]:
    """Reverse completed renames newest first; return what could not be reverted."""
    problems: list[str] = []
    for rename in reversed(done):
        try:
            rename_entity(hass, rename.to_id, rename.from_id)
        except Exception as error:  # noqa: BLE001 - keep reverting the others
            problems.append(f"{rename.to_id} -> {rename.from_id}: {error}")
    return problems


@dataclass(frozen=True)
class _DashboardChange:
    ref: DashboardRef
    before: dict[str, Any]
    after: dict[str, Any]


async def _prepare_dashboards(
    hass: HomeAssistant, entries: list[dict[str, Any]], replace: set[Confidence]
) -> list[_DashboardChange]:
    """Re-read each planned dashboard, verify its hash and compute the new configuration."""
    changes: list[_DashboardChange] = []
    for entry in entries:
        ref = DashboardRef(entry["url_path"])
        try:
            config, digest = await load_dashboard(hass, ref)
        except AdapterUnavailable as error:
            raise PlanStale(f"dashboard {ref.label} cannot be read: {error}; plan again") from error
        if digest != entry["base_hash"]:
            raise PlanStale(f"dashboard {ref.label} changed since the plan was created; plan again")
        found = [_finding_from_dict(item) for item in entry["findings"]]
        after = rewrite_json(config, found, replace)
        if after != config:
            changes.append(_DashboardChange(ref, config, after))
    return changes


def _write_snapshots(backup_dir: Path, changes: list[_DashboardChange]) -> list[str]:
    return [write_snapshot(backup_dir, c.ref, c.before, c.after) for c in changes]


@dataclass(frozen=True)
class _HelperSnapshot:
    entry_id: str
    domain: str
    before: dict[str, Any]


def _prepare_helpers(hass: HomeAssistant, entries: list[dict[str, Any]]) -> list[_HelperSnapshot]:
    """Verify each planned helper entry is unchanged and capture its options."""
    snapshots: list[_HelperSnapshot] = []
    for entry in entries:
        try:
            options, digest = helpers.current_options(hass, entry["entry_id"])
        except AdapterUnavailable as error:
            raise PlanStale(
                f"helper {entry['entry_id']} cannot be read: {error}; plan again"
            ) from error
        if digest != entry["base_hash"]:
            raise PlanStale(
                f"helper {entry['entry_id']} changed since the plan was created; plan again"
            )
        snapshots.append(_HelperSnapshot(entry["entry_id"], entry["domain"], options))
    return snapshots


def _write_helper_snapshots(
    backup_dir: Path, snapshots: list[_HelperSnapshot], after: dict[str, dict[str, Any]]
) -> list[str]:
    return [
        helpers.write_snapshot(
            backup_dir,
            snap.entry_id,
            snap.domain,
            snap.before,
            after.get(snap.entry_id, snap.before),
        )
        for snap in snapshots
    ]


async def apply(hass: HomeAssistant, plan_id: str) -> ApplyResult:
    """Apply a stored plan: back up, rewrite files, check config, rename, reload."""
    work_dir = _work_dir(hass)
    config_dir = Path(hass.config.config_dir)
    payload = await hass.async_add_executor_job(_load_plan, work_dir, plan_id)
    if payload["blockers"]:
        raise PlanBlocked("; ".join(payload["blockers"]))
    created = dt_util.parse_datetime(payload["created_at"])
    if created is None or dt_util.utcnow() - created > PLAN_TTL:
        raise PlanExpired(f"plan {plan_id} is older than {PLAN_TTL}; plan again")
    await hass.async_add_executor_job(_verify_base, config_dir, payload["base_hashes"])

    renames = [Rename(item["from"], item["to"]) for item in payload["renames"]]
    mapping = {rename.from_id: rename.to_id for rename in renames}
    ordered = order_renames(renames)
    _reject_taken_temp_ids(hass, renames, ordered)
    findings = {
        rel: [_finding_from_dict(item) for item in items]
        for rel, items in payload["findings"].items()
    }
    replace = {Confidence(level) for level in payload["replace"]}
    new_texts, _ = await hass.async_add_executor_job(_render_all, config_dir, findings, replace)
    changed = sorted(new_texts)
    dashboards = await _prepare_dashboards(hass, payload["lovelace"], replace)
    helper_snapshots = _prepare_helpers(hass, payload["helpers"])

    root = config_dir.resolve()
    apply_id = f"apply-{dt_util.utcnow():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    backup_dir = await hass.async_add_executor_job(
        create_backup, work_dir, apply_id, [root / relative for relative in changed]
    )
    before = await hass.async_add_executor_job(_hash_files, config_dir, changed)
    manifest = Manifest(
        apply_id=apply_id,
        created_at=dt_util.utcnow().isoformat(),
        renames=renames,
        files=[FileRecord(str(root / rel), before[rel]) for rel in changed],
    )
    stale = [rel for rel in changed if before[rel] != payload["base_hashes"].get(rel)]
    if stale:
        await hass.async_add_executor_job(_finish_manifest, backup_dir, manifest, "rolled_back")
        raise PlanStale(f"{', '.join(stale)} changed while the apply started; plan again")
    if dashboards:
        manifest.snapshots = await hass.async_add_executor_job(
            _write_snapshots, backup_dir, dashboards
        )
    if helper_snapshots:
        manifest.snapshots += await hass.async_add_executor_job(
            _write_helper_snapshots, backup_dir, helper_snapshots, {}
        )
    await hass.async_add_executor_job(write_manifest, backup_dir, manifest)

    done: list[Rename] = []
    saved: list[_DashboardChange] = []
    edited_helpers: list[tuple[str, dict[str, Any]]] = []
    files_written = False

    async def roll_back() -> list[str]:
        problems: list[str] = []
        for entry_id, options_before in reversed(edited_helpers):
            try:
                helpers.set_options(hass, entry_id, options_before)
            except AdapterUnavailable as error:
                problems.append(f"helper {entry_id} could not be restored: {error}")
        problems += _undo_registry(hass, done)
        for change in reversed(saved):
            try:
                await save_dashboard(hass, change.ref, change.before)
            except AdapterUnavailable as error:
                problems.append(f"dashboard {change.ref.label} could not be restored: {error}")
        if files_written and manifest.files:
            try:
                await hass.async_add_executor_job(restore_files, manifest, backup_dir)
            except Exception as error:  # noqa: BLE001 - reported to the caller
                problems.append(f"files could not be restored: {error}")
        status = "failed" if problems else "rolled_back"
        try:
            await hass.async_add_executor_job(_finish_manifest, backup_dir, manifest, status)
        except Exception:
            _LOGGER.exception("could not record the outcome of apply %s", apply_id)
        return problems

    try:
        if new_texts:
            files_written = True
            await hass.async_add_executor_job(_write_texts, config_dir, new_texts)
            error_text = await async_check_ha_config_file(hass)
            if error_text:
                raise ConfigCheckFailed(error_text)
        _rename_in_registry(hass, ordered, done)
        for change in dashboards:
            await save_dashboard(hass, change.ref, change.after)
            saved.append(change)
        if helper_snapshots:
            fresh = await helpers.scan_entries(hass, mapping)
            await helpers.apply_entry_edits(hass, fresh, replace, edited_helpers)
        helper_after = {
            snap.entry_id: helpers.current_options(hass, snap.entry_id)[0]
            for snap in helper_snapshots
        }
        if helper_snapshots:
            await hass.async_add_executor_job(
                _write_helper_snapshots, backup_dir, helper_snapshots, helper_after
            )
        after = await hass.async_add_executor_job(_hash_files, config_dir, changed)
        for record in manifest.files:
            record.sha256_after = after[Path(record.path).relative_to(root).as_posix()]
        await hass.async_add_executor_job(_finish_manifest, backup_dir, manifest, "completed")
    except BaseException as error:
        problems = await roll_back()
        if isinstance(error, ConfigCheckFailed) and not problems:
            raise
        if not isinstance(error, Exception):
            raise
        detail = f"; manual repair needed: {'; '.join(problems)}" if problems else ""
        raise ApplyFailed(f"apply failed and was rolled back: {error}{detail}") from error

    warnings: list[str] = []
    domains, unknown = domains_for_files(changed)
    try:
        needs_restart = bool(await reload_domains(hass, domains)) or unknown
    except Exception as error:  # noqa: BLE001 - the change itself is already in place
        warnings.append(f"reload failed, restart Home Assistant: {error}")
        needs_restart = True
    known = registry_entity_ids(hass)
    warnings.extend(
        f"{rename.to_id} is missing from the entity registry after the apply"
        for rename in renames
        if rename.to_id not in known
    )
    return ApplyResult(
        apply_id,
        "completed",
        changed,
        [change.ref.label for change in dashboards],
        [entry_id for entry_id, _ in edited_helpers],
        needs_restart,
        warnings,
    )


async def undo(hass: HomeAssistant, apply_id: str, *, force: bool = False) -> ApplyResult:
    """Reverse a completed apply; refuse if files changed since, unless ``force``."""
    manifest, backup_dir = await hass.async_add_executor_job(
        _load_manifest, _work_dir(hass), apply_id
    )
    if manifest.status != "completed":
        raise UndoRefused(
            f"apply {apply_id} has status {manifest.status}; only completed applies can be undone"
        )
    try:
        snapshots = [
            await hass.async_add_executor_job(read_snapshot, backup_dir, name)
            for name in manifest.snapshots
            if name.startswith("dashboards/")
        ]
        helper_snaps = [
            await hass.async_add_executor_job(helpers.read_snapshot, backup_dir, name)
            for name in manifest.snapshots
            if name.startswith("helpers/")
        ]
    except ValueError as error:
        raise UndoRefused(str(error)) from error
    if not force:
        changed = await hass.async_add_executor_job(_changed_since, manifest)
        changed += await _dashboards_changed_since(hass, snapshots)
        changed += _helpers_changed_since(hass, helper_snaps)
        if changed:
            raise UndoRefused(
                f"changed since the apply: {', '.join(changed)}; use force to overwrite"
            )
    back = order_renames([Rename(r.to_id, r.from_id) for r in manifest.renames])
    done: list[Rename] = []
    restored: list[dict[str, Any]] = []
    restored_helpers: list[dict[str, Any]] = []
    try:
        for snap in helper_snaps:
            helpers.set_options(hass, snap["entry_id"], snap["before"])
            restored_helpers.append(snap)
        for snapshot in snapshots:
            await save_dashboard(hass, DashboardRef(snapshot["url_path"]), snapshot["before"])
            restored.append(snapshot)
        _rename_in_registry(hass, back, done)
        if manifest.files:
            await hass.async_add_executor_job(restore_files, manifest, backup_dir)
    except Exception as error:
        problems = _undo_registry(hass, done)
        for snap in reversed(restored_helpers):
            try:
                helpers.set_options(hass, snap["entry_id"], snap["after"])
            except AdapterUnavailable as helper_error:
                problems.append(f"helper {snap['entry_id']} not reverted: {helper_error}")
        for snapshot in reversed(restored):
            try:
                await save_dashboard(hass, DashboardRef(snapshot["url_path"]), snapshot["after"])
            except AdapterUnavailable as dashboard_error:
                problems.append(f"dashboard {snapshot['url_path']} not reverted: {dashboard_error}")
        detail = f"; manual repair needed: {'; '.join(problems)}" if problems else ""
        raise UndoRefused(f"undo failed and was reverted: {error}{detail}") from error
    root = Path(hass.config.config_dir).resolve()
    relatives = [Path(record.path).relative_to(root).as_posix() for record in manifest.files]
    domains, unknown = domains_for_files(relatives)
    warnings: list[str] = []
    try:
        needs_restart = bool(await reload_domains(hass, domains)) or unknown
    except Exception as error:  # noqa: BLE001 - the files are already restored
        warnings.append(f"reload failed, restart Home Assistant: {error}")
        needs_restart = True
    await hass.async_add_executor_job(_finish_manifest, backup_dir, manifest, "undone")
    return ApplyResult(
        apply_id,
        "undone",
        relatives,
        [DashboardRef(snapshot["url_path"]).label for snapshot in snapshots],
        [snap["entry_id"] for snap in helper_snaps],
        needs_restart,
        warnings,
    )


async def _dashboards_changed_since(
    hass: HomeAssistant, snapshots: list[dict[str, Any]]
) -> list[str]:
    changed: list[str] = []
    for snapshot in snapshots:
        ref = DashboardRef(snapshot["url_path"])
        try:
            _, digest = await load_dashboard(hass, ref)
        except AdapterUnavailable:
            changed.append(f"dashboard {ref.label}")
            continue
        if digest != snapshot["sha256_after"]:
            changed.append(f"dashboard {ref.label}")
    return changed


def _helpers_changed_since(hass: HomeAssistant, snapshots: list[dict[str, Any]]) -> list[str]:
    changed: list[str] = []
    for snap in snapshots:
        try:
            _, digest = helpers.current_options(hass, snap["entry_id"])
        except AdapterUnavailable:
            changed.append(f"helper {snap['entry_id']}")
            continue
        if digest != snap["sha256_after"]:
            changed.append(f"helper {snap['entry_id']}")
    return changed


def _changed_since(manifest: Manifest) -> list[str]:
    return [
        record.path
        for record in manifest.files
        if not Path(record.path).is_file() or sha256_of(Path(record.path)) != record.sha256_after
    ]


async def audit(hass: HomeAssistant) -> AuditReport:
    """List references in the YAML files to entities that do not exist. Writes nothing.

    Only IDs of a domain that the running system knows are considered, and IDs that are
    registered services (``light.turn_on``) are skipped. Dynamically built IDs are not found.
    """
    known = registry_entity_ids(hass) | state_entity_ids(hass)
    domains = {entity_id.split(".", 1)[0] for entity_id in known}
    pattern = build_domain_pattern(domains)
    findings, _, warnings = await hass.async_add_executor_job(
        _scan_files, Path(hass.config.config_dir), {}, pattern
    )
    dead: dict[str, list[Finding]] = {}
    for items in findings.values():
        for finding in items:
            domain, object_part = finding.old.split(".", 1)
            if finding.old in known or hass.services.has_service(domain, object_part):
                continue
            dead.setdefault(finding.old, []).append(finding)
    return AuditReport(dead=dict(sorted(dead.items())), warnings=warnings)


async def references(hass: HomeAssistant, entity_id: str) -> list[Finding]:
    """List every place in the YAML files that mentions ``entity_id``. Writes nothing."""
    if not is_valid_entity_id(entity_id):
        raise ValueError(f"'{entity_id}' is not a valid entity ID")
    findings, _, _ = await hass.async_add_executor_job(
        _scan_files, Path(hass.config.config_dir), {entity_id: entity_id}, None
    )
    return sorted(
        (item for items in findings.values() for item in items),
        key=lambda item: (item.location, item.line),
    )
