"""Core API: plan, apply and undo a rename. Services and websocket only wrap this."""

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.check_config import async_check_ha_config_file
from homeassistant.util import dt as dt_util

from ..const import DEFAULT_EXCLUDES, WORK_DIR_NAME
from ..engine.jinja_scan import find_pattern_warnings
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
from .backup import (
    FileRecord,
    Manifest,
    create_backup,
    read_manifest,
    restore_files,
    write_manifest,
)
from .files import discover_yaml_files, sha256_of, write_atomic
from .registry import registry_entity_ids, rename_entity, state_entity_ids
from .reload import domains_for_files, reload_domains

PLAN_TTL = timedelta(hours=24)
DEFAULT_REPLACE = (Confidence.CERTAIN, Confidence.LIKELY)
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
    restart_required: bool = False


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
    config_dir: Path, mapping: dict[str, str]
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
        found = scan_yaml(text, relative, mapping)
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

    plan_id = f"plan-{uuid.uuid4().hex[:12]}"
    warnings = [*preflight.warnings, *scan_warnings]
    summary: dict[str, Any] = {
        "files": {
            relative: {
                level.value: sum(1 for item in items if item.confidence is level)
                for level in Confidence
            }
            for relative, items in findings.items()
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
        "blockers": preflight.blockers,
        "warnings": warnings,
        "summary": summary,
    }
    payload["plan_hash"] = _canonical_hash(payload)
    await hass.async_add_executor_job(_write_plan_files, _work_dir(hass), plan_id, payload, diff)
    return PlanResult(plan_id, renames, preflight.blockers, warnings, summary, diff)


def _load_plan(work_dir: Path, plan_id: str) -> dict[str, Any]:
    _check_id(plan_id, "plan")
    path = work_dir / "plans" / f"{plan_id}.json"
    if not path.is_file():
        raise PlanNotFound(f"no plan {plan_id}")
    payload: dict[str, Any] = json.loads(path.read_text())
    if payload.get("plan_hash") != _canonical_hash(payload):
        raise PlanStale(f"plan {plan_id} was altered after it was created")
    return payload


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


def _undo_registry(hass: HomeAssistant, done: list[Rename]) -> None:
    for rename in reversed(done):
        rename_entity(hass, rename.to_id, rename.from_id)


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
    ordered = order_renames(renames)
    _reject_taken_temp_ids(hass, renames, ordered)
    findings = {
        rel: [_finding_from_dict(item) for item in items]
        for rel, items in payload["findings"].items()
    }
    replace = {Confidence(level) for level in payload["replace"]}
    new_texts, _ = await hass.async_add_executor_job(_render_all, config_dir, findings, replace)
    changed = sorted(new_texts)

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
    await hass.async_add_executor_job(write_manifest, backup_dir, manifest)

    async def restore() -> None:
        if manifest.files:
            await hass.async_add_executor_job(restore_files, manifest, backup_dir)

    try:
        if new_texts:
            await hass.async_add_executor_job(_write_texts, config_dir, new_texts)
            error = await async_check_ha_config_file(hass)
            if error:
                await restore()
                await hass.async_add_executor_job(
                    _finish_manifest, backup_dir, manifest, "rolled_back"
                )
                raise ConfigCheckFailed(error)
        done: list[Rename] = []
        try:
            _rename_in_registry(hass, ordered, done)
        except Exception as error:
            _undo_registry(hass, done)
            await restore()
            await hass.async_add_executor_job(_finish_manifest, backup_dir, manifest, "rolled_back")
            raise ApplyFailed(f"registry rename failed and was rolled back: {error}") from error
    except RenameError:
        raise
    except BaseException:
        await hass.async_add_executor_job(_finish_manifest, backup_dir, manifest, "failed")
        raise

    after = await hass.async_add_executor_job(_hash_files, config_dir, changed)
    for record in manifest.files:
        record.sha256_after = after[Path(record.path).relative_to(root).as_posix()]
    domains, unknown = domains_for_files(changed)
    needs_restart = bool(await reload_domains(hass, domains)) or unknown
    await hass.async_add_executor_job(_finish_manifest, backup_dir, manifest, "completed")
    return ApplyResult(apply_id, "completed", changed, needs_restart)


async def undo(hass: HomeAssistant, apply_id: str, *, force: bool = False) -> ApplyResult:
    """Reverse a completed apply; refuse if files changed since, unless ``force``."""
    _check_id(apply_id, "apply")
    backup_dir = _work_dir(hass) / "backups" / apply_id
    if not backup_dir.is_dir():
        raise PlanNotFound(f"no apply {apply_id}")
    manifest = await hass.async_add_executor_job(read_manifest, backup_dir)
    if manifest.status != "completed":
        raise UndoRefused(
            f"apply {apply_id} has status {manifest.status}; only completed applies can be undone"
        )
    if not force:
        changed = await hass.async_add_executor_job(_changed_since, manifest)
        if changed:
            raise UndoRefused(
                f"files changed since the apply: {', '.join(changed)}; use force to overwrite"
            )
    for rename in order_renames([Rename(r.to_id, r.from_id) for r in manifest.renames]):
        rename_entity(hass, rename.from_id, rename.to_id)
    if manifest.files:
        await hass.async_add_executor_job(restore_files, manifest, backup_dir)
    root = Path(hass.config.config_dir).resolve()
    relatives = [Path(record.path).relative_to(root).as_posix() for record in manifest.files]
    domains, unknown = domains_for_files(relatives)
    needs_restart = bool(await reload_domains(hass, domains)) or unknown
    await hass.async_add_executor_job(_finish_manifest, backup_dir, manifest, "undone")
    return ApplyResult(apply_id, "undone", relatives, needs_restart)


def _changed_since(manifest: Manifest) -> list[str]:
    return [
        record.path
        for record in manifest.files
        if not Path(record.path).is_file() or sha256_of(Path(record.path)) != record.sha256_after
    ]
