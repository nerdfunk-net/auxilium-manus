"""F-F (W14-08): every key a step's ``get_config()`` carries is declared in ``registry.yaml``.

The registry is what the Ask the Net tools, the workflow validation and the docs read; a key
the executor reads but the registry omits is invisible to them.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest
import yaml

REGISTRY = Path(__file__).resolve().parents[2] / "workflow_steps" / "registry.yaml"


def _plugins() -> list[dict[str, Any]]:
    return yaml.safe_load(REGISTRY.read_text())["plugins"]


def _declared(plugin: dict[str, Any]) -> set[str]:
    inputs = (plugin.get("metadata") or {}).get("configuration_input") or []
    return {item["name"] for item in inputs}


def _defaults(plugin: dict[str, Any]) -> dict[str, Any] | None:
    try:
        module = importlib.import_module(f"workflow_steps.{plugin['directory']}.config")
    except ModuleNotFoundError:
        return None
    return module.get_config()


@pytest.mark.parametrize("plugin", _plugins(), ids=lambda p: p["id"])
def test_every_default_key_is_declared(plugin: dict[str, Any]) -> None:
    defaults = _defaults(plugin)
    if defaults is None:
        pytest.skip("no config module")
    assert set(defaults) - _declared(plugin) == set()


@pytest.mark.parametrize(
    ("step_id", "key"),
    [
        ("get-catalyst-center-client-data", "dry_run"),
        ("filter-output", "source_command"),
        ("start-workflow", "bag_name"),
    ],
)
def test_the_keys_the_audit_found_are_declared(step_id: str, key: str) -> None:
    plugin = next(p for p in _plugins() if p["id"] == step_id)
    assert key in _declared(plugin)
