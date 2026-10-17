"""Function table of the attribute expression language (a subset of NiFi's).

Values are ``str | float | bool | None``. ``None`` is "no value" (absent, null, empty or a
non-scalar attribute) and makes every comparison false instead of failing the device.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

Value = str | float | bool | None
ReturnType = Literal["bool", "number", "string"]

# Longest text a transform may produce; longer results count as "no value" instead of
# allocating an attribute-sized product in the worker (e.g. replace() on a parsed config).
MAX_TEXT_LENGTH = 1_000_000

# Functions that read the subject's existence state rather than its text.
STATE_FUNCTIONS = frozenset({"isAbsent", "isNull", "isEmpty", "exists"})
# ``count()`` reads the subject's raw value (a list has no text), so like the state functions it
# is only valid first in a chain.
COUNT_FUNCTION = "count"
FIRST_ONLY_FUNCTIONS = STATE_FUNCTIONS | {COUNT_FUNCTION}
# Functions that need the isolated regex runner: name -> match mode.
REGEX_FUNCTIONS = {"matches": "full", "find": "find"}


@dataclass(frozen=True)
class FunctionSpec:
    min_args: int
    max_args: int | None
    returns: ReturnType
    impl: Callable[[Value, Sequence[Value]], Value] | None = None


def count_items(raw: Any) -> int:
    """Number of items: list length, dict keys, 1 for a non-empty scalar or sealed secret, else 0.

    ``None`` (absent or null), an empty string, list or dict count 0.
    """
    from services.workflow_context.secret_fields import is_sealed_secret

    if raw is None:
        return 0
    if is_sealed_secret(raw):
        return 1
    if isinstance(raw, (list, dict)):
        return len(raw)
    return 1 if str(raw).strip() else 0


def to_number(value: Value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        number = float(value.strip())
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def to_text(value: Value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        number = float(value)
        return str(int(number)) if number.is_integer() else repr(number)
    return value


def to_bool(value: Value) -> bool:
    if isinstance(value, bool):
        return value
    return isinstance(value, str) and value.strip().lower() == "true"


def _text_pair(subject: Value, args: Sequence[Value]) -> tuple[str, str] | None:
    left, right = to_text(subject), to_text(args[0])
    return None if left is None or right is None else (left, right)


def _equals(subject: Value, args: Sequence[Value]) -> bool:
    if isinstance(subject, float) or isinstance(args[0], float):
        left, right = to_number(subject), to_number(args[0])
        return left is not None and left == right
    pair = _text_pair(subject, args)
    return pair is not None and pair[0] == pair[1]


def _text_predicate(test: Callable[[str, str], bool]) -> Callable[[Value, Sequence[Value]], Value]:
    def impl(subject: Value, args: Sequence[Value]) -> Value:
        pair = _text_pair(subject, args)
        return pair is not None and test(*pair)

    return impl


def _in(subject: Value, args: Sequence[Value]) -> bool:
    return any(_equals(subject, [candidate]) for candidate in args)


def _compare(test: Callable[[float, float], bool]) -> Callable[[Value, Sequence[Value]], Value]:
    def impl(subject: Value, args: Sequence[Value]) -> Value:
        left, right = to_number(subject), to_number(args[0])
        return left is not None and right is not None and test(left, right)

    return impl


def _arithmetic(
    op: Callable[[float, float], float | None],
) -> Callable[[Value, Sequence[Value]], Value]:
    def impl(subject: Value, args: Sequence[Value]) -> Value:
        left, right = to_number(subject), to_number(args[0])
        if left is None or right is None:
            return None
        return op(left, right)

    return impl


def _mod(left: float, right: float) -> float | None:
    return None if right == 0 else math.fmod(left, right)


def _text_transform(fn: Callable[[str], Value]) -> Callable[[Value, Sequence[Value]], Value]:
    def impl(subject: Value, args: Sequence[Value]) -> Value:
        text = to_text(subject)
        return None if text is None else fn(text)

    return impl


def _join(subject: Value, args: Sequence[Value], *, prefix: bool) -> Value:
    text, other = to_text(subject), to_text(args[0])
    if text is None or other is None or len(text) + len(other) > MAX_TEXT_LENGTH:
        return None
    return other + text if prefix else text + other


def _substring(subject: Value, args: Sequence[Value]) -> Value:
    text = to_text(subject)
    bounds = [to_number(arg) for arg in args]
    if text is None or any(bound is None for bound in bounds):
        return None
    start = int(bounds[0])  # type: ignore[arg-type]
    end = int(bounds[1]) if len(bounds) > 1 else len(text)  # type: ignore[arg-type]
    return text[start:end]


def _replace(subject: Value, args: Sequence[Value]) -> Value:
    text, old, new = to_text(subject), to_text(args[0]), to_text(args[1])
    if text is None or not old or new is None:  # '' would insert `new` between every character
        return None
    if len(text) + text.count(old) * (len(new) - len(old)) > MAX_TEXT_LENGTH:
        return None
    return text.replace(old, new)


def _to_number_fn(subject: Value, _args: Sequence[Value]) -> Value:
    return to_number(subject)


FUNCTIONS: dict[str, FunctionSpec] = {
    **{name: FunctionSpec(0, 0, "bool") for name in STATE_FUNCTIONS},
    **{name: FunctionSpec(1, 1, "bool") for name in REGEX_FUNCTIONS},
    COUNT_FUNCTION: FunctionSpec(0, 0, "number"),
    "equals": FunctionSpec(1, 1, "bool", _equals),
    "equalsIgnoreCase": FunctionSpec(
        1, 1, "bool", _text_predicate(lambda a, b: a.casefold() == b.casefold())
    ),
    "startsWith": FunctionSpec(1, 1, "bool", _text_predicate(str.startswith)),
    "endsWith": FunctionSpec(1, 1, "bool", _text_predicate(str.endswith)),
    "contains": FunctionSpec(1, 1, "bool", _text_predicate(lambda a, b: b in a)),
    "in": FunctionSpec(1, None, "bool", _in),
    "gt": FunctionSpec(1, 1, "bool", _compare(lambda a, b: a > b)),
    "ge": FunctionSpec(1, 1, "bool", _compare(lambda a, b: a >= b)),
    "lt": FunctionSpec(1, 1, "bool", _compare(lambda a, b: a < b)),
    "le": FunctionSpec(1, 1, "bool", _compare(lambda a, b: a <= b)),
    "toNumber": FunctionSpec(0, 0, "number", _to_number_fn),
    "plus": FunctionSpec(1, 1, "number", _arithmetic(lambda a, b: a + b)),
    "minus": FunctionSpec(1, 1, "number", _arithmetic(lambda a, b: a - b)),
    "multiply": FunctionSpec(1, 1, "number", _arithmetic(lambda a, b: a * b)),
    "mod": FunctionSpec(1, 1, "number", _arithmetic(_mod)),
    "toLower": FunctionSpec(0, 0, "string", _text_transform(str.lower)),
    "toUpper": FunctionSpec(0, 0, "string", _text_transform(str.upper)),
    "trim": FunctionSpec(0, 0, "string", _text_transform(str.strip)),
    "length": FunctionSpec(0, 0, "number", _text_transform(lambda text: float(len(text)))),
    "substring": FunctionSpec(1, 2, "string", _substring),
    "replace": FunctionSpec(2, 2, "string", _replace),
    "append": FunctionSpec(1, 1, "string", lambda s, a: _join(s, a, prefix=False)),
    "prepend": FunctionSpec(1, 1, "string", lambda s, a: _join(s, a, prefix=True)),
    "not": FunctionSpec(0, 0, "bool", lambda s, _a: not to_bool(s)),
    "and": FunctionSpec(1, 1, "bool", lambda s, a: to_bool(s) and to_bool(a[0])),
    "or": FunctionSpec(1, 1, "bool", lambda s, a: to_bool(s) or to_bool(a[0])),
}
