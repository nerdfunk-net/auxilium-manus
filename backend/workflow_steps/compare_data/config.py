def get_config() -> dict:
    return {
        "content_source": "running_config",
        "source_step_node_id": "",
        "parsed_output_key": "",
        "reference_location": "filesystem",
        "reference_subdirectory": "references",
        "git_source_id": "",
        "repository_subdirectory": "",
        "pull_before_read": False,
        "filename_template": "{device.name}.cfg",
        "strict_templates": True,
        "normalize_line_endings": True,
        "ignore_trailing_whitespace": False,
    }
