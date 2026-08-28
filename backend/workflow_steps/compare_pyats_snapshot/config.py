def get_config() -> dict:
    return {
        "feature": "",
        "source_step_node_id": "",
        "parsed_output_key": "",
        "reference_location": "filesystem",
        "reference_subdirectory": "pyats-snapshots",
        "git_repository_id": None,
        "repository_subdirectory": "",
        "pull_before_read": False,
        "filename_template": "{device.name}.pyats-snapshot.json",
        "exclude_keys": [],
    }
