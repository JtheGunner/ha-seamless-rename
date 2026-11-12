import hashlib
from pathlib import Path

import pytest

from custom_components.seamless_rename.engine.models import Rename
from custom_components.seamless_rename.ha.backup import (
    FileRecord,
    Manifest,
    create_backup,
    read_manifest,
    restore_files,
    write_manifest,
)
from custom_components.seamless_rename.ha.files import sha256_of


def _manifest(paths: list[Path]) -> Manifest:
    return Manifest(
        apply_id="a1",
        created_at="2026-11-12T10:00:00+00:00",
        renames=[Rename("sensor.foo", "sensor.bar")],
        files=[FileRecord(path=str(path), sha256_before=sha256_of(path)) for path in paths],
        excluded_finding_ids=["f:1"],
    )


def test_backup_restore_hash_identical(tmp_path: Path) -> None:
    work = tmp_path / "work"
    first = tmp_path / "automations.yaml"
    second = tmp_path / "sub" / "scripts.yaml"
    second.parent.mkdir()
    first.write_bytes(b"a: sensor.foo\n")
    second.write_bytes(b"b: sensor.foo\n")
    manifest = _manifest([first, second])
    backup_dir = create_backup(work, "a1", [first, second])

    first.write_bytes(b"a: sensor.bar\n")
    second.unlink()
    restore_files(manifest, backup_dir)

    for record in manifest.files:
        assert sha256_of(Path(record.path)) == record.sha256_before


def test_crlf_bom_no_trailing_newline_survive_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "f.yaml"
    original = b"\xef\xbb\xbfa: 1\r\nb: sensor.foo"
    path.write_bytes(original)
    manifest = _manifest([path])
    backup_dir = create_backup(tmp_path / "work", "a1", [path])
    path.write_bytes(b"changed\n")
    restore_files(manifest, backup_dir)
    assert path.read_bytes() == original


def test_same_filename_in_different_folders_do_not_collide(tmp_path: Path) -> None:
    one = tmp_path / "one" / "x.yaml"
    two = tmp_path / "two" / "x.yaml"
    for path, text in ((one, b"1"), (two, b"2")):
        path.parent.mkdir()
        path.write_bytes(text)
    manifest = _manifest([one, two])
    backup_dir = create_backup(tmp_path / "work", "a1", [one, two])
    one.write_bytes(b"x")
    two.write_bytes(b"y")
    restore_files(manifest, backup_dir)
    assert (one.read_bytes(), two.read_bytes()) == (b"1", b"2")


def test_existing_backup_dir_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "f.yaml"
    path.write_bytes(b"x")
    create_backup(tmp_path / "work", "a1", [path])
    with pytest.raises(FileExistsError):
        create_backup(tmp_path / "work", "a1", [path])


def test_restore_detects_tampered_backup(tmp_path: Path) -> None:
    path = tmp_path / "f.yaml"
    path.write_bytes(b"original")
    manifest = _manifest([path])
    backup_dir = create_backup(tmp_path / "work", "a1", [path])
    for copy in (backup_dir / "files").iterdir():
        copy.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="sha256"):
        restore_files(manifest, backup_dir)


def test_manifest_json_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "f.yaml"
    path.write_bytes(b"x")
    manifest = _manifest([path])
    manifest.status = "completed"
    manifest.files[0].sha256_after = "abc"
    backup_dir = create_backup(tmp_path / "work", "a1", [path])
    write_manifest(backup_dir, manifest)
    assert read_manifest(backup_dir) == manifest


@pytest.mark.parametrize("apply_id", ["../x", "a/b", "..", ".", "", "/abs", "a\\b", "x y"])
def test_unsafe_apply_id_is_rejected_and_creates_nothing(tmp_path: Path, apply_id: str) -> None:
    path = tmp_path / "f.yaml"
    path.write_bytes(b"x")
    work = tmp_path / "work"
    with pytest.raises(ValueError, match="apply id"):
        create_backup(work, apply_id, [path])
    assert not work.exists()


def test_damaged_second_backup_leaves_first_file_untouched(tmp_path: Path) -> None:
    first = tmp_path / "one.yaml"
    second = tmp_path / "two.yaml"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    manifest = _manifest([first, second])
    backup_dir = create_backup(tmp_path / "work", "a1", [first, second])
    first.write_bytes(b"changed-one")
    second.write_bytes(b"changed-two")
    damaged = backup_dir / "files" / hashlib.sha256(str(second).encode()).hexdigest()
    damaged.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="sha256"):
        restore_files(manifest, backup_dir)
    assert first.read_bytes() == b"changed-one"
    assert second.read_bytes() == b"changed-two"


def test_failed_backup_is_cleaned_up_and_id_can_be_reused(tmp_path: Path) -> None:
    good = tmp_path / "good.yaml"
    good.write_bytes(b"x")
    work = tmp_path / "work"
    with pytest.raises(FileNotFoundError):
        create_backup(work, "a1", [good, tmp_path / "missing.yaml"])
    assert not (work / "backups" / "a1").exists()
    assert create_backup(work, "a1", [good]).is_dir()


def test_missing_backup_copy_raises_value_error_before_any_write(tmp_path: Path) -> None:
    path = tmp_path / "f.yaml"
    path.write_bytes(b"original")
    manifest = _manifest([path])
    backup_dir = create_backup(tmp_path / "work", "a1", [path])
    path.write_bytes(b"changed")
    for copy in (backup_dir / "files").iterdir():
        copy.unlink()
    with pytest.raises(ValueError, match="missing"):
        restore_files(manifest, backup_dir)
    assert path.read_bytes() == b"changed"
