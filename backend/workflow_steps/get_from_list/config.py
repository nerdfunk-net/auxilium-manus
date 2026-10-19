from __future__ import annotations

from workflow_steps.common.device_list import DEFAULT_NETWORK_DRIVER


def get_config() -> dict:
    return {
        "devices": [{"name": "", "ip_address": "", "network_driver": DEFAULT_NETWORK_DRIVER}],
        "fan_out": {
            "enabled": False,
            "mode": "per_device",
            "chunk_size": 1,
            "max_concurrency": 0,
        },
    }
