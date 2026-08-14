def get_config() -> dict:
    return {"content_source": "running_config", "replace_rules": []}


def get_default_rule() -> dict:
    return {
        "pattern": r"ntp server 192\.168\.1\.10",
        "replacement": "ntp server 192.168.178.10",
        "regex_flags": {"case_insensitive": False, "multiline": False, "dotall": False},
        "replace_all": True,
    }
