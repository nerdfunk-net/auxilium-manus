#!/usr/bin/env python3
"""Guard 11 (W13 Q4): branch coverage of ``workflow_steps`` may only rise.

Reads the ``.coverage`` data file the pytest run left behind (``branch = true`` in
``pyproject.toml`` makes it record branches), so it needs no second test run::

    cd backend && python -m pytest && python scripts/check_branch_coverage.py

Two-sided like the AST ratchets: exit ``1`` when the branch coverage of ``workflow_steps`` is
below ``BRANCH_FLOOR`` (a regression), and also when it is ``RAISE_MARGIN`` points or more above
it (raise the floor to the new value, rounded down to one decimal).
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

# percent; 90.0 at the introduction (2026-11-26, measured 90.50), raised at 91.04 (2026-11-27)
BRANCH_FLOOR = 91.0
RAISE_MARGIN = 1.0
INCLUDE = "workflow_steps/*"


def branch_percent(files: Mapping[str, Mapping[str, Any]]) -> float:
    """Branch coverage in percent over the *files* of a coverage JSON report."""
    covered = sum(entry["summary"]["covered_branches"] for entry in files.values())
    total = sum(entry["summary"]["num_branches"] for entry in files.values())
    if total == 0:
        raise ValueError("no branch data: is branch = true set under [tool.coverage.run]?")
    return 100.0 * covered / total


def verdict(actual: float, floor: float = BRANCH_FLOOR) -> str | None:
    """``None`` when *actual* is within the ratchet window, else the reason it fails."""
    if actual < floor:
        return f"workflow_steps branch coverage {actual:.2f} % is below the floor {floor:.1f} %"
    if actual >= floor + RAISE_MARGIN:
        return (
            f"workflow_steps branch coverage {actual:.2f} % is {RAISE_MARGIN:.0f} point(s) or more "
            f"above the floor {floor:.1f} %: raise BRANCH_FLOOR in scripts/check_branch_coverage.py"
        )
    return None


def _report(data_file: Path) -> dict[str, Any]:
    import coverage

    cov = coverage.Coverage(data_file=str(data_file))
    cov.load()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "coverage.json"
        cov.json_report(include=[INCLUDE], outfile=str(out))
        return json.loads(out.read_text())


def main(argv: list[str]) -> int:
    data_file = Path(argv[0]) if argv else Path(__file__).resolve().parents[1] / ".coverage"
    if not data_file.is_file():
        print(f"no coverage data at {data_file}: run python -m pytest first", file=sys.stderr)
        return 1
    actual = branch_percent(_report(data_file)["files"])
    problem = verdict(actual)
    if problem:
        print(problem, file=sys.stderr)
        return 1
    print(f"workflow_steps branch coverage {actual:.2f} % (floor {BRANCH_FLOOR:.1f} %)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
