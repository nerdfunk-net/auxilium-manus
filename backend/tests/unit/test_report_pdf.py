"""Markdown -> PDF for report snapshots (reportlab, no system libraries)."""

from __future__ import annotations

import re

from reportlab.platypus import ListFlowable, Paragraph, Preformatted, Table

from services.reports.pdf_renderer import markdown_to_flowables, render_pdf

SAMPLE = """\
# Fleet

All **sites** and _devices_ with `code` & <tags>.

## Per site

| location | devices |
| --- | --- |
| dc1 | 2 |
| dc2 | 1 |

- first
- second

1. one
2. two

> a quote

```
show version
  line two
```

---

[docs](https://example.com) and ![alt text](https://evil.example/x.png)
"""


def _texts(flowables) -> list[str]:
    out: list[str] = []
    for f in flowables:
        if isinstance(f, ListFlowable):
            for item in f._flowables:
                out.extend(_texts(item._flowables))
        elif isinstance(f, Paragraph):
            out.append(re.sub(r"<[^>]+>", "", f.text))
        elif isinstance(f, Preformatted):
            out.append("\n".join(f.lines))
    return out


def test_headings_paragraphs_lists_and_code_become_flowables() -> None:
    texts = _texts(markdown_to_flowables(SAMPLE))

    assert texts[0] == "Fleet"
    assert any("All sites and devices with code &amp; &lt;tags&gt;." in t for t in texts)
    assert "Per site" in texts
    assert "first" in texts and "second" in texts and "one" in texts and "two" in texts
    lists = [f for f in markdown_to_flowables(SAMPLE) if isinstance(f, ListFlowable)]
    assert len(lists) == 2
    assert any("a quote" in t for t in texts)
    assert any("show version\n  line two" == t for t in texts)


def test_a_table_keeps_header_and_rows() -> None:
    tables = [f for f in markdown_to_flowables(SAMPLE) if isinstance(f, Table)]

    assert len(tables) == 1
    rows = [[re.sub(r"<[^>]+>", "", c.text) for c in row] for row in tables[0]._cellvalues]
    assert rows == [["location", "devices"], ["dc1", "2"], ["dc2", "1"]]


def test_inline_markup_is_escaped_and_images_are_not_fetched() -> None:
    joined = " ".join(_texts(markdown_to_flowables(SAMPLE)))

    assert "&lt;tags&gt;" in joined  # no raw markup reaches reportlab's mini-HTML
    assert "alt text" in joined and "evil.example/x.png" not in joined
    assert "docs" in joined


def test_raw_html_in_the_markdown_is_shown_as_text_not_interpreted() -> None:
    texts = _texts(markdown_to_flowables("<b onclick=x>bold</b> <img src=x>"))

    joined = " ".join(texts)
    assert "<b" not in re.sub(r"&lt;|&gt;", "", joined) or "&lt;b" in joined


def test_render_pdf_returns_a_valid_pdf_with_a_page_per_overflow() -> None:
    short = render_pdf(title="Fleet", markdown=SAMPLE)
    long = render_pdf(title="Fleet", markdown="\n\n".join(f"Paragraph {i}" for i in range(400)))

    for pdf in (short, long):
        assert pdf.startswith(b"%PDF-") and pdf.rstrip().endswith(b"%%EOF")
    pages_short = len(re.findall(rb"/Type /Page\b", short))
    pages_long = len(re.findall(rb"/Type /Page\b", long))
    assert pages_short == 1 and pages_long > 1


def test_non_ascii_text_and_wide_tables_do_not_break_rendering() -> None:
    header = "| " + " | ".join(f"c{i}" for i in range(14)) + " |"
    divider = "| " + " | ".join("---" for _ in range(14)) + " |"
    row = "| " + " | ".join("Zürich–Straße €" for _ in range(14)) + " |"

    pdf = render_pdf(title="Übersicht", markdown=f"# Größe\n\n{header}\n{divider}\n{row}\n")

    assert pdf.startswith(b"%PDF-")


def test_empty_markdown_still_makes_a_pdf() -> None:
    assert render_pdf(title="Empty", markdown="").startswith(b"%PDF-")


def test_markdown_size_is_capped() -> None:
    import pytest

    from services.reports.pdf_renderer import MAX_MARKDOWN_CHARS, PdfTooLargeError

    with pytest.raises(PdfTooLargeError):
        render_pdf(title="x", markdown="a" * (MAX_MARKDOWN_CHARS + 1))


# -- limits: untrusted data must not make rendering slow or crash ---------------------------------


def _table(rows: int, cols: int = 3, cell: str = "x") -> str:
    header = "| " + " | ".join(f"c{i}" for i in range(cols)) + " |"
    divider = "| " + " | ".join("---" for _ in range(cols)) + " |"
    body = ["| " + " | ".join(cell for _ in range(cols)) + " |" for _ in range(rows)]
    return "\n".join([header, divider, *body])


def test_tables_are_shortened_with_a_notice() -> None:
    from services.reports.pdf_renderer import MAX_TABLE_ROWS

    flowables = markdown_to_flowables(_table(MAX_TABLE_ROWS + 50))

    tables = [f for f in flowables if isinstance(f, Table)]
    assert len(tables[0]._cellvalues) == MAX_TABLE_ROWS + 1  # header + capped rows
    assert any("shortened" in t and str(MAX_TABLE_ROWS + 50) in t for t in _texts(flowables))


def test_many_tables_share_one_row_budget() -> None:
    from services.reports.pdf_renderer import MAX_TOTAL_TABLE_ROWS

    markdown = "\n\n".join(_table(1500) for _ in range(6))

    tables = [f for f in markdown_to_flowables(markdown) if isinstance(f, Table)]

    assert sum(len(t._cellvalues) - 1 for t in tables) <= MAX_TOTAL_TABLE_ROWS


def test_wide_tables_and_long_cells_are_clipped_instead_of_crashing() -> None:
    from services.reports.pdf_renderer import MAX_CELL_CHARS, MAX_TABLE_COLUMNS

    wide = render_pdf(title="w", markdown=_table(3, cols=500))
    giant = render_pdf(title="g", markdown=_table(2, cols=2, cell="A" * 200_000))

    assert wide.startswith(b"%PDF-") and giant.startswith(b"%PDF-")
    tables = [f for f in markdown_to_flowables(_table(2, cols=500)) if isinstance(f, Table)]
    assert len(tables[0]._cellvalues[0]) == MAX_TABLE_COLUMNS
    long_cell = [f for f in markdown_to_flowables(_table(1, 1, "A" * 9000)) if isinstance(f, Table)]
    text = re.sub(r"<[^>]+>", "", long_cell[0]._cellvalues[1][0].text)
    assert len(text) <= MAX_CELL_CHARS + 1 and text.endswith("…")


def test_a_very_long_code_line_does_not_break_rendering() -> None:
    pdf = render_pdf(title="c", markdown="```\n" + "x" * 300_000 + "\n```\n")

    assert pdf.startswith(b"%PDF-")


def test_a_render_failure_becomes_a_pdf_error(monkeypatch) -> None:
    import pytest

    from services.reports import pdf_renderer

    def boom(self, *a, **k):
        raise RuntimeError("layout exploded")

    monkeypatch.setattr(pdf_renderer.SimpleDocTemplate, "build", boom)

    with pytest.raises(pdf_renderer.PdfRenderError):
        render_pdf(title="x", markdown="# hi")
