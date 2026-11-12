"""The language files of the integration must cover the same keys and placeholders."""

import json
import re
from pathlib import Path
from typing import Any

TRANSLATIONS = Path(__file__).parent.parent / "custom_components/seamless_rename/translations"
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, str]:
    flat: dict[str, str] = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten(value, path))
        else:
            flat[path] = value
    return flat


def _load(language: str) -> dict[str, str]:
    return _flatten(json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8")))


def test_every_language_covers_the_same_keys_as_english() -> None:
    english = _load("en")
    for file in sorted(TRANSLATIONS.glob("*.json")):
        assert set(_load(file.stem)) == set(english), file.name


def test_every_language_uses_the_same_placeholders_as_english() -> None:
    english = _load("en")
    for file in sorted(TRANSLATIONS.glob("*.json")):
        for key, text in _load(file.stem).items():
            assert set(PLACEHOLDER.findall(text)) == set(PLACEHOLDER.findall(english[key])), (
                file.name,
                key,
            )


def test_german_and_english_are_present() -> None:
    assert {"en", "de"} <= {file.stem for file in TRANSLATIONS.glob("*.json")}
