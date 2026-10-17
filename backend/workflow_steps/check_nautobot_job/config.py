"""Default configuration for the check-nautobot-job workflow step."""

from __future__ import annotations


def get_config() -> dict:
    return {
        "nautobot_source_id": "",
        "job_uuid": "{nautobot_job.job_result_id}",
        "max_checks": 10,
        "interval_seconds": 5,
        # attribute_bags key this step writes status/checks_performed to (merged onto
        # whatever start-nautobot-job already put there). Must match that step's bag_name
        # when pairing multiple start/check job pairs on the same device.
        "bag_name": "nautobot_job",
    }
