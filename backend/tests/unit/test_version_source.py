"""The release version lives in one place per toolchain and the two must agree.

``core/version.py`` is the backend's source (FastAPI reads it); ``frontend/package.json`` is the
frontend's, because npm needs it there. Bump both together (see CONTRIBUTING.md, "Releases").
"""

from __future__ import annotations

import json
from pathlib import Path

from core.version import __version__

REPO = Path(__file__).resolve().parents[3]


def test_frontend_and_backend_versions_agree() -> None:
    package = json.loads((REPO / "frontend" / "package.json").read_text())
    assert package["version"] == __version__


def test_the_api_reports_the_backend_version() -> None:
    from main import app

    assert app.version == __version__


def test_changelog_has_an_entry_for_the_current_version() -> None:
    changelog = (REPO / "CHANGELOG.md").read_text()
    assert f"## [{__version__}]" in changelog
