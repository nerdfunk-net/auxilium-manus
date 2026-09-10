def get_config() -> dict:
    return {
        "git_repository_id": None,
        # When this run deploys an approved change request, pull that change
        # request's per-change branch (manus/cr-{id}) instead of the repository's
        # default branch. No effect on ordinary runs. See doc/CICD_PIPELINE.md.
        "use_change_request_branch": False,
    }
