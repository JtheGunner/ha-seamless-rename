"""Find and rewrite entity ID references in JSON-shaped data (dashboards, helper options).

Findings address their location with an RFC 6901 JSON Pointer (``/views/0/cards/2/entity``).
A pointer ending in ``#key`` refers to a dictionary key instead of the value stored under it.
``Finding.offset`` / ``length`` are positions inside that string. ``Finding.line`` is 0
because trees have no line numbers.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from typing import Any

from .classify import classify, inside_jinja
from .ids import build_token_pattern
from .models import Confidence, Finding

_KEY_SUFFIX = "#key"


def _escape(segment: str) -> str:
    return segment.replace("~", "~0").replace("/", "~1")


def _string_findings(
    value: str,
    pointer: str,
    key: str | None,
    mapping: Mapping[str, str],
    location: str,
) -> list[Finding]:
    findings: list[Finding] = []
    for match in build_token_pattern(mapping).finditer(value):
        start, end = match.span("id")
        old_id = match.group("id")
        findings.append(
            Finding(
                finding_id=f"{location}:{pointer}:{start}",
                location=location,
                line=0,
                old=old_id,
                new=mapping[old_id],
                confidence=classify(value, old_id, key, inside_jinja(value, start, end)),
                offset=start,
                length=end - start,
                json_path=pointer,
            )
        )
    return findings


def scan_json(tree: object, mapping: Mapping[str, str], location: str) -> list[Finding]:
    """Find every reference to a key of ``mapping`` in ``tree``."""
    findings: list[Finding] = []
    pattern_probe = build_token_pattern(mapping)

    def walk(node: object, pointer: str, key: str | None) -> None:
        if isinstance(node, str):
            if pattern_probe.search(node):
                findings.extend(_string_findings(node, pointer, key, mapping, location))
        elif isinstance(node, Mapping):
            for child_key, child in node.items():
                child_pointer = f"{pointer}/{_escape(str(child_key))}"
                if isinstance(child_key, str) and pattern_probe.search(child_key):
                    findings.extend(
                        _string_findings(
                            child_key, child_pointer + _KEY_SUFFIX, None, mapping, location
                        )
                    )
                walk(child, child_pointer, child_key if isinstance(child_key, str) else None)
        elif isinstance(node, Sequence):
            for index, child in enumerate(node):
                walk(child, f"{pointer}/{index}", key)

    walk(tree, "", None)
    return findings


def _apply_to_string(value: str, edits: Sequence[Finding], pointer: str) -> str:
    result = value
    for finding in sorted(edits, key=lambda item: item.offset or 0, reverse=True):
        start = finding.offset or 0
        end = start + (finding.length or 0)
        if value[start:end] != finding.old:
            raise ValueError(f"source changed since scan at {finding.location}:{pointer}")
        result = result[:start] + finding.new + result[end:]
    return result


def rewrite_json(
    tree: object, findings: Sequence[Finding], replace: AbstractSet[Confidence]
) -> Any:
    """Return a copy of ``tree`` with the selected findings applied; ``tree`` is never mutated."""
    by_pointer: dict[str, list[Finding]] = defaultdict(list)
    for finding in findings:
        if finding.confidence in replace and finding.json_path is not None:
            by_pointer[finding.json_path].append(finding)

    def rebuild(node: object, pointer: str) -> Any:
        if isinstance(node, str):
            return _apply_to_string(node, by_pointer.get(pointer, []), pointer)
        if isinstance(node, Mapping):
            entries: list[tuple[Any, Any]] = []
            for child_key, child in node.items():
                child_pointer = f"{pointer}/{_escape(str(child_key))}"
                new_key = child_key
                if isinstance(child_key, str):
                    new_key = _apply_to_string(
                        child_key, by_pointer.get(child_pointer + _KEY_SUFFIX, []), child_pointer
                    )
                entries.append((new_key, rebuild(child, child_pointer)))
            keys = [entry_key for entry_key, _ in entries]
            if len(set(keys)) != len(keys):
                raise ValueError(f"rename collides on a dictionary key under {pointer or '/'}")
            return dict(entries)
        if isinstance(node, Sequence):
            return [rebuild(child, f"{pointer}/{index}") for index, child in enumerate(node)]
        return node

    return rebuild(tree, "")
