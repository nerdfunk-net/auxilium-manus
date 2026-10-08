def get_config() -> dict:
    return {
        "git_repository_id": None,
        # Fetch from origin first so ahead/behind is accurate (needs network + credentials).
        "fetch_remote": True,
        # Which conditions make the working tree "dirty".
        "check_uncommitted": True,
        "check_untracked": True,
        "check_sync": True,
        # When this run deploys an approved change request, inspect that change
        # request's per-change branch (manus/cr-{id}). See doc/CICD_PIPELINE.md.
        "use_change_request_branch": False,
    }
