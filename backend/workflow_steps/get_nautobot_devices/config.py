from __future__ import annotations


def get_config() -> dict:
    return {
        "nautobot_source_id": "",
        "inventory_id": None,
        "inventory_name": "",
        "device_filter": {"logic": "AND", "negate": False, "id": "root", "items": []},
        "fan_out": {
            "enabled": False,
            "mode": "per_device",
            "chunk_size": 1,
            "max_concurrency": 0,
        },
    }
