from __future__ import annotations


def get_config() -> dict:
    return {
        # How far back the controller looks for wired clients (hours, 1-168).
        "lookback_hours": 24,
    }
