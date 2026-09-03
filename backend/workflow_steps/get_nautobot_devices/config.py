from __future__ import annotations


def get_config() -> dict:
    return {
        "nautobot_source_id": "",
        # "fixed" → resolve the canvas device_filter / device_ids below.
        # "run_param" → resolve the inventory id held in the run parameter named
        # by inventory_param (a workflow static_attribute of type "reference",
        # ref_kind "inventory"), scoped to the triggering user.
        "inventory_source": "fixed",
        "inventory_param": "",
        "inventory_id": None,
        "inventory_name": "",
        "inventory_type": "filter",
        "device_filter": {"logic": "AND", "negate": False, "id": "root", "items": []},
        "device_ids": [],
        "fan_out": {
            "enabled": False,
            "mode": "per_device",
            "chunk_size": 1,
            "max_concurrency": 0,
        },
    }
