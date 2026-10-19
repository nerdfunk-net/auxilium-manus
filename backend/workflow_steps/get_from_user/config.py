from __future__ import annotations

from workflow_steps.common.device_list import DEFAULT_NETWORK_DRIVER


def get_config() -> dict:
    return {
        "device_param": "target_devices",
        # Network driver of every device line that does not name its own
        # (``name,ip_address,network_driver``).
        "default_network_driver": DEFAULT_NETWORK_DRIVER,
        # UI-only hints consumed by the Run Inputs dialog when prompting the
        # operator — the executor never reads these two fields and never
        # calls Nautobot. "manual": a plain multi-line box. "nautobot_search":
        # a name-contains typeahead against nautobot_source_id, with manual
        # entry still available as a fallback.
        "lookup_mode": "manual",
        "nautobot_source_id": "",
        "fan_out": {
            "enabled": False,
            "mode": "per_device",
            "chunk_size": 1,
            "max_concurrency": 0,
        },
    }
