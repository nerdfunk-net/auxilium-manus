def get_config() -> dict:
    return {
        "nautobot_source_id": "",
        "device_identifier": {"mode": "from_context"},
        "mode": "write",
        "path": "",
        "create_local_if_missing": False,
        "value_source": {
            "type": "attribute",
            "attribute_path": "",
            "template_id": None,
        },
    }
