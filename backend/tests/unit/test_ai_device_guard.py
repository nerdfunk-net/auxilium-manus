"""Only ``device_access.py`` may reach a device from the assistant (doc/AI_TOOL_CHAIN.md §13.5).

Same idea as ``scripts/check_text_sql.py``: a structural guard, so a new tool cannot open a Netmiko
session, call a workflow step executor or start a run by importing it directly.
"""

from __future__ import annotations

import ast
from pathlib import Path

ASSISTANT = Path(__file__).resolve().parents[2] / "services" / "ai_assistant"
ALLOWED = {"device_access.py"}
FORBIDDEN_MODULES = (
    "netmiko",
    "paramiko",
    "services.network.netmiko",
    "services.execution.step_registry",
    "services.execution.step_runner",
    "services.execution.run_lifecycle_service",
    "services.execution.schedule_fire",
    "workflow_steps",
    "hatchet",
)
FORBIDDEN_NAMES = {"NetmikoService", "NetmikoPreviewService", "DeviceSessionPool", "ConnectHandler"}


def _forbidden(module: str) -> bool:
    return any(module == m or module.startswith(f"{m}.") for m in FORBIDDEN_MODULES)


def violations_in(source: str) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.extend(a.name for a in node.names if _forbidden(a.name))
        elif isinstance(node, ast.ImportFrom) and node.module:
            if _forbidden(node.module):
                found.append(node.module)
            found.extend(a.name for a in node.names if a.name in FORBIDDEN_NAMES)
    return found


def test_the_guard_catches_each_way_in() -> None:
    assert violations_in("import netmiko") == ["netmiko"]
    assert violations_in("from netmiko import ConnectHandler") == ["netmiko", "ConnectHandler"]
    assert violations_in("from services.network.netmiko.service import NetmikoService") == [
        "services.network.netmiko.service",
        "NetmikoService",
    ]
    assert violations_in("from workflow_steps.run_command import executor") == [
        "workflow_steps.run_command"
    ]
    assert violations_in("from services.execution.step_registry import STEP_REGISTRY") == [
        "services.execution.step_registry"
    ]
    assert violations_in("import paramiko") == ["paramiko"]
    assert violations_in("from hatchet_sdk import Hatchet") == []  # not our hatchet package
    assert violations_in("from hatchet.workflows import x") == ["hatchet.workflows"]
    assert violations_in("from services.execution.run_service import RunService") == []  # reads
    assert violations_in("from services.execution.step_runner import StepRunner")
    assert violations_in("from netmiko_extras import x") == []  # a prefix is not a package
    assert violations_in("import json\nfrom typing import Any") == []


def test_only_the_device_access_module_reaches_a_device() -> None:
    offenders: dict[str, list[str]] = {}
    for path in sorted(ASSISTANT.rglob("*.py")):
        if path.name in ALLOWED and path.parent == ASSISTANT:
            continue
        hits = violations_in(path.read_text(encoding="utf-8"))
        if hits:
            offenders[str(path.relative_to(ASSISTANT))] = hits

    assert offenders == {}


def test_the_allowed_module_exists_and_is_where_the_netmiko_import_lives() -> None:
    hits = violations_in((ASSISTANT / "device_access.py").read_text(encoding="utf-8"))

    assert "NetmikoPreviewService" in hits
