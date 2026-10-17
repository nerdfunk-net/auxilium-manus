def get_config() -> dict:
    return {
        "connection_id": None,
        "path_template": "network/{device.name}/tacacs",
        "field": "key",
        "source_path": "run_input.new_tacacs_key",
        "destination_path": "tacacs.shared_secret",
        "strict_templates": True,
    }
