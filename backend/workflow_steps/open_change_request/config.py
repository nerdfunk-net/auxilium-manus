def get_config() -> dict:
    return {
        # Git repository the per-change branch is pushed to.
        "git_repository_id": None,
        # Which upstream content to commit (defaults to rendered templates).
        "content_source": "rendered_template",
        "source_step_node_id": "",
        "parsed_output_key": "",
        # Path prefix inside the repository working tree.
        "repository_subdirectory": "",
        # Per-device file name. Placeholders: {device.name}, {nautobot.*}, {run.*}.
        "filename_template": "{device.name}.cfg",
        # Per-change branch name. Placeholders: {run.id}, {workflow.id}.
        "branch_template": "manus/cr-{run.id}",
        "commit_message_template": "Change request: run {run.id}",
        "title_template": "Change request for run {run.id}",
        # Workflow that deploys an approved change request (optional — a reviewer
        # may also choose one at approval time).
        "deploy_workflow_id": None,
        # TTL for an un-actioned change request; 0 disables expiry.
        "expires_after_hours": 168,
        "strict_templates": True,
    }
