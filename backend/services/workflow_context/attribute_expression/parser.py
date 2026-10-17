"""Parser for ``{key:function(args):function(args)...}`` attribute expressions.

Hand-written recursive descent over a whitelist of functions (``functions.FUNCTIONS``); nothing is
ever passed to ``eval``. The result is an immutable AST. Every error is a ``ValueError`` naming the
character position, so it can be shown when the workflow is saved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from services.workflow_context.attribute_expression.functions import (
    FIRST_ONLY_FUNCTIONS,
    FUNCTIONS,
    REGEX_FUNCTIONS,
    ReturnType,
)


@dataclass(frozen=True)
class Literal:
    value: str | float | bool


@dataclass(frozen=True)
class Call:
    name: str
    args: tuple[Node, ...] = ()


@dataclass(frozen=True)
class Expr:
    """``subject`` is an attribute path; ``""`` stands for the step's own attribute_path."""

    subject: str
    calls: tuple[Call, ...] = ()


Node = Literal | Expr

# Deepest ``and({...})``/``or({...})`` nesting accepted; the parser and evaluator are recursive,
# so an unbounded payload would overflow the stack instead of failing as a ValueError.
MAX_NESTING = 16

_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_BOOLEAN_BARE = {"true": True, "false": False}


def _subject_end(text: str, start: int) -> int:
    """Index of the ``:`` or ``}`` ending the subject that begins at ``start`` (or -1)."""
    brackets = braces = 0
    for position in range(start, len(text)):
        char = text[position]
        if char == "[":
            brackets += 1
        elif char == "]":
            brackets = max(0, brackets - 1)
        elif char == "{":
            braces += 1
        elif char == "}":
            if braces == 0 and brackets == 0:
                return position
            braces -= 1
        elif char == ":" and brackets == 0 and braces == 0:
            return position
    return -1


def is_expression(value: str) -> bool:
    """True for a whole ``{subject:function(...)}`` value; ``{foo}`` and plain text are literals."""
    text = value.strip()
    if len(text) < 3 or text[0] != "{" or text[-1] != "}":
        return False
    end = _subject_end(text, 1)
    return end != -1 and text[end] == ":"


def returns_of(expr: Expr) -> ReturnType | None:
    """Type the chain ends in, or ``None`` for a bare ``{path}`` reference."""
    return FUNCTIONS[expr.calls[-1].name].returns if expr.calls else None


