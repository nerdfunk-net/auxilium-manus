from workflow_steps.common.device_file_upload import DEFAULT_SOCKET_TIMEOUT


def get_config() -> dict:
    return {
        "credential_reference": "",
        "credential_source": "fixed",
        "credential_param": "",
        "git_repository_id": None,
        "allow_stale_repository": False,
        "source_path": "",
        "expected_md5": "",
        "destination_filename": "",
        "file_system": "",
        "overwrite": False,
        "network_driver_override": "",
        "socket_timeout": DEFAULT_SOCKET_TIMEOUT,
        "read_timeout": 600,
    }
