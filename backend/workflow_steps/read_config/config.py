def get_config() -> dict:
    return {
        "source": "filesystem",
        "git_repository_id": None,
        "allow_stale_repository": False,
        "path_template": "{device.name}.cfg",
        "overwrite_existing": False,
    }
