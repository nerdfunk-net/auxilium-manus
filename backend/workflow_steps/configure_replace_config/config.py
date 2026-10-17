def get_config() -> dict:
    return {
        "destination_filename": "",
        "file_system": "bootflash:",
        "timeout_minutes": 2,
        "job_timeout_seconds": 120,
        "skip_if_no_pending_changes": True,
        "verify_diff_after_replace": True,
    }
