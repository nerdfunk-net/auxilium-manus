from services.network.netmiko.connection import DEFAULT_READ_TIMEOUT


def get_config() -> dict:
    return {
        "credential_reference": "",
        "source_step_node_id": "",
        "parsed_output_key": "",
        "execution_mode": "config_mode",
        "network_driver_override": "",
        "write_config_after_execution": False,
        "read_timeout": DEFAULT_READ_TIMEOUT,
        "auto_confirm_prompts": False,
    }
