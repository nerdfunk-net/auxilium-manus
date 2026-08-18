def get_config() -> dict:
    return {
        "message": (
            "Device {device.name} failed at {error.step_id} (node {error.node_id}): {error.message}"
        ),
    }
