from services.network.netmiko.connection import DEFAULT_READ_TIMEOUT


def get_config() -> dict:
    return {
        "credential_reference": "",
        "credential_source": "fixed",
        "credential_param": "",
        "commands": ["show version"],
        "parser": "none",
        "network_driver_override": "",
        "pyats_source_id": "",
        "parsed_output_key": "parsed",
        "execution_mode": "exec_mode",
        "write_config_after_execution": False,
        "read_timeout": DEFAULT_READ_TIMEOUT,
        "auto_confirm_prompts": False,
    }
