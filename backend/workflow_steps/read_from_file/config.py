def get_config() -> dict:
    return {
        "source": "filesystem",
        "git_repository_id": None,
        "allow_stale_repository": False,
        "path": "",
        "format": "auto",
        "destination_path": "data",
        "overwrite": False,
    }
