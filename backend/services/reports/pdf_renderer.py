"""Render a report snapshot's Markdown to PDF with reportlab (doc/REPORTS.md).

Pure Python, no system libraries (the Docker images and the air-gapped bundle stay as they are).
The Markdown is parsed by markdown-it-py with raw HTML switched off; every text run is escaped
before it reaches reportlab's mini-markup, images are never fetched (their alt text is printed)
and only http, https and mailto links are kept. Fonts: the Bitstream Vera family that ships
with reportlab (Latin including German umlauts, ß, €, typographic dashes and quotes); other
scripts render as empty boxes.
"""

from __future__ import annotations

import io
import os
from collections.abc import Sequence
from functools import cache
from typing import Any

import reportlab
from markdown_it import MarkdownIt
from markdown_it.token import Token
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    HRFlowable,
    ListFlowable,
    ListItem,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

MAX_MARKDOWN_CHARS = 1_000_000
# Table cells come from device and report data. Layout time grows faster than the row count
# (20,000 rows took ~12 s), and one huge cell or hundreds of columns make reportlab raise.
MAX_TABLE_ROWS = 1000
MAX_TOTAL_TABLE_ROWS = 4000
MAX_TABLE_COLUMNS = 16
MAX_CELL_CHARS = 1000
MAX_CODE_LINE_CHARS = 400
PAGE_MARGIN = 18 * mm
_FONT = "Vera"
_MONO = "Courier"
_SAFE_LINK_SCHEMES = ("http://", "https://", "mailto:")
_WIDE_TABLE_COLUMNS = 8


class PdfTooLargeError(ValueError):
    """The Markdown is too long to render as a PDF."""


class PdfRenderError(ValueError):
    """The layout failed (reportlab refused the content); nothing else is known about why."""


@cache
def _register_fonts() -> None:
    directory = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
    faces = {
        _FONT: "Vera.ttf",
        f"{_FONT}-Bold": "VeraBd.ttf",
        f"{_FONT}-Italic": "VeraIt.ttf",
        f"{_FONT}-BoldItalic": "VeraBI.ttf",
    }
    for name, filename in faces.items():
        pdfmetrics.registerFont(TTFont(name, os.path.join(directory, filename)))
    pdfmetrics.registerFontFamily(
        _FONT,
        normal=_FONT,
        bold=f"{_FONT}-Bold",
        italic=f"{_FONT}-Italic",
        boldItalic=f"{_FONT}-BoldItalic",
    )


def _styles() -> dict[str, ParagraphStyle]:
    _register_fonts()
    body = ParagraphStyle(
        "body", fontName=_FONT, fontSize=10, leading=14, spaceAfter=6, alignment=TA_LEFT
    )
    headings = {
        level: ParagraphStyle(
            f"h{level}",
            parent=body,
            fontName=f"{_FONT}-Bold",
            fontSize=size,
            leading=size + 4,
            spaceBefore=10 if level > 1 else 0,
            spaceAfter=6,
            keepWithNext=1,
        )
        for level, size in {1: 20, 2: 15, 3: 12.5, 4: 11, 5: 10, 6: 10}.items()
    }
    return {
        "body": body,
        "quote": ParagraphStyle(
            "quote",
            parent=body,
            leftIndent=12,
            textColor=colors.HexColor("#475569"),
            fontName=f"{_FONT}-Italic",
        ),
        "code": ParagraphStyle(
            "code", fontName=_MONO, fontSize=8.5, leading=11, leftIndent=6, spaceAfter=6
        ),
        "cell": ParagraphStyle("cell", parent=body, fontSize=8.5, leading=10.5, spaceAfter=0),
        "cell_small": ParagraphStyle(
            "cell_small", parent=body, fontSize=7, leading=8.5, spaceAfter=0
        ),
        "head": ParagraphStyle(
            "head", parent=body, fontName=f"{_FONT}-Bold", fontSize=8.5, leading=10.5, spaceAfter=0
        ),
        "head_small": ParagraphStyle(
            "head_small",
            parent=body,
            fontName=f"{_FONT}-Bold",
            fontSize=7,
            leading=8.5,
            spaceAfter=0,
        ),
        **{f"h{level}": style for level, style in headings.items()},
    }


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline(token: Token | None) -> str:
    """reportlab mini-markup for an ``inline`` token; all text is escaped."""
    if token is None or not token.children:
        return _escape(token.content) if token is not None else ""
    parts: list[str] = []
    open_links = 0
    for child in token.children:
        kind = child.type
        if kind == "text":
            parts.append(_escape(child.content))
        elif kind == "strong_open":
            parts.append("<b>")
        elif kind == "strong_close":
            parts.append("</b>")
        elif kind == "em_open":
            parts.append("<i>")
        elif kind == "em_close":
            parts.append("</i>")
        elif kind == "code_inline":
            parts.append(f'<font face="{_MONO}">{_escape(child.content)}</font>')
        elif kind in ("softbreak",):
            parts.append(" ")
        elif kind == "hardbreak":
            parts.append("<br/>")
        elif kind == "link_open":
            href = str(child.attrGet("href") or "")
            if href.lower().startswith(_SAFE_LINK_SCHEMES):
                parts.append(
                    f'<a href="{_escape(href).replace(chr(34), "&quot;")}" color="#1d4ed8">'
                )
                open_links += 1
        elif kind == "link_close":
            if open_links:
                parts.append("</a>")
                open_links -= 1
        elif kind == "image":
            # Never fetched: print what the text says instead.
            parts.append(_escape(f"[{child.content}]" if child.content else "[image]"))
        else:  # html_inline and anything unknown is shown as plain text
            parts.append(_escape(child.content))
    parts.extend("</a>" for _ in range(open_links))
    return "".join(parts)


