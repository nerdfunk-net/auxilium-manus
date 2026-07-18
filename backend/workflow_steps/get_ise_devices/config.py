from __future__ import annotations


def get_config() -> dict:
    return {
        "ise_source_id": "",
        "query_mode": "name",
        "device_names": [],
        "cidr": "",
        "group_name": "",
        "resolve_to_devices": False,
        "fan_out": {
            "enabled": False,
            "mode": "per_device",
            "chunk_size": 1,
            "max_concurrency": 0,
        },
    }
