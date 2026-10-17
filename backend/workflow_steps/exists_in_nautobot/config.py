from __future__ import annotations


def get_config() -> dict:
    return {
        "nautobot_source_id": "",
        "strategy": "name",
        "ip_address": "{device.primary_ip4}",
        "case_insensitive_lookup": False,
    }
