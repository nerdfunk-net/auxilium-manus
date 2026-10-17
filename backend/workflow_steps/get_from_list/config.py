from __future__ import annotations


def get_config() -> dict:
    return {
        "devices": [{"name": "", "ip_address": ""}],
        "fan_out": {
            "enabled": False,
            "mode": "per_device",
            "chunk_size": 1,
            "max_concurrency": 0,
        },
    }
