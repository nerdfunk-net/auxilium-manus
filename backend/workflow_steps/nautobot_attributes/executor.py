"""Executor for the get-nautobot-attributes step."""

from __future__ import annotations

import logging
from typing import Any

from core.models.runs import WorkflowRun

logger = logging.getLogger(__name__)


async def execute(
    *,
    config: dict[str, Any],
    parent_outputs: dict[str, Any],
    run: WorkflowRun,
) -> dict[str, Any]:
    device_ids: list[str] = []
    for output in parent_outputs.values():
        if isinstance(output, dict) and "device_ids" in output:
            device_ids = output["device_ids"]
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
        for device_id in device_ids
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
