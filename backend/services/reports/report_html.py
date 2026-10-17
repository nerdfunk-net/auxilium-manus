"""Markdown -> HTML for the email body of a report snapshot.

Raw HTML in the Markdown stays text (markdown-it ``html`` option off), only http, https and mailto
links survive (markdown-it's own link validation), and images are switched off: a data value
containing ``![](https://...)`` must not make the recipient's mail client fetch an address chosen
by whoever wrote the value.
"""

from __future__ import annotations

from functools import cache
from html import escape

from markdown_it import MarkdownIt

_STYLE = "font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.5;color:#0f172a;"
_TABLE_CSS = (
    "table{border-collapse:collapse}th,td{border:1px solid #cbd5e1;padding:4px 8px;"
    "text-align:left;font-size:13px}th{background:#f1f5f9}code,pre{background:#f1f5f9}"
    "blockquote{border-left:3px solid #cbd5e1;margin-left:0;padding-left:12px;color:#475569}"
)


@cache
def _parser() -> MarkdownIt:
    return (
        MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table").disable("image")
    )


def markdown_to_email_html(markdown: str, *, intro: str | None = None) -> str:
    """A complete HTML document for the mail body; *intro* is a plain-text note above the report."""
    note = f"<p>{escape(intro)}</p>" if intro else ""
    body = _parser().render(markdown)
    return (
        f'<!doctype html><html><head><meta charset="utf-8"><style>{_TABLE_CSS}</style></head>'
        f'<body style="{_STYLE}">{note}{body}</body></html>'
    )