class _Parser:
    def __init__(self, text: str) -> None:
        self._text = text
        self._pos = 0
        self._depth = 0

    def error(self, message: str) -> ValueError:
        return ValueError(f"invalid expression {self._text!r}: {message} at position {self._pos}")

    def _skip_space(self) -> None:
        while self._pos < len(self._text) and self._text[self._pos].isspace():
            self._pos += 1

    def _peek(self) -> str:
        self._skip_space()
        return self._text[self._pos] if self._pos < len(self._text) else ""

    def _expect(self, char: str) -> None:
        if self._peek() != char:
            raise self.error(f"expected {char!r}")
        self._pos += 1

    def parse_top_level(self) -> Expr:
        expr = self.parse_expr()
        self._skip_space()
        if self._pos != len(self._text):
            raise self.error("unexpected text after the closing '}'")
        if not expr.calls:
            raise self.error("a function is required after ':'")
        if returns_of(expr) != "bool":
            raise self.error(f"the last function {expr.calls[-1].name!r} must return a boolean")
        return expr

    def parse_expr(self) -> Expr:
        self._depth += 1
        try:
            if self._depth > MAX_NESTING:
                raise self.error(f"expressions are nested more than {MAX_NESTING} levels deep")
            return self._parse_expr_body()
        finally:
            self._depth -= 1

    def _parse_expr_body(self) -> Expr:
        self._expect("{")
        end = _subject_end(self._text, self._pos)
        if end == -1:
            raise self.error("missing closing '}'")
        subject = self._text[self._pos : end].strip()
        self._pos = end
        calls: list[Call] = []
        while self._peek() == ":":
            self._pos += 1
            calls.append(self._parse_call(first=not calls))
        self._expect("}")
        return Expr(subject=subject, calls=tuple(calls))

    def _parse_call(self, *, first: bool) -> Call:
        self._skip_space()
        match = _NAME_RE.match(self._text, self._pos)
        if match is None:
            raise self.error("expected a function name")
        name = match.group(0)
        spec = FUNCTIONS.get(name)
        if spec is None:
            raise self.error(f"unknown function {name!r}")
        if name in FIRST_ONLY_FUNCTIONS and not first:
            raise self.error(f"{name}() must be the first function in the chain")
        self._pos = match.end()
        self._expect("(")
        args = self._parse_args()
        count = len(args)
        if count < spec.min_args or (spec.max_args is not None and count > spec.max_args):
            raise self.error(f"wrong number of arguments for {name}()")
        self._check_args(name, args)
        return Call(name=name, args=tuple(args))

    def _check_args(self, name: str, args: list[Node]) -> None:
        if name in ("and", "or"):
            arg = args[0]
            if not isinstance(arg, Expr) or returns_of(arg) != "bool":
                raise self.error(f"{name}() needs a boolean expression such as {{x:exists()}}")
        # A pattern is never compiled here: that would run caller-supplied regex in this process.
        # Syntax errors surface per device from the isolated runner; only the empty pattern,
        # which matches everything, is refused statically.
        if name in REGEX_FUNCTIONS and isinstance(args[0], Literal) and args[0].value == "":
            raise self.error(f"{name}() needs a non-empty pattern")

    def _parse_args(self) -> list[Node]:
        args: list[Node] = []
        if self._peek() == ")":
            self._pos += 1
            return args
        while True:
            args.append(self._parse_arg())
            char = self._peek()
            self._pos += 1 if char in (",", ")") else 0
            if char == ")":
                return args
            if char != ",":
                raise self.error("expected ',' or ')'")

    def _parse_arg(self) -> Node:
        char = self._peek()
        if char in ("'", '"'):
            return Literal(self._parse_string(char))
        if char == "{":
            return self.parse_expr()
        start = self._pos
        while self._pos < len(self._text) and self._text[self._pos] not in ",)":
            self._pos += 1
        token = self._text[start : self._pos].strip()
        if token in _BOOLEAN_BARE:
            return Literal(_BOOLEAN_BARE[token])
        try:
            return Literal(float(token))
        except ValueError:
            self._pos = start
            raise self.error(
                "expected a quoted string, a number, true/false or {reference}"
            ) from None

    def _parse_string(self, quote: str) -> str:
        self._pos += 1
        chars: list[str] = []
        while self._pos < len(self._text):
            char = self._text[self._pos]
            # ``\\`` and an escaped quote give one character; any other backslash is kept verbatim,
            # so a regex such as 'sw\d+' reaches the matcher unchanged.
            following = self._text[self._pos + 1 : self._pos + 2]
            if char == "\\" and following in (quote, "\\"):
                chars.append(following)
                self._pos += 2
            elif char == quote:
                self._pos += 1
                return "".join(chars)
            else:
                chars.append(char)
                self._pos += 1
        raise self.error("unterminated string")


def parse_expression(value: str) -> Expr:
    """Parse one ``{subject:function(...)}`` value; raises ``ValueError`` on any error."""
    try:
        return _Parser(value.strip()).parse_top_level()
    except RecursionError:  # pragma: no cover - MAX_NESTING stops this first
        raise ValueError("invalid expression: too deeply nested") from None


def split_values(raw: str) -> list[str]:
    """Split a comma-separated ``values`` string, keeping commas inside ``{...}`` intact.

    Quotes only matter inside braces, so a plain value such as ``it's`` is never misread.
    """
    values: list[str] = []
    current: list[str] = []
    depth = 0
    quote = ""
    escaped = False
    for char in raw:
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
        elif depth and char in ("'", '"'):
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            values.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    values.append("".join(current).strip())
    return [value for value in values if value]
