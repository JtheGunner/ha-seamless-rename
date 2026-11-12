"""Apply findings to source text by span replacement."""

from collections.abc import Sequence
from collections.abc import Set as AbstractSet

from .models import Confidence, Finding


def apply_edits(text: str, findings: Sequence[Finding], replace: AbstractSet[Confidence]) -> str:
    """Return ``text`` with every selected finding replaced in a single pass.

    Only the span of each finding is touched, so comments, quoting, line endings and
    all other bytes stay as they are. Spans are applied back to front so earlier
    offsets remain valid, and every span is checked against ``Finding.old`` first.
    """
    selected = [
        finding
        for finding in findings
        if finding.confidence in replace
        and finding.offset is not None
        and finding.length is not None
    ]
    result = text
    for finding in sorted(selected, key=lambda item: item.offset or 0, reverse=True):
        start = finding.offset or 0
        end = start + (finding.length or 0)
        if text[start:end] != finding.old:
            raise ValueError(f"source changed since scan at {finding.location}:{finding.line}")
        result = result[:start] + finding.new + result[end:]
    return result
