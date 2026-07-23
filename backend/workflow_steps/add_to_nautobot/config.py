"""Default configuration for the add-to-nautobot step."""


def get_config() -> dict:
    return {
        "nautobot_source_id": "",
        "device_fields": {
            "name": {"enabled": True, "value": "{parsed.cisco_config.hostname}"},
            "role": {"enabled": True, "value": "{nautobot.origin}"},
            "status": {"enabled": True, "value": "{nautobot.origin | default('Active')}"},
            "location": {"enabled": True, "value": "{nautobot.origin}"},
            "device_type": {"enabled": True, "value": "{nautobot.origin}"},
            "platform": {"enabled": True, "value": "{nautobot.origin}"},
            "software_version": {"enabled": True, "value": "{nautobot.origin}"},
            "serial": {"enabled": True, "value": "{nautobot.origin}"},
            "asset_tag": {"enabled": True, "value": "{nautobot.origin}"},
            "tags": {"enabled": True, "value": "{nautobot.origin}"},
            "custom_fields": {},
        },
        "custom_fields_source": "manual",
        "interfaces": [],
        "interfaces_source": "manual",
        "add_prefix": True,
        "default_prefix_length": "/24",
        "virtual_chassis": {"mode": "none", "id": "", "name": ""},
        "dry_run": False,
    }
