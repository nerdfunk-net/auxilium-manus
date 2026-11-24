"""Guard 6: the import boundaries of ``workflow_steps`` (P-Y).

(a) ``common/`` imports no step; (b) no step imports another step (shared code lives in
``common/`` or ``services/``); (c) a step imports a repository only at the documented sites below;
(d) only a short list of modules outside ``workflow_steps`` import it.
"""

from __future__ import annotations

import ast
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]
_STEPS = _BACKEND / "workflow_steps"

# (c) The repository imports a step may hold, each with the reason it is accepted. A new entry needs
# a decision; behind a service is the default (``doc/claude/backend.md``).
_REPOSITORY_ALLOW_LIST: dict[str, set[str]] = {
    "batfish_init_snapshot/executor.py": {"repositories.run_repository"},
    "collect_statistics/executor.py": {"repositories.job_statistics_repository"},
    "common/notification_context.py": {"repositories.workflow_repository"},
    "contact_the_ai/executor.py": {"repositories.user_repository"},
    "from_change_request/executor.py": {"repositories.change_request_repository"},
    "get_from_user/inventory_reference.py": {"repositories.user_repository"},
    "get_nautobot_devices/executor.py": {"repositories.user_repository"},
    "notify/executor.py": {"repositories.notification_repository"},
    "notify_on_error/executor.py": {"repositories.notification_repository"},
    "start_workflow/executor.py": {"repositories.run_repository"},
}

# (d) Modules outside workflow_steps/ (and tests/) that may import it.
_EXTERNAL_IMPORTERS = {
    "services/execution/step_registry.py",
    "scripts/ai_inventory_filter.py",
    "routers/workflow_crypto_attribute.py",
}


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def _step_of(module: str) -> str | None:
    parts = module.split(".")
    return parts[1] if parts[0] == "workflow_steps" and len(parts) > 1 else None


def _python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def test_no_step_imports_another_step_and_common_imports_no_step() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _python_files(_STEPS):
        relative = path.relative_to(_STEPS)
        own = relative.parts[0]
        if len(relative.parts) == 1:  # registry glue next to the packages
            continue
        wrong = sorted(
            {
                module
                for module in _imports(path)
                if (step := _step_of(module)) is not None
                and step != own
                and step != "common"
                and step not in {"registry"}
                and (_STEPS / step).is_dir()
            }
        )
        if wrong:
            offenders[str(relative)] = wrong
    assert offenders == {}, "move shared code to workflow_steps/common or services/"


def test_repository_imports_are_the_documented_ones() -> None:
    found: dict[str, set[str]] = {}
    for path in _python_files(_STEPS):
        repositories = {
            module
            for module in _imports(path)
            if module.startswith("repositories.") and module.count(".") == 1
        }
        if repositories:
            found[str(path.relative_to(_STEPS))] = repositories
    assert found == _REPOSITORY_ALLOW_LIST


def test_only_the_documented_modules_outside_the_steps_import_them() -> None:
    importers: set[str] = set()
    for path in _python_files(_BACKEND):
        relative = path.relative_to(_BACKEND)
        if relative.parts[0] in {"workflow_steps", "tests", ".venv", "build"}:
            continue
        if any(_step_of(m) is not None or m == "workflow_steps" for m in _imports(path)):
            importers.add(str(relative))
    assert importers == _EXTERNAL_IMPORTERS
