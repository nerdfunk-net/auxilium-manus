from __future__ import annotations


def get_config() -> dict:
    return {
        "ise_source_id": "",
        "priority": [
            {"type": "name_exact_32", "enabled": True},
            {"type": "name_any", "enabled": True},
            {"type": "location_group", "enabled": True},
            {"type": "ip_prefix_scan", "enabled": True},
            {"type": "ip_range_scan", "enabled": True},
        ],
        "location_group_prefix": "All Locations",
    }
