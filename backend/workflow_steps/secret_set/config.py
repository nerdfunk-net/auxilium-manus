def get_config() -> dict:
    return {
        "connection_id": None,
        "path_template": "network/{device.name}/tacacs",
        "field": "key",
        "mode": "fixed",
        "fixed_value": "",
        "source_path": "",
        "destination_path": "tacacs.shared_secret",
        "strict_templates": True,
    }
