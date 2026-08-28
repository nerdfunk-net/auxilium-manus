def get_config() -> dict:
    return {
        "git_repository_id": None,
        "directory": "",
        "file_filter": "",
        "recursive": True,
        "include_history": False,
        "search_text": "",
        "case_sensitive": False,
        "fan_out": {
            "enabled": False,
            "mode": "per_device",
            "chunk_size": 1,
            "max_concurrency": 0,
        },
    }
