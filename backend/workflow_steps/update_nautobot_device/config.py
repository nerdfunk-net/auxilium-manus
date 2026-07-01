"""Default configuration for the update-nautobot-device step."""


def get_config() -> dict:
    return {
        "nautobot_source_id": "",
        "device_identifier": {
            "mode": "from_context",
        },
        "update_fields": {},
        "interfaces": [],
        "add_prefix": True,
        "default_prefix_length": "/24",
        "sync_interfaces": False,
    }
