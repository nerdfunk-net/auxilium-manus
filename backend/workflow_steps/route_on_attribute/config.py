def get_config() -> dict:
    return {
        "attribute_path": "device.network_driver",
        "case_sensitive": False,
        "default_outcome": "unmatched",
        "routes": [
            {
                "outcome": "ios",
                "values": ["cisco_ios", "ios"],
            },
            {
                "outcome": "nxos",
                "values": ["cisco_nxos", "nxos"],
            },
        ],
    }
