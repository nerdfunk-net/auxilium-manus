def get_config() -> dict:
    return {
        "source": "filesystem",
        "git_repository_id": None,
        "path_template": "{device.name}.cfg",
        "overwrite_existing": False,
    }
