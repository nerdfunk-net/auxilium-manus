"""``scripts/check_playbooks.py``: operators validate playbook files before restarting."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import check_playbooks  # noqa: E402

GOOD = (
    '---\nname: site\ntitle: Site\nwhen: "a site"\ntools: [get_routes]\nscope: read-only\n---\n'
    "## Steps\n1. `get_routes` for the destination.\n"
)


def test_shipped_playbooks_pass(tmp_path: Path, capsys) -> None:
    assert check_playbooks.main(["--dir", str(tmp_path / "none")]) == 0

    assert "target-unreachable" in capsys.readouterr().out


def test_a_valid_local_directory_passes_and_is_listed(tmp_path: Path, capsys) -> None:
    (tmp_path / "site.md").write_text(GOOD, encoding="utf-8")

    assert check_playbooks.main(["--dir", str(tmp_path)]) == 0

    out = capsys.readouterr().out
    assert "site" in out
    assert "local" in out


def test_an_invalid_local_file_fails_with_its_name_and_reason(tmp_path: Path, capsys) -> None:
    (tmp_path / "site.md").write_text(GOOD.replace("get_routes]", "get_nothing]"), encoding="utf-8")

    assert check_playbooks.main(["--dir", str(tmp_path)]) == 1

    out = capsys.readouterr().out
    assert "site.md" in out
    assert "get_nothing" in out


def test_unknown_arguments_are_refused() -> None:
    with pytest.raises(SystemExit):
        check_playbooks.main(["--nope"])


def test_a_local_class_a_playbook_is_called_out(tmp_path: Path, capsys) -> None:
    (tmp_path / "site.md").write_text(
        GOOD.replace("---\n## Steps", "data_class: A\n---\n## Steps"), encoding="utf-8"
    )

    assert check_playbooks.main(["--dir", str(tmp_path)]) == 0

    assert "every user" in capsys.readouterr().out
