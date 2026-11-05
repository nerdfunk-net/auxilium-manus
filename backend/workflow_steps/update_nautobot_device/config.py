"""Default configuration for the update-nautobot-device step."""


def get_config() -> dict:
    return {
        "nautobot_source_id": "",
        "device_identifier": {
            "mode": "from_context",
        },
        "update_fields": {},
        "interfaces_source": "manual",
        "interfaces": [],
        # Used when interfaces_source == "parsed_list": a list of dicts on the device (for example
        # TextFSM "show interfaces" output) whose columns are mapped to interface fields.
        "parsed_list": {
            "source_path": "",
            "field_map": {},
            "fixed_values": {},
            # Type for interfaces that do not exist yet (never changes an existing one):
            # mode none (skip them), infer (guess from the name) or fixed (+ value).
            "new_interface_type": {"mode": "none", "value": ""},
        },
        "add_prefix": True,
        "default_prefix_length": "/24",
        "sync_interfaces": False,
        "dry_run": False,
    }
