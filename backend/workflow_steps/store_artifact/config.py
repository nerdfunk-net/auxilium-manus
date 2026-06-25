def get_config() -> dict:
    return {
        "destination": "filesystem",
        "output_subdirectory": "exports",
        "content_source": "running_config",
        "source_step_node_id": "",
        "filename_template": "{device.name}_{nautobot.location.name}_{run.timestamp}.cfg",
        "strict_templates": True,
        "retention_policy": "standard-90-days",
        "git_source_id": "",
        "repository_subdirectory": "",
        "pull_before_write": False,
        "commit_after_write": False,
        "push_after_write": False,
        "commit_message_template": "commit {timestamp}",
    }
