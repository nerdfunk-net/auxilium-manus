"""Unit tests for ai_template_apply.py's pure, DB-free patch loading.

The rest of the script (DB session, TemplatesService, RBAC-seeded fixtures) is
deliberately not unit-tested here -- see doc/ai_collaboration/PROCESS.md, which
documents the same precedent for ai_workflow_apply.py: verified manually against
the dev DB, not via an in-memory-SQLite main() test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ai_template_apply import _load_patch


def _write(tmp_path: Path, content: str) -> Path:
    patch_file = tmp_path / "patch.json"
    patch_file.write_text(content)
    return patch_file


def test_load_patch_round_trips_a_valid_object(tmp_path: Path) -> None:
    patch_file = _write(tmp_path, json.dumps({"name": "tpl", "content": "hi"}))

    assert _load_patch(patch_file) == {"name": "tpl", "content": "hi"}


def test_load_patch_rejects_non_dict_json(tmp_path: Path) -> None:
    patch_file = _write(tmp_path, json.dumps(["not", "a", "dict"]))

    with pytest.raises(ValueError, match="JSON object"):
        _load_patch(patch_file)


def test_load_patch_rejects_unknown_field(tmp_path: Path) -> None:
    patch_file = _write(tmp_path, json.dumps({"name": "tpl", "bogus_field": 1}))

    with pytest.raises(ValueError, match="bogus_field"):
        _load_patch(patch_file)


def test_load_patch_rejects_malformed_json(tmp_path: Path) -> None:
    patch_file = _write(tmp_path, "{not valid json")

    with pytest.raises(json.JSONDecodeError):
        _load_patch(patch_file)
