def get_config() -> dict:
    return {
        "batfish_source_id": "",
        "retain_snapshots": 5,
        "allow_partial_snapshot": False,
        "network_name": "",
        "network_name_source": "fixed",
        "network_name_param": "",
        "config_source": "live",
        "git_repository_id": None,
        "allow_stale_repository": False,
        "base_path": "",
        "glob_pattern": "",
    }
