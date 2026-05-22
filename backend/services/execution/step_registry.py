"""Registry mapping step type identifiers to async executor functions.

Each executor receives:
  config        — pluginConfig dict from the canvas node (step configuration)
  parent_outputs — dict of {node_id: output_dict} for upstream steps
  run           — the WorkflowRun ORM instance

It returns a JSON-serialisable dict that becomes the step's output.

To add a new step type:
  1. Implement an async executor function below.
  2. Register it in STEP_REGISTRY under the step's kind string (hyphen-separated).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from core.models.runs import WorkflowRun

logger = logging.getLogger(__name__)

StepExecutor = Callable[..., Awaitable[dict[str, Any]]]

_MOCK_DEVICES = [
    {
        "id": "device-mock-001",
        "name": "router-core-01",
        "platform": "cisco_ios",
        "ip": "10.0.0.1",
        "role": "core-router",
        "location": "dc-ams-01",
    },
    {
        "id": "device-mock-002",
        "name": "switch-access-02",
        "platform": "cisco_nxos",
        "ip": "10.0.0.2",
        "role": "access-switch",
        "location": "dc-ams-01",
    },
    {
        "id": "device-mock-003",
        "name": "firewall-edge-01",
        "platform": "paloalto_panos",
        "ip": "10.0.0.3",
        "role": "edge-firewall",
        "location": "dc-ams-01",
    },
]


async def _execute_get_nautobot_devices(
    *,
    config: dict[str, Any],
    parent_outputs: dict[str, Any],
    run: WorkflowRun,
) -> dict[str, Any]:
    source_id = config.get("nautobot_source_id", "<not configured>")
    device_filter = config.get("device_filter")

    logger.info(
        "[mock] get-nautobot-devices run_id=%s source_id=%s filter=%s",
        run.id,
        source_id,
        device_filter,
    )

    devices = run.device_ids or [d["id"] for d in _MOCK_DEVICES]
    mock_device_details = [d for d in _MOCK_DEVICES if d["id"] in devices] or _MOCK_DEVICES

    logger.info(
        "[mock] get-nautobot-devices returning %d devices run_id=%s",
        len(mock_device_details),
        run.id,
    )

    return {
        "devices": [d["id"] for d in mock_device_details],
        "device_details": mock_device_details,
        "source_id": source_id,
        "total": len(mock_device_details),
    }


async def _execute_get_nautobot_attributes(
    *,
    config: dict[str, Any],
    parent_outputs: dict[str, Any],
    run: WorkflowRun,
) -> dict[str, Any]:
    device_ids: list[str] = []
    for output in parent_outputs.values():
        if isinstance(output, dict) and "devices" in output:
            device_ids = output["devices"]
            break

    attributes = config.get("list_of_attributes", [])
    source_id = config.get("nautobot_source_id", "<not configured>")

    logger.info(
        "[mock] get-nautobot-attributes run_id=%s source_id=%s devices=%d attributes=%s",
        run.id,
        source_id,
        len(device_ids),
        attributes,
    )

    mock_attribute_data = {
        device_id: {
            "device_id": device_id,
            "attributes": {
                "interfaces": ["GigabitEthernet0/0", "GigabitEthernet0/1"],
                "vlans": [10, 20, 100],
                "bgp_neighbors": [],
                "os_version": "15.9(3)M",
                "serial": f"SN{device_id[-3:].upper()}123",
            },
        }
        for device_id in (device_ids or [d["id"] for d in _MOCK_DEVICES])
    }

    logger.info(
        "[mock] get-nautobot-attributes returning attributes for %d devices run_id=%s",
        len(mock_attribute_data),
        run.id,
    )

    return {
        "devices": device_ids,
        "source_id": source_id,
        "attributes_requested": attributes,
        "attribute_data": mock_attribute_data,
        "total": len(mock_attribute_data),
    }


STEP_REGISTRY: dict[str, StepExecutor] = {
    "get-nautobot-devices": _execute_get_nautobot_devices,
    "get-nautobot-attributes": _execute_get_nautobot_attributes,
}
