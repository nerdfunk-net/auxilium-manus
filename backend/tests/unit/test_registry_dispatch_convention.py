"""Guard 10 (W10-15, W14-10): ``registry.yaml``, the dispatch table, the step packages and the
frontend loaders describe the same steps.

The vitest half (``frontend/src/lib/plugin-ui-registry.test.ts``) checks the loader convention
(step id == directory == ``<Pascal>Plugin``, no panel without a loader); this half ties the
loaders to the registry. ``test_registry_declares_config_keys.py`` checks that ``get_config()``
keys are declared; the last test here checks that every declared key is at least written in the
frontend (its panel or a shared block), so a new key is never invisible in the editor.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from services.execution.step_registry import STEP_REGISTRY

BACKEND = Path(__file__).resolve().parents[2]
STEPS = BACKEND / "workflow_steps"
FRONTEND_STEPS = BACKEND.parent / "frontend" / "src" / "components" / "features" / "workflow-steps"
LOADERS = BACKEND.parent / "frontend" / "src" / "lib" / "plugin-ui-registry.ts"
_LOADER = re.compile(r'"?([a-z0-9-]+)"?: \(\) => import\("@/components/features/workflow-steps/')

# Canvas decorations: in the registry for the palette, executed by the runner itself.
DECORATIONS = frozenset({"background", "funnel", "label", "step-group"})
# Registry ids without a config panel (two-sided: drop an entry once it gains a loader).
WITHOUT_PANEL = frozenset({"step-group"})


def _plugins() -> list[dict[str, Any]]:
    return yaml.safe_load((STEPS / "registry.yaml").read_text())["plugins"]


def _ids() -> list[str]:
    return [plugin["id"] for plugin in _plugins()]


def loader_ids(source: str) -> set[str]:
    return set(_LOADER.findall(source))


def test_registry_ids_are_unique() -> None:
    assert len(_ids()) == len(set(_ids()))


def test_every_registry_id_is_dispatched_or_a_decoration() -> None:
    ids = set(_ids())
    assert ids - DECORATIONS == set(STEP_REGISTRY)
    assert DECORATIONS <= ids
    assert DECORATIONS.isdisjoint(STEP_REGISTRY)


def test_every_dispatched_step_has_an_executor() -> None:
    missing = [
        p["id"]
        for p in _plugins()
        if p["id"] not in DECORATIONS and not (STEPS / p["directory"] / "executor.py").is_file()
    ]
    assert missing == []


def test_every_step_package_is_in_the_registry() -> None:
    directories = {p["directory"] for p in _plugins()}
    packages = {path.parent.name for path in STEPS.glob("*/executor.py")}
    assert packages - directories == set()


def test_every_frontend_loader_is_a_registry_id_and_every_id_has_one() -> None:
    loaders = loader_ids(LOADERS.read_text())
    ids = set(_ids())
    assert loaders - ids == set(), "loader for an id the registry does not know"
    assert ids - loaders == WITHOUT_PANEL, "update WITHOUT_PANEL (it may only shrink)"


def _frontend_text(directory: Path) -> str:
    if not directory.is_dir():
        return ""
    return "".join(
        path.read_text() for path in sorted(directory.rglob("*.ts*")) if ".test." not in path.name
    )


@pytest.mark.parametrize("plugin", _plugins(), ids=lambda p: p["id"])
def test_every_declared_key_is_written_in_the_frontend(plugin: dict[str, Any]) -> None:
    keys = [i["name"] for i in (plugin.get("metadata") or {}).get("configuration_input") or []]
    text = _frontend_text(FRONTEND_STEPS / plugin["id"]) + _frontend_text(FRONTEND_STEPS / "shared")
    unwritten = [key for key in keys if not re.search(rf"\b{re.escape(key)}\b", text)]
    assert unwritten == [], "a registry key no panel or shared block reads or writes"


def test_the_loader_pattern_reads_both_spellings() -> None:
    source = (
        'const R = {\n  "run-command": () => import("@/components/features/workflow-steps/'
        'run-command").then((m) => m.RunCommandPlugin),\n  label: () => import('
        '"@/components/features/workflow-steps/label").then((m) => m.LabelPlugin),\n}'
    )
    assert loader_ids(source) == {"run-command", "label"}
