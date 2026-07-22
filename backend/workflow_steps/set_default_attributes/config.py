"""Default configuration for the set-default-attributes step."""


def get_config() -> dict:
    return {
        "type": "device",
        "mode": "manual",
        "overwrite": False,
        "attributes": {
            "role": {"enabled": False, "value": ""},
            "status": {"enabled": False, "value": ""},
            "location": {"enabled": False, "value": ""},
            "platform": {"enabled": False, "value": ""},
            "software_version": {"enabled": False, "value": ""},
            "serial": {"enabled": False, "value": ""},
            "asset_tag": {"enabled": False, "value": ""},
            "tags": {"enabled": False, "value": ""},
            "device_type": {"enabled": False, "model": "", "manufacturer": ""},
            "rack": {"enabled": False, "value": ""},
            "face": {"enabled": False, "value": ""},
            "position": {"enabled": False, "value": ""},
            "custom_fields": {},
            "interfaces": [],
        },
        "git": {
            "git_source_id": "",
            "filename_pattern": "*.yaml",
        },
    }
