def get_config() -> dict:
    return {
        "destination": "filesystem",
        "output_subdirectory": "exports",
        "content_source": "running_config",
        "source_step_node_id": "",
        "filename_template": "{name}_{attributes.location.name}_{timestamp}.cfg",
        "retention_policy": "standard-90-days",
    }
