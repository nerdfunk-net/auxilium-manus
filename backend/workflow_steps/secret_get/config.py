def get_config() -> dict:
    return {
        "connection_id": None,
        "path_template": "network/{device.name}/tacacs",
        "field": "key",
        "destination_path": "tacacs.shared_secret",
        "version": None,
        "strict_templates": True,
    }
