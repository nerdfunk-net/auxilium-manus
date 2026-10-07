from __future__ import annotations


def get_config() -> dict:
    return {
        "git_repository_id": None,
        "filename_pattern": "*.yaml",
        "directory": "",
        "file_format": "yaml",
        "csv_delimiter": ";",
        "csv_multiline": False,
        "device_mapping": [],
        "fan_out": {
            "enabled": False,
            "mode": "per_device",
            "chunk_size": 1,
            "max_concurrency": 0,
        },
    }
