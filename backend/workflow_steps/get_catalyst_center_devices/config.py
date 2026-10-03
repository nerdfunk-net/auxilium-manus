from __future__ import annotations


def get_config() -> dict:
    return {
        "catalyst_center_source_id": "",
        # Server-side device filters; keys are listed in
        # services/catalyst_center/device_filters.py. Empty = none configured.
        "filters": {},
        # Safety guard: with no filter the step fails unless this is explicitly enabled.
        "allow_all": False,
        # Fail (never truncate) when more devices than this match; None = no cap.
        "max_devices": None,
        "fan_out": {
            "enabled": False,
            "mode": "per_device",
            "chunk_size": 1,
            "max_concurrency": 0,
        },
    }
