"""Backups and the manifest that makes an apply reversible."""

import hashlib
import json
import re
import shutil
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..engine.models import Rename
from .files import sha256_of, write_atomic

MANIFEST_NAME = "manifest.json"
FILES_DIR = "files"
_APPLY_ID_RE = re.compile(r"[A-Za-z0-9_.-]+")


@dataclass
class FileRecord:
    """One text file touched by an apply."""

    path: str
    sha256_before: str
    sha256_after: str | None = None


@dataclass
class Manifest:
    """What an apply changed, so that it can be verified and undone.

    ``status`` is ``in_progress`` until the apply ends as ``completed``, ``rolled_back`` or
    ``failed``. ``snapshots`` names the dashboard and helper snapshot files stored next to
    the manifest.
    """

    apply_id: str
    created_at: str
    renames: list[Rename] = field(default_factory=list)
    files: list[FileRecord] = field(default_factory=list)
    snapshots: list[str] = field(default_factory=list)
    excluded_finding_ids: list[str] = field(default_factory=list)
    status: str = "in_progress"
    finished_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "apply_id": self.apply_id,
            "created_at": self.created_at,
            "renames": [{"from": rename.from_id, "to": rename.to_id} for rename in self.renames],
            "files": [
                {"path": f.path, "sha256_before": f.sha256_before, "sha256_after": f.sha256_after}
                for f in self.files
            ],
            "snapshots": list(self.snapshots),
            "excluded_finding_ids": list(self.excluded_finding_ids),
            "status": self.status,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Manifest:
        return cls(
            apply_id=data["apply_id"],
            created_at=data["created_at"],
            renames=[Rename(item["from"], item["to"]) for item in data["renames"]],
            files=[FileRecord(**item) for item in data["files"]],
            snapshots=list(data["snapshots"]),
            excluded_finding_ids=list(data["excluded_finding_ids"]),
            status=data["status"],
            finished_at=data["finished_at"],
        )


def _backup_name(path: str) -> str:
    """Name of a file's copy inside the backup folder; unique per full path."""
    return hashlib.sha256(path.encode()).hexdigest()


def create_backup(work_dir: Path, apply_id: str, paths: Sequence[Path]) -> Path:
    """Copy ``paths`` into ``<work_dir>/backups/<apply_id>/files`` and return that folder's parent.

    Raises ``FileExistsError`` if a backup with this ID already exists and ``ValueError`` for
    an ID that could point outside the backup folder.
    """
    if not _APPLY_ID_RE.fullmatch(apply_id) or apply_id in {".", ".."}:
        raise ValueError(f"invalid apply id: {apply_id!r}")
    backup_dir = work_dir / "backups" / apply_id
    files_dir = backup_dir / FILES_DIR
    files_dir.parent.mkdir(parents=True, exist_ok=False)
    files_dir.mkdir()
    for path in paths:
        shutil.copy2(path, files_dir / _backup_name(str(path)))
    return backup_dir


def write_manifest(backup_dir: Path, manifest: Manifest) -> None:
    """Write the manifest as JSON next to the backed-up files."""
    payload = json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False) + "\n"
    write_atomic(backup_dir / MANIFEST_NAME, payload.encode())


def read_manifest(backup_dir: Path) -> Manifest:
    """Read the manifest written by ``write_manifest``."""
    return Manifest.from_dict(json.loads((backup_dir / MANIFEST_NAME).read_text()))


def restore_files(manifest: Manifest, backup_dir: Path) -> None:
    """Put every file of the manifest back to its content before the apply.

    All backup copies are verified against ``sha256_before`` first, so a damaged backup
    raises ``ValueError`` before any file is touched.
    """
    restorations: list[tuple[Path, bytes]] = []
    for record in manifest.files:
        data = (backup_dir / FILES_DIR / _backup_name(record.path)).read_bytes()
        if hashlib.sha256(data).hexdigest() != record.sha256_before:
            raise ValueError(f"backup of {record.path} failed sha256 verification")
        restorations.append((Path(record.path), data))
    for path, data in restorations:
        write_atomic(path, data)
        if sha256_of(path) != hashlib.sha256(data).hexdigest():
            raise ValueError(f"restored file {path} does not match its backup")
