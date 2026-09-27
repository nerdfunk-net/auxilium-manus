"""Default configuration for the start-nautobot-job workflow step."""

from __future__ import annotations


def get_config() -> dict:
    return {
        "nautobot_source_id": "",
        "job_id": "",
        "job_name": "",
        "job_variables_schema": [],
        "parameters": {"required": {}, "optional": {}},
        "task_queue": "",
    }
