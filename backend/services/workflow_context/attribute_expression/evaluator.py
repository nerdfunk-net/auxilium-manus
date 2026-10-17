"""Evaluate a parsed attribute expression against one device.

Evaluation is eager (``and``/``or`` evaluate both sides) and side-effect free, which lets the
regex functions work in two passes: the first pass records every ``(text, pattern, mode)`` it
would test in ``RegexLookup.pending`` and answers ``False``; the caller runs the whole batch in
the isolated regex runner and evaluates again with ``RegexLookup.results`` filled in.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from models.workflow_context import DeviceContext, DeviceError
from services.workflow_context.attribute_expression.functions import (
    COUNT_FUNCTION,
    FUNCTIONS,
    REGEX_FUNCTIONS,
    STATE_FUNCTIONS,
    Value,
    count_items,
    to_bool,
    to_text,
)
from services.workflow_context.attribute_expression.parser import Call, Expr, Literal, Node
from services.workflow_context.attribute_path import (
    AttributeState,
    resolve_device_attribute_raw,
    resolve_device_attribute_state,
)

RegexKey = tuple[str, str, str]

_STATE_FOR_FUNCTION = {
    "isAbsent": AttributeState.ABSENT,
    "isNull": AttributeState.NULL,
    "isEmpty": AttributeState.EMPTY,
    "exists": AttributeState.PRESENT,
}


# What the isolated runner answers for a question it could not evaluate.
REGEX_INVALID = "invalid"
REGEX_STOPPED = "stopped"


class RegexUnavailableError(Exception):
    """A regex in the expression could not be evaluated for this device.

    ``code`` is ``invalid_regular_expression`` or ``regular_expression_stopped``. The message
    never contains the pattern or the text: both can come from device attributes.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class RegexLookup:
    """Regex answers, and the questions that had no answer yet.

    A question without an answer is recorded in ``pending`` and answered ``False``, so a
    collecting caller learns what to ask; it repeats until nothing new is pending (a pattern
    may be built from an earlier regex result). ``strict`` makes an answer of "invalid" or
    "stopped" raise ``RegexUnavailableError``; a collecting pass reads it as ``False``.
    """

    results: dict[RegexKey, bool | str] = field(default_factory=dict)
    pending: set[RegexKey] = field(default_factory=set)
    strict: bool = True

    def test(self, text: str, pattern: str, mode: str) -> bool:
        key = (text, pattern, mode)
        if key not in self.results:
            self.pending.add(key)
            return False
        answer = self.results[key]
        if isinstance(answer, bool):
            return answer
        if not self.strict:
            return False
        if answer == REGEX_INVALID:
            raise RegexUnavailableError(
                "invalid_regular_expression", "a regular expression in the route is not valid"
            )
        raise RegexUnavailableError(
            "regular_expression_stopped",
            "a regular expression in the route used too much time or memory",
        )


def _apply_call(
    call: Call,
    value: Value,
    device: DeviceContext,
    default_path: str,
    regex: RegexLookup,
    error: DeviceError | None,
) -> Value:
    args = [_node_value(arg, device, default_path, regex, error) for arg in call.args]
    mode = REGEX_FUNCTIONS.get(call.name)
    if mode is not None:
        text, pattern = to_text(value), to_text(args[0])
        return text is not None and pattern is not None and regex.test(text, pattern, mode)
    impl = FUNCTIONS[call.name].impl
    if impl is None:  # state functions are only valid first in a chain; the parser enforces it
        raise ValueError(f"{call.name}() must be the first function in the chain")
    return impl(value, args)


def _node_value(
    node: Node,
    device: DeviceContext,
    default_path: str,
    regex: RegexLookup,
    error: DeviceError | None,
) -> Value:
    if isinstance(node, Literal):
        return node.value
    return _expr_value(node, device, default_path, regex, error)


def _expr_value(
    expr: Expr,
    device: DeviceContext,
    default_path: str,
    regex: RegexLookup,
    error: DeviceError | None,
) -> Value:
    path = expr.subject or default_path
    state, text = resolve_device_attribute_state(device, path, error=error)
    value: Value = text
    calls = expr.calls
    if calls and calls[0].name == COUNT_FUNCTION:
        value = float(count_items(resolve_device_attribute_raw(device, path, error=error)))
        calls = calls[1:]
    elif calls and calls[0].name in STATE_FUNCTIONS:
        value = state == _STATE_FOR_FUNCTION[calls[0].name]
        calls = calls[1:]
    for call in calls:
        value = _apply_call(call, value, device, default_path, regex, error)
    return value


def evaluate(
    expr: Expr,
    device: DeviceContext,
    *,
    default_path: str,
    regex: RegexLookup,
    error: DeviceError | None = None,
) -> bool:
    """True when the boolean expression holds for ``device``.

    ``default_path`` is used when the expression has no subject (``{:isEmpty()}``).
    """
    return to_bool(_expr_value(expr, device, default_path, regex, error))
