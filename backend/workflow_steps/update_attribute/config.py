def get_config() -> dict:
    return {
        "mode": "fixed",
        "destination_path": "custom.location",
        "fixed_value": "",
        "source_path": "device.name",
        "pattern": r"^([^-]+)-",
        "destination_template": r"DC-\1",
        "regex_flags": {
            "case_insensitive": False,
            "multiline": False,
            "dotall": False,
        },
    }
