def get_config() -> dict:
    return {
        "connection_id": None,
        "path_template": "network/{device.name}/tacacs",
        "field": "key",
        "destination_path": "tacacs.shared_secret",
        "charset": "hex",
        "length": 32,
        "strict_templates": True,
    }
