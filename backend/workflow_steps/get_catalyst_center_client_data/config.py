from __future__ import annotations


def get_config() -> dict:
    return {
        # How far back the controller looks for wired clients (hours, 1-168).
        "lookback_hours": 24,
        # true = query nothing; the preview is stored per device (dry_run_results).
        "dry_run": False,
    }