def _clip_cell(token: Token) -> str:
    """Inline markup of a table cell, cut to MAX_CELL_CHARS of visible text."""
    if len(token.content) > MAX_CELL_CHARS:
        clipped = Token("inline", "", 0)
        clipped.content = token.content[:MAX_CELL_CHARS] + "…"
        clipped.children = []
        return _inline(clipped)
    return _inline(token)


def _matching_close(tokens: Sequence[Token], start: int) -> int:
    level = tokens[start].level
    for index in range(start + 1, len(tokens)):
        token = tokens[index]
        if token.level == level and token.nesting == -1:
            return index
    return len(tokens) - 1


class _Builder:
    def __init__(self) -> None:
        self.styles = _styles()
        self.table_rows_left = MAX_TOTAL_TABLE_ROWS

    def blocks(self, tokens: Sequence[Token], *, quote: bool = False) -> list[Flowable]:
        out: list[Flowable] = []
        style_name = "quote" if quote else "body"
        i = 0
        while i < len(tokens):
            token = tokens[i]
            kind = token.type
            if kind == "heading_open":
                level = min(int(token.tag[1:]), 6)
                out.append(Paragraph(_inline(tokens[i + 1]), self.styles[f"h{level}"]))
                i += 3
            elif kind == "paragraph_open":
                out.append(Paragraph(_inline(tokens[i + 1]), self.styles[style_name]))
                i += 3
            elif kind in ("bullet_list_open", "ordered_list_open"):
                end = _matching_close(tokens, i)
                out.append(self._list(tokens[i : end + 1], ordered=kind == "ordered_list_open"))
                i = end + 1
            elif kind == "blockquote_open":
                end = _matching_close(tokens, i)
                out.extend(self.blocks(tokens[i + 1 : end], quote=True))
                i = end + 1
            elif kind in ("fence", "code_block"):
                out.append(Preformatted(_clip_lines(token.content), self.styles["code"]))
                i += 1
            elif kind == "hr":
                out.append(HRFlowable(width="100%", color=colors.HexColor("#cbd5e1"), spaceAfter=6))
                i += 1
            elif kind == "table_open":
                end = _matching_close(tokens, i)
                out.extend(self._table(tokens[i : end + 1]))
                out.append(Spacer(1, 6))
                i = end + 1
            elif kind == "html_block":
                out.append(Paragraph(_escape(token.content.strip()), self.styles[style_name]))
                i += 1
            else:
                i += 1
        return out

    def _list(self, tokens: Sequence[Token], *, ordered: bool) -> ListFlowable:
        items: list[ListItem] = []
        level = tokens[0].level + 1
        i = 1
        while i < len(tokens) - 1:
            token = tokens[i]
            if token.type == "list_item_open" and token.level == level:
                end = _matching_close(tokens, i)
                items.append(ListItem(self.blocks(tokens[i + 1 : end]), leftIndent=14))
                i = end + 1
            else:
                i += 1
        start = int(tokens[0].attrGet("start") or 1) if ordered else None
        return ListFlowable(
            items,  # type: ignore[arg-type]  # ListItem is a valid nested flowable
            bulletType="1" if ordered else "bullet",
            start=start if ordered else "•",
            bulletFontName=_FONT,
            bulletFontSize=10,
            leftIndent=14,
        )

    def _table(self, tokens: Sequence[Token]) -> list[Flowable]:
        rows: list[list[Paragraph]] = []
        header_rows = 0
        wide = False
        raw_rows: list[list[tuple[str, bool]]] = []
        current: list[tuple[str, bool]] | None = None
        in_head = False
        for index, token in enumerate(tokens):
            if token.type == "thead_open":
                in_head = True
            elif token.type == "thead_close":
                in_head = False
            elif token.type == "tr_open":
                current = []
            elif token.type == "tr_close" and current is not None:
                raw_rows.append(current)
                header_rows += 1 if in_head else 0
                current = None
            elif token.type in ("th_open", "td_open") and current is not None:
                current.append((_clip_cell(tokens[index + 1]), token.type == "th_open"))
        notes: list[str] = []
        body_rows = len(raw_rows) - header_rows
        allowed = max(min(MAX_TABLE_ROWS, self.table_rows_left), 0)
        if body_rows > allowed:
            raw_rows = raw_rows[: header_rows + allowed]
            notes.append(f"Table shortened: showing the first {allowed} of {body_rows} rows.")
        self.table_rows_left -= max(len(raw_rows) - header_rows, 0)
        if any(len(r) > MAX_TABLE_COLUMNS for r in raw_rows):
            raw_rows = [r[:MAX_TABLE_COLUMNS] for r in raw_rows]
            notes.append(f"Table shortened: showing only the first {MAX_TABLE_COLUMNS} columns.")
        columns = max((len(r) for r in raw_rows), default=0)
        wide = columns > _WIDE_TABLE_COLUMNS
        cell = self.styles["cell_small" if wide else "cell"]
        head = self.styles["head_small" if wide else "head"]
        for raw in raw_rows:
            rows.append(
                [Paragraph(text, head if is_head else cell) for text, is_head in raw]
                + [Paragraph("", cell)] * (columns - len(raw))
            )
        available = A4[0] - 2 * PAGE_MARGIN
        weights = [
            min(max((len(_plain(r[c][0])) for r in raw_rows if c < len(r)), default=4), 40)
            for c in range(columns)
        ]
        weights = [max(w, 4) for w in weights]
        total = sum(weights) or 1
        table = Table(
            rows or [[""]],
            colWidths=[available * w / total for w in weights] or None,
            repeatRows=header_rows or 0,
            hAlign="LEFT",
        )
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, max(header_rows - 1, 0)),
                        colors.HexColor("#f1f5f9"),
                    )
                    if header_rows
                    else ("BACKGROUND", (0, 0), (0, 0), colors.white),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 3),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        return [table, *(Paragraph(_escape(note), self.styles["quote"]) for note in notes)]


