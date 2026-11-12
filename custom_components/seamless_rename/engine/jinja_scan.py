"""Warn about Jinja constructs that build entity IDs dynamically.

A rename can only rewrite IDs that appear literally. Anything assembled at runtime is
reported so the user can check it by hand.
"""

import re
from collections.abc import Collection

from .ids import object_id
from .messages import CodedMessage

MESSAGE = "possible pattern reference, check manually"
MIN_FRAGMENT_LENGTH = 6
LITERAL_HEURISTIC = "literal holds part of an old object ID"

_JINJA_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)
_LITERAL_RE = re.compile(r"""'([^'\\]*)'|"([^"\\]*)\"""")

_HEURISTICS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("selectattr search/match", re.compile(r"selectattr\([^)]*['\"](?:search|match)['\"]")),
    ("startswith", re.compile(r"\bstartswith\b")),
    ("states.<domain> filter", re.compile(r"\bstates\.[a-z_]+\s*\|")),
    ("domain prefix concatenation", re.compile(r"""['"][a-z_]+\.['"]\s*~""")),
)


def _fragment_in_literal(literal: str, old_id: str) -> bool:
    """True if the literal holds a long piece of the object ID but not the whole ID."""
    if old_id in literal:
        return False
    name = object_id(old_id)
    return any(
        name[start : start + MIN_FRAGMENT_LENGTH] in literal
        for start in range(len(name) - MIN_FRAGMENT_LENGTH + 1)
    )


def find_pattern_warnings(scalar: str, old_ids: Collection[str]) -> list[CodedMessage]:
    """Return one warning per dynamic-pattern heuristic that fires inside Jinja code."""
    warnings: list[CodedMessage] = []
    jinja = [region.group(0) for region in _JINJA_RE.finditer(scalar)]
    if not jinja:
        return warnings
    code = "\n".join(jinja)

    for name, pattern in _HEURISTICS:
        if pattern.search(code):
            warnings.append(
                CodedMessage("pattern_reference", f"{MESSAGE} ({name})", heuristic=name)
            )

    literals = [first or second for first, second in _LITERAL_RE.findall(code)]
    if any(_fragment_in_literal(literal, old_id) for literal in literals for old_id in old_ids):
        warnings.append(
            CodedMessage(
                "pattern_reference",
                f"{MESSAGE} (literal holds part of an old object ID)",
                heuristic=LITERAL_HEURISTIC,
            )
        )
    return warnings
