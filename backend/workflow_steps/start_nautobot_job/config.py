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
        # attribute_bags key this step writes to. Two start-nautobot-job nodes on the same
        # device (e.g. an onboard job and an update job) must use different bag_name values
        # or the second node's write overwrites the first's job_result_id/request/response.
        "bag_name": "nautobot_job",
    }