def _clip_lines(text: str) -> str:
    lines = text.rstrip("\n").split("\n")
    return "\n".join(
        line if len(line) <= MAX_CODE_LINE_CHARS else line[:MAX_CODE_LINE_CHARS] + "…"
        for line in lines
    )


def _plain(markup: str) -> str:
    out = []
    skipping = False
    for ch in markup:
        if ch == "<":
            skipping = True
        elif ch == ">":
            skipping = False
        elif not skipping:
            out.append(ch)
    return "".join(out)


@cache
def _parser() -> MarkdownIt:
    # "commonmark" has no raw-HTML handling beyond the html option; tables are a GFM extension.
    return MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table")


def markdown_to_flowables(markdown: str) -> list[Flowable]:
    """The reportlab flowables for *markdown* (exposed for tests and previews)."""
    return _Builder().blocks(_parser().parse(markdown))


def render_pdf(*, title: str, markdown: str) -> bytes:
    """A4 PDF of the Markdown with the title and page numbers in the footer."""
    if len(markdown) > MAX_MARKDOWN_CHARS:
        raise PdfTooLargeError("The report text is too large to export as a PDF")
    story = markdown_to_flowables(markdown) or [Spacer(1, 1)]
    footer_title = title[:80]

    def footer(canvas: Any, document: Any) -> None:
        canvas.saveState()
        canvas.setFont(_FONT, 8)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(PAGE_MARGIN, 10 * mm, footer_title)
        canvas.drawRightString(A4[0] - PAGE_MARGIN, 10 * mm, f"Page {document.page}")
        canvas.restoreState()

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=PAGE_MARGIN,
        rightMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN,
        bottomMargin=PAGE_MARGIN + 6 * mm,
        title=title[:200],
        author="Auxilium Manus",
    )
    try:
        document.build(story, onFirstPage=footer, onLaterPages=footer)
    except (
        Exception
    ) as exc:  # reportlab raises LayoutError, ValueError, ... for content it cannot place
        raise PdfRenderError("The report could not be laid out as a PDF") from exc
    return buffer.getvalue()
