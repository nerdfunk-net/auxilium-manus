from __future__ import annotations


def get_config() -> dict:
    return {
        "git_source_id": "",
        "filename_pattern": "*.yaml",
        "device_mapping": {},
        "fan_out": {
            "enabled": False,
            "mode": "per_device",
            "chunk_size": 1,
            "max_concurrency": 0,
        },
    }
