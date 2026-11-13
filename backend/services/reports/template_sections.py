"""Which sections a report template refers to.

A report template reads ``sections["per-site"]`` (or ``sections.totals``, ``sections.get("x")``)
and/or loops over ``section_list`` or ``sections.items()``. A report built for a template must
provide every section the template names, otherwise strict rendering fails on the missing one.
This reads the references from the template text with a small scan (no rendering): fixed ids, a
flag for a loop over whatever sections exist (any ids work then), and a flag for a lookup it cannot
resolve (``sections[some_variable]``, ``sections.get(name)``): the needed ids are unknown then.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_BRACKET = re.compile(r"""\bsections\s*\[\s*(?:"([^"]*)"|'([^']*)')\s*\]""")
_GET = re.compile(r"""\bsections\s*\.\s*get\s*\(\s*(?:"([^"]*)"|'([^']*)')\s*[,)]""")
_DOT = re.compile(r"\bsections\s*\.\s*([A-Za-z_][A-Za-z0-9_]*)")
_ANY_BRACKET = re.compile(r"\bsections\s*\[")
_ANY_GET = re.compile(r"\bsections\s*\.\s*get\s*\(")
_LIST = re.compile(r"\bsection_list\b")
# Iterating the dict reaches every section, like ``section_list``.
_ITERATION = re.compile(r"\bsections\s*\.\s*(?:items|keys|values)\s*\(")
# Other dict methods are not section ids.
_DICT_METHODS = frozenset({"items", "keys", "values", "get", "pop", "update", "copy"})


@dataclass(frozen=True)
class TemplateSections:
    ids: tuple[str, ...]
    # The template loops over every section that exists, so any ids work.
    uses_section_list: bool
    # A lookup by variable: the ids it needs cannot be known from the text.
    dynamic: bool


def _first(match: tuple[str, str]) -> str:
    return match[0] or match[1]


def referenced_sections(template: str) -> TemplateSections:
    ids: list[str] = [_first(m) for m in _BRACKET.findall(template)]
    ids.extend(_first(m) for m in _GET.findall(template))
    ids.extend(m for m in _DOT.findall(template) if m not in _DICT_METHODS)
    dynamic = len(_ANY_BRACKET.findall(template)) > len(_BRACKET.findall(template)) or len(
        _ANY_GET.findall(template)
    ) > len(_GET.findall(template))
    return TemplateSections(
        ids=tuple(dict.fromkeys(ids)),
        uses_section_list=bool(_LIST.search(template) or _ITERATION.search(template)),
        dynamic=dynamic,
    )
