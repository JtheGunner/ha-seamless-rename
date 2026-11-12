"""Find entity ID references in YAML source text without re-serialising it."""

import bisect
import re
from collections.abc import Mapping

import yaml

from .ids import build_token_pattern
from .models import Confidence, Finding

_JINJA_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)


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

    def walk(node: yaml.Node, key: str | None) -> None:
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
    parts = [part.strip() for part in scalar.value.split(",")]
    if scalar.value.strip() == old_id:
        return Confidence.CERTAIN
    if scalar.key == "entity_id" and old_id in parts:
        return Confidence.CERTAIN
    for region in _JINJA_RE.finditer(text, scalar.start, scalar.end):
        if region.start() <= hit_start and hit_end <= region.end():
            return Confidence.LIKELY
    return Confidence.UNCERTAIN


def scan_yaml(text: str, path: str, mapping: Mapping[str, str]) -> list[Finding]:
    """Find every reference to a key of ``mapping`` in ``text``.

    Hits outside any scalar span (comments) and every hit in a file that does not parse
    are reported as ``UNCERTAIN`` so they are visible but never replaced by default.
    """
    scalars = _collect_scalars(text)
    starts = [scalar.start for scalar in scalars] if scalars is not None else []
    findings: list[Finding] = []
    for match in build_token_pattern(mapping).finditer(text):
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
                new=mapping[old_id],
                confidence=confidence,
                offset=start,
                length=end - start,
            )
        )
    return findings
