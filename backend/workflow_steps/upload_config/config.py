from workflow_steps.common.device_file_upload import DEFAULT_SOCKET_TIMEOUT


def get_config() -> dict:
    return {
        "credential_reference": "",
        "credential_source": "fixed",
        "credential_param": "",
        "content_source": "updated_content",
        "source_step_node_id": "",
        "parsed_output_key": "",
        "destination_filename": "",
        "file_system": "",
        "overwrite": False,
        "inline_transfer": False,
        "network_driver_override": "",
        "socket_timeout": DEFAULT_SOCKET_TIMEOUT,
        "verify_content": False,
        "verify_algorithm": "md5",
    }
