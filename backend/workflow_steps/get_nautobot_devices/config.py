from __future__ import annotations


def get_config() -> dict:
    return {
        "inventory_source": {"url": "", "token": ""},
        "device_filter": {"logic": "AND", "negate": False, "id": "root", "items": []},
    }
