"""File discovery and atomic writes inside the Home Assistant config directory."""

import contextlib
import hashlib
import os
import stat
import tempfile
from collections.abc import Collection
from fnmatch import fnmatchcase
from pathlib import Path

_YAML_SUFFIXES = (".yaml", ".yml")
_NEW_FILE_MODE = 0o644
_CHUNK_SIZE = 1024 * 1024


def _is_excluded(parts: Collection[str], excludes: Collection[str]) -> bool:
    return any(fnmatchcase(part, pattern) for part in parts for pattern in excludes)


def discover_yaml_files(root: Path, excludes: Collection[str]) -> list[Path]:
    """Return every YAML file below ``root`` that is neither excluded nor outside it.

    ``excludes`` holds glob patterns that are matched against each path component, so
    ``.storage`` excludes that folder at any depth and ``*.log*`` excludes matching names.
    Symlinks are resolved: a link pointing outside ``root`` is ignored, a link pointing
    inside is reported once under its real path, and the real path is checked against the
    excludes as well. Directory loops terminate.
    """
    if not root.is_dir():
        return []
    real_root = root.resolve()
    found: set[Path] = set()
    visited: set[Path] = set()
    for directory, dirnames, filenames in os.walk(root, followlinks=True):
        real_directory = Path(directory).resolve()
        if real_directory in visited or not real_directory.is_relative_to(real_root):
            dirnames[:] = []
            continue
        visited.add(real_directory)
        dirnames[:] = sorted(name for name in dirnames if not _is_excluded((name,), excludes))
        for name in filenames:
            if not name.endswith(_YAML_SUFFIXES) or _is_excluded((name,), excludes):
                continue
            resolved = (Path(directory) / name).resolve()
            if not resolved.is_relative_to(real_root):
                continue
            if _is_excluded(resolved.relative_to(real_root).parts, excludes):
                continue
            found.add(resolved)
    return sorted(found)


def sha256_of(path: Path) -> str:
    """Return the hex SHA-256 digest of a file's bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def write_atomic(path: Path, data: bytes) -> None:
    """Replace ``path`` with ``data`` in one step, keeping permissions and ownership.

    The data goes to a temporary file in the same folder and is moved over the target with
    ``os.replace``, so readers see either the old or the new file, never a partial one. A
    symlink as ``path`` is followed, so the link itself stays intact.
    """
    target = Path(os.path.realpath(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = target.stat() if target.exists() else None
    handle_fd, temp_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle_fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, stat.S_IMODE(existing.st_mode) if existing else _NEW_FILE_MODE)
        if existing:
            with contextlib.suppress(PermissionError, OSError):
                os.chown(temp_name, existing.st_uid, existing.st_gid)
        os.replace(temp_name, target)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp_name)
        raise
