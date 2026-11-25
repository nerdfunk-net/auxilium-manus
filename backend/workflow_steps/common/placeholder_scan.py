"""One scanner for ``{path}`` placeholders in step text (W4-07).

A path may hold list selectors, and a selector may itself hold a placeholder: the scan is aware of
``[...]``. ``update-attribute`` expands every span it finds; the message steps (``log-message``,
``notify``, ...) use ``is_path_shaped`` to leave text such as ``{hello world}`` alone.
"""

from __future__ import annotations

import re

_PATH_CHARS = re.compile(r"[A-Za-z0-9_.]*")


def next_placeholder(template: str, start: int) -> tuple[int, int] | None:
    """Locate the next ``{path}`` placeholder at or after ``start`` as ``(open, close)``.

    A path may hold list selectors, and a selector may itself hold a placeholder, to any
    depth: ``{a.b[mac={c.d[{e.f}]}].role}``. Braces are only part of a placeholder when
    they sit inside ``[...]``; an unbracketed ``{`` starts a new candidate, so JSON-like
    text such as ``{"k": "{x.y}"}`` still expands just ``{x.y}``.
    """
    opening = template.find("{", start)
    while opening != -1:
        bracket = brace = 0
        position = opening + 1
        restart = opening + 1
        while position < len(template):
            char = template[position]
            if char == "[":
                bracket += 1
            elif char == "]":
                bracket = max(0, bracket - 1)
            elif char == "{":
                if bracket == 0:
                    restart = position
                    break
                brace += 1
            elif char == "}":
                if bracket == 0:
                    if position > opening + 1:
                        return opening, position
                    break
                if brace == 0:
                    break
                brace -= 1
            position += 1
        opening = template.find("{", restart)
    return None


def is_path_shaped(inner: str) -> bool:
    """Whether the text between the braces can be an attribute path.

    Outside ``[...]`` only letters, digits, ``_`` and ``.`` are allowed; a selector may hold
    anything (``[name=Gi 1]``, ``[mac={a.b}]``). ``{hello world}`` and ``{"k": 1}`` are text.
    """
    if not inner:
        return False
    depth = 0
    outside: list[str] = []
    for char in inner:
        if char == "[":
            depth += 1
        elif char == "]":
            if depth == 0:
                return False
            depth -= 1
        elif depth == 0:
            outside.append(char)
    return depth == 0 and _PATH_CHARS.fullmatch("".join(outside)) is not None
