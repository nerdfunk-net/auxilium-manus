"""Every repository path mentioned in the operator-facing security documents must exist.

A dangling reference (a report that is not shipped, a renamed guide) is exactly what an operator
following SECURITY.md or the Docker guides would trip over.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
DOCS = [
    REPO / "SECURITY.md",
    REPO / "README.md",
    REPO / "INSTALL.md",
    *sorted((REPO / "docker").glob("*.md")),
]
# `doc/...` paths, possibly with a trailing anchor, inside backticks or markdown links.
_PATH = re.compile(r"(?<![\w/.-])(doc/[A-Za-z0-9_./-]+?\.(?:md|yaml|yml))(?=[)`#\s,:;.]|$)")


@pytest.mark.parametrize("document", DOCS, ids=lambda p: str(p.relative_to(REPO)))
def test_referenced_doc_paths_exist(document: Path) -> None:
    missing = sorted(
        {
            path
            for path in _PATH.findall(document.read_text(encoding="utf-8"))
            if not (REPO / path).exists()
        }
    )
    assert not missing, f"{document.name} references missing files: {missing}"
