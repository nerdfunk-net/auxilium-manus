"""Default configuration for the config-to-attributes step."""


def get_config() -> dict:
    return {
        "config_source": "running",
        "parsed_key": "cisco_config",
        "attributes": ["layer3_interfaces"],
    }
