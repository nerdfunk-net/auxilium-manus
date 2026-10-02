def get_config() -> dict:
    return {
        "nautobot_source_id": "",
        "device_identifier": {"mode": "from_context"},
        "mode": "write",
        # write/append: one path + value_source.
        "path": "",
        "value_source": {
            "type": "attribute",
            "attribute_path": "",
            "template_id": None,
        },
        # update: one entry per path/value pair, all applied in a single PATCH.
        "updates": [
            {
                "path": "",
                "value_source": {
                    "type": "attribute",
                    "attribute_path": "",
                    "template_id": None,
                },
            }
        ],
        "create_local_if_missing": False,
    }
