def get_config() -> dict:
    return {
        "destination": "filesystem",
        "output_subdirectory": "exports",
        "content_source": "running_config",
        "source_step_node_id": "",
        "filename_template": "{device.name}_{nautobot.location.name}_{run.timestamp}.cfg",
        "strict_templates": True,
        "retention_policy": "standard-90-days",
    }
