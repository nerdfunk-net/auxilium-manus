def get_config() -> dict:
    return {
        "source": "filesystem",
        "git_source_id": "",
        "path_template": "{device.name}.cfg",
        "overwrite_existing": False,
    }
