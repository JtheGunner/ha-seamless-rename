import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = json.loads((ROOT / "custom_components/seamless_rename/manifest.json").read_text())


def test_manifest_keys_follow_the_hassfest_order() -> None:
    keys = list(MANIFEST)
    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:])


def test_hacs_metadata_names_the_integration() -> None:
    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert hacs["name"] == MANIFEST["name"]
    assert hacs["homeassistant"]


def test_manifest_and_project_versions_match() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["version"] == MANIFEST["version"]


def test_license_file_names_the_readme_license() -> None:
    assert (ROOT / "LICENSE").read_text().startswith("MIT License")
    assert "license-MIT" in (ROOT / "README.md").read_text()


def test_display_name_is_seamless_rename() -> None:
    assert MANIFEST["name"] == "Seamless Rename"
    translations_dir = ROOT / "custom_components/seamless_rename/translations"
    for language in ("en", "de"):
        translations = json.loads((translations_dir / f"{language}.json").read_text())
        assert translations["config"]["step"]["user"]["title"] == "Seamless Rename"
