from __future__ import annotations


def get_config() -> dict:
    return {
        "nautobot_source_id": "",
        "ip_address": "",
        "namespace": "Global",
        "status": "Active",
        "create_prefix": False,
        "default_mask_length": None,
        "description": "",
        "dns_name": "",
        "result_attribute": "",
        "interface_name": "",
        "set_primary": False,
    }
