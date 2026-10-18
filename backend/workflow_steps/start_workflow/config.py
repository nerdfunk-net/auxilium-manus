"""Default configuration for the start-workflow workflow step."""

from __future__ import annotations


def get_config() -> dict:
    return {
        # id of the workflow to start (e.g. a backup workflow)
        "workflow_id": None,
        "workflow_name": "",
        # values for the started workflow's declared run inputs (static attributes); never secrets
        "run_inputs": {},
        # name of the started workflow's text run input (the device_param of its Get from User
        # step) that receives this workflow's devices as one "name,ip" line per device; empty =
        # the workflow is called without devices
        "devices_input": "",
        # "all_devices": one run for all devices; "per_device": one run per device
        "run_mode": "all_devices",
        # most runs this step may start; more devices than this in per_device mode is refused
        "max_runs": 25,
        # wait for the started runs to finish, up to wait_seconds (10 minutes at most)
        "wait": True,
        "wait_seconds": 300,
        "poll_interval_seconds": 5,
        # accept a run that finished with a partial step as success
        "allow_partial": False,
        # attribute_bags key the run id / status are written to on every device
        "bag_name": "child_run",
    }
