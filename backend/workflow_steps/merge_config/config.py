from services.network.netmiko.connection import DEFAULT_READ_TIMEOUT


def get_config() -> dict:
    return {
        "credential_reference": "",
        "credential_source": "fixed",
        "credential_param": "",
        "source_filename": "",
        "network_driver_override": "",
        "read_timeout": DEFAULT_READ_TIMEOUT,
    }
