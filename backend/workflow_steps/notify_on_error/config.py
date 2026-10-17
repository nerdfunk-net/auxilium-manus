def get_config() -> dict:
    return {
        "message": (
            "Device {device.name} failed at {error.step_id} (node {error.node_id}): {error.message}"
        ),
        "max_messages": 20,
        "notify_local": True,
        "notify_mattermost": False,
        "mattermost_source_id": "",
        "team_name": "",
        "channel_name": "",
    }
