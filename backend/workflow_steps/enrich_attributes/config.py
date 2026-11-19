def get_config() -> dict:
    return {
        "source": "filesystem",
        "git_repository_id": None,
        "allow_stale_repository": False,
        "path": "",
        "delimiter": ";",
        "key_column": "",
        "device_attribute_path": "",
        "match_mode": "match",
        "case_insensitive": False,
        "destination_path": "data",
        "overwrite": False,
    }
