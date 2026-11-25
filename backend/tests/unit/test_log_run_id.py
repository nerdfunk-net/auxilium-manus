"""W11-10: steps log the run's UUID, never the database integer ``run.id``."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from tests.unit._step_helpers import make_run
from workflow_steps.common.run_logging import log_run_id

_STEPS = Path(__file__).resolve().parents[2] / "workflow_steps"
_LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
# These pass ``run.id`` on purpose: it is a database foreign key (job statistics, notifications,
# report data, the parent run of a child run), not a log value.
_PERSISTED_RUN_ID = {
    "workflow_steps/collect_statistics/executor.py",
    "workflow_steps/notify/executor.py",
    "workflow_steps/notify_on_error/executor.py",
    "workflow_steps/store_for_report/executor.py",
}


def test_log_run_id_is_the_uuid_string_not_the_database_id() -> None:
    run = make_run(id=7, uuid="3f2c1a64-0000-4000-8000-000000000001")
    assert log_run_id(run) == "3f2c1a64-0000-4000-8000-000000000001"


def _integer_run_ids() -> list[str]:
    """``file:line`` of every ``run_id=run.id`` keyword argument (helpers only log it) and of every
    log call whose ``run_id=%s`` argument is ``run.id``, and of every
    ``run_id = run.id`` (the variable only feeds log lines)."""
    found: list[str] = []
    for path in sorted(_STEPS.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.keyword)
                and node.arg == "run_id"
                and ast.unparse(node.value) == "run.id"
                and str(path.relative_to(_STEPS.parent)) not in _PERSISTED_RUN_ID
            ):
                found.append(f"{path.relative_to(_STEPS.parent)}:{node.value.lineno}")
                continue
            if (
                isinstance(node, ast.Assign)
                and [ast.unparse(target) for target in node.targets] == ["run_id"]
                and ast.unparse(node.value) == "run.id"
            ):
                found.append(f"{path.relative_to(_STEPS.parent)}:{node.lineno}")
                continue
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _LOG_METHODS
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and "run_id=" in node.args[0].value
            ):
                continue
            fmt = node.args[0].value
            position = len(re.findall(r"%[sdr]", fmt[: fmt.index("run_id=")])) + 1
            if position < len(node.args) and ast.unparse(node.args[position]) == "run.id":
                found.append(f"{path.relative_to(_STEPS.parent)}:{node.lineno}")
    return found


def test_no_step_logs_the_integer_run_id() -> None:
    assert _integer_run_ids() == [], "log log_run_id(run) instead of run.id"
