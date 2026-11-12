"""Messages that a client can translate: an English text plus a stable code and parameters.

A ``CodedMessage`` is a plain ``str`` everywhere (joining, comparing, deduplicating, JSON),
so code that only needs the English text keeps working. A client that knows the code
renders its own wording from ``params`` instead.
"""

from typing import Any


class CodedMessage(str):
    """An English message that also carries the code and parameters it was built from."""

    code: str
    params: dict[str, Any]

    def __new__(cls, code: str, text: str, **params: Any) -> CodedMessage:
        message = super().__new__(cls, text)
        message.code = code
        message.params = params
        return message


def describe(message: str) -> dict[str, Any]:
    """Return the code and parameters of a message; a plain string has no code."""
    if isinstance(message, CodedMessage):
        return {"code": message.code, "params": dict(message.params)}
    return {"code": None, "params": {}}
