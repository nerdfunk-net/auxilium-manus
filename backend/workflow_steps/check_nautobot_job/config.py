"""Default configuration for the check-nautobot-job workflow step."""

from __future__ import annotations


def get_config() -> dict:
    return {
        "nautobot_source_id": "",
        "job_uuid": "{nautobot_job.job_result_id}",
        "max_checks": 10,
        "interval_seconds": 5,
    }
