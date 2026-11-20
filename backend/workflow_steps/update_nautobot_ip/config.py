from __future__ import annotations


def get_config() -> dict:
    return {
        "nautobot_source_id": "",
        "ip_id": "",
        "namespace": "",
        "type": "",
        "role": "",
        "status": "",
        "dns_name": "",
        "description": "",
        "ips_from_interfaces": False,
        "ip_version": "",
        "dry_run": False,
    }
