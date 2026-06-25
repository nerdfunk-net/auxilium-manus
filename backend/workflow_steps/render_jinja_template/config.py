def get_config() -> dict:
    return {
        "output_key": "device_config",
        "template": (
            "! Generated configuration for {{ device.name }}\n"
            "hostname {{ device.hostname }}\n"
        ),
        "editor_nautobot_source_id": "",
        "editor_list_of_attributes": [
            "interfaces",
            "config_context",
            "tags",
        ],
        "editor_sample_device_name": "",
    }
