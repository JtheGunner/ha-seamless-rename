"""Find entity ID references in YAML source text without re-serialising it."""

import bisect
import re
from collections.abc import Mapping

import yaml

from .classify import classify, inside_jinja
from .ids import build_token_pattern
from .models import Confidence, Finding


class _Scalar:
    """A scalar node's span in the source text, and the key it belongs to."""

    __slots__ = ("end", "key", "start", "value")

    def __init__(self, start: int, end: int, value: str, key: str | None) -> None:
        self.start = start
        self.end = end
        self.value = value
        self.key = key


def _collect_scalars(text: str) -> list[_Scalar] | None:
    """Return all scalar nodes (values and mapping keys) sorted by start, or None."""
    scalars: list[_Scalar] = []
    # Anchors and aliases share node objects. Visit each node once so aliased content is
    # recorded a single time and self-referencing aliases cannot recurse forever.
    visited: set[int] = set()

    def walk(node: yaml.Node, key: str | None) -> None:
        if id(node) in visited:
            return
        visited.add(id(node))
        if isinstance(node, yaml.ScalarNode):
            scalars.append(_Scalar(node.start_mark.index, node.end_mark.index, node.value, key))
        elif isinstance(node, yaml.SequenceNode):
            for item in node.value:
                walk(item, key)
        elif isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                walk(key_node, None)
                key_name = key_node.value if isinstance(key_node, yaml.ScalarNode) else None
                walk(value_node, key_name)

    try:
        for document in yaml.compose_all(text, Loader=yaml.SafeLoader):
            if document is not None:
                walk(document, None)
    except yaml.YAMLError:
        return None
    return sorted(scalars, key=lambda scalar: scalar.start)


def _classify(scalar: _Scalar, hit_start: int, hit_end: int, old_id: str, text: str) -> Confidence:
    jinja = inside_jinja(text, hit_start, hit_end, scalar.start, scalar.end)
    return classify(scalar.value, old_id, scalar.key, jinja)


def scan_yaml(
    text: str, path: str, mapping: Mapping[str, str], pattern: re.Pattern[str] | None = None
) -> list[Finding]:
    """Find every reference to a key of ``mapping`` in ``text``.

    ``pattern`` replaces the pattern built from ``mapping``; IDs it finds that are not in
    ``mapping`` are reported with ``new`` equal to ``old`` (used by the read-only audit).

    Hits outside any scalar span (comments) and every hit in a file that does not parse
    are reported as ``UNCERTAIN`` so they are visible but never replaced by default.
    """
    scalars = _collect_scalars(text)
    starts = [scalar.start for scalar in scalars] if scalars is not None else []
    findings: list[Finding] = []
    for match in (pattern or build_token_pattern(mapping)).finditer(text):
        start, end = match.span("id")
        old_id = match.group("id")
        scalar = None
        if scalars is not None:
            index = bisect.bisect_right(starts, start) - 1
            if index >= 0 and scalars[index].start <= start and end <= scalars[index].end:
                scalar = scalars[index]
        confidence = _classify(scalar, start, end, old_id, text) if scalar else Confidence.UNCERTAIN
        findings.append(
            Finding(
                finding_id=f"{path}:{start}",
                location=path,
                line=text.count("\n", 0, start) + 1,
                old=old_id,
                new=mapping.get(old_id, old_id),
                confidence=confidence,
                offset=start,
                length=end - start,
            )
        )
    return findings
