def get_config() -> dict:
    return {
        "git_repository_id": None,
        "allow_stale_repository": False,
        "path_template": "{device.name}.cfg",
        "output_bag": "backup_age",
        "use_marker": False,
        "marker_storage_key": "",
    }
