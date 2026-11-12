import os
import stat
from pathlib import Path

import pytest

from custom_components.seamless_rename.const import DEFAULT_EXCLUDES
from custom_components.seamless_rename.ha.files import (
    discover_yaml_files,
    sha256_of,
    write_atomic,
)


def _touch(path: Path, text: str = "a: 1\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _names(root: Path, found: list[Path]) -> set[str]:
    return {str(path.relative_to(root.resolve())) for path in found}


def test_discovers_yaml_and_yml_and_applies_default_excludes(tmp_path: Path) -> None:
    root = tmp_path / "config"
    _touch(root / "automations.yaml")
    _touch(root / "packages" / "music.yml")
    _touch(root / "notes.txt")
    _touch(root / ".storage" / "core.yaml")
    _touch(root / ".git" / "info.yaml")
    _touch(root / "custom_components" / "x" / "services.yaml")
    _touch(root / "secrets.yaml")
    _touch(root / ".seamless_rename" / "plans" / "p.yaml")
    found = discover_yaml_files(root, DEFAULT_EXCLUDES)
    assert _names(root, found) == {"automations.yaml", "packages/music.yml"}


def test_custom_excludes_support_globs(tmp_path: Path) -> None:
    root = tmp_path / "config"
    _touch(root / "a.yaml")
    _touch(root / "old" / "b.yaml")
    _touch(root / "c.backup.yaml")
    found = discover_yaml_files(root, ("old", "*.backup.yaml"))
    assert _names(root, found) == {"a.yaml"}


def test_symlink_outside_root_is_ignored_and_inside_is_deduplicated(tmp_path: Path) -> None:
    root = tmp_path / "config"
    target = _touch(root / "a.yaml")
    outside = _touch(tmp_path / "outside.yaml")
    (root / "link_out.yaml").symlink_to(outside)
    (root / "link_in.yaml").symlink_to(target)
    (root / "outside_dir").symlink_to(outside.parent)
    found = discover_yaml_files(root, ())
    assert _names(root, found) == {"a.yaml"}


def test_symlink_into_excluded_directory_is_excluded(tmp_path: Path) -> None:
    root = tmp_path / "config"
    hidden = _touch(root / ".storage" / "x.yaml")
    (root / "shortcut.yaml").symlink_to(hidden)
    assert discover_yaml_files(root, DEFAULT_EXCLUDES) == []


def test_directory_symlink_loop_terminates(tmp_path: Path) -> None:
    root = tmp_path / "config"
    _touch(root / "sub" / "a.yaml")
    (root / "sub" / "loop").symlink_to(root)
    found = discover_yaml_files(root, ())
    assert _names(root, found) == {"sub/a.yaml"}


def test_missing_root_returns_empty(tmp_path: Path) -> None:
    assert discover_yaml_files(tmp_path / "nope", ()) == []


def test_sha256_of_matches_known_digest(tmp_path: Path) -> None:
    path = _touch(tmp_path / "f.yaml", "abc")
    assert sha256_of(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_write_atomic_preserves_mode_and_bytes(tmp_path: Path) -> None:
    path = _touch(tmp_path / "f.yaml")
    os.chmod(path, 0o640)
    data = b"\xef\xbb\xbfa: 1\r\nb: 2"
    write_atomic(path, data)
    assert path.read_bytes() == data
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert [p.name for p in tmp_path.iterdir()] == ["f.yaml"]


def test_write_atomic_creates_new_file(tmp_path: Path) -> None:
    path = tmp_path / "new" / "f.yaml"
    write_atomic(path, b"x")
    assert path.read_bytes() == b"x"


def test_write_atomic_cleans_up_on_failure(tmp_path: Path) -> None:
    path = tmp_path / "f.yaml"
    with pytest.raises(TypeError):
        write_atomic(path, "not bytes")  # type: ignore[arg-type]
    assert list(tmp_path.iterdir()) == []
