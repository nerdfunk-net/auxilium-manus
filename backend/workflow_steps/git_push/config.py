def get_config() -> dict:
    return {
        "git_source_id": "",
        "commit_before_push": True,
        "commit_message_template": "commit {timestamp}",
    }
