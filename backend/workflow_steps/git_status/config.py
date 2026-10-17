def get_config() -> dict:
    return {
        "git_repository_id": None,
        # Fetch from origin first so ahead/behind is accurate (needs network + credentials).
        "fetch_remote": True,
        # Which conditions make the working tree "dirty".
        "check_uncommitted": True,
        "check_untracked": True,
        "check_sync": True,
    }
