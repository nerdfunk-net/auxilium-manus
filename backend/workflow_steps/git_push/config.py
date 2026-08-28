def get_config() -> dict:
    return {
        "git_repository_id": None,
        "commit_before_push": True,
        "commit_message_template": "commit {timestamp}",
    }
