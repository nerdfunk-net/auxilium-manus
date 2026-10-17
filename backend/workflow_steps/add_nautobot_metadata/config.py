"""Default configuration for the add-nautobot-metadata step."""


def get_config() -> dict:
    return {
        "nautobot_source_id": "",
        "metadata_type": "location",
        "location": {
            "location_type": "",
            "name": "",
            "status": "Active",
            "description": "",
            "parent": "",
        },
        "device_type": {
            "manufacturer": "",
            "role": "",
            "model": "",
            "height": "1",
            "platform": "",
        },
    }
