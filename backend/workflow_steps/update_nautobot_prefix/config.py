from __future__ import annotations


def get_config() -> dict:
    return {
        "nautobot_source_id": "",
        "prefix_id": "",
        "prefix": "",
        "namespace": "",
        "description": "",
        "status": "",
        "role": "",
        "locations": "",
        "locations_mode": "replace",
        "prefixes_from_interfaces": False,
        "dry_run": False,
    }
