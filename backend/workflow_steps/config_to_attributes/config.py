"""Default configuration for the config-to-attributes step."""


def get_config() -> dict:
    return {
        "source_format": "cisco_config_parser",
        "config_source": "running",
        "parsed_key": "cisco_config",
        "attributes": ["interfaces"],
        "update_primary_ipv4": False,
        "primary_ipv4_priority": [
            "management_interface",
            "loopback_highest",
            "loopback_lowest",
            "custom_interface",
        ],
        "primary_ipv4_custom_pattern": "",
    }
