"""The ``redundancy_groups`` setting shared by the steps that write interfaces to Nautobot.

``{"enabled": bool, "name_pattern": "hsrp-{next}", "status": "Active"}``. Off (the default) means
no group is written. See ``services/nautobot/devices/interface_workflow/redundancy_ops.py``.
"""

from __future__ import annotations

from typing import Any

from services.nautobot.devices.interface_workflow.redundancy_naming import (
    DEFAULT_NAME_PATTERN,
    validate_name_pattern,
)
from workflow_steps.common.step_flags import parse_bool_flag

DEFAULT_REDUNDANCY_STATUS = "Active"


def default_redundancy_groups() -> dict[str, Any]:
    """The setting as a step's ``get_config()`` lists it."""
    return {
        "enabled": False,
        "name_pattern": DEFAULT_NAME_PATTERN,
        "status": DEFAULT_REDUNDANCY_STATUS,
    }


def parse_redundancy_groups(
    config: dict[str, Any], *, step_id: str, interfaces_source: str
) -> tuple[str | None, str]:
    """``(name pattern or None when off, status)``; ``ValueError`` for an unusable setting."""
    raw = config.get("redundancy_groups")
    if raw is None:
        return None, DEFAULT_REDUNDANCY_STATUS
    if not isinstance(raw, dict):
        raise ValueError(f"{step_id}: redundancy_groups must be an object")
    if not parse_bool_flag(raw, "enabled", default=False):
        return None, DEFAULT_REDUNDANCY_STATUS
    if interfaces_source != "nautobot_origin":
        raise ValueError(
            f"{step_id}: redundancy_groups needs interfaces_source 'nautobot_origin' "
            "(the groups are read from the interfaces in the Nautobot attribute bag)"
        )
    pattern = str(raw.get("name_pattern") or DEFAULT_NAME_PATTERN).strip()
    problem = validate_name_pattern(pattern)
    if problem:
        raise ValueError(f"{step_id}: redundancy_groups.name_pattern: {problem}")
    status = str(raw.get("status") or DEFAULT_REDUNDANCY_STATUS).strip()
    return pattern, status
