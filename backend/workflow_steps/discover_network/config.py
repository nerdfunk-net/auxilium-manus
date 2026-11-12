from services.network.netmiko.connection import DEFAULT_READ_TIMEOUT


def get_config() -> dict:
    return {
        "credential_reference": "",
        "credential_source": "fixed",
        "credential_param": "",
        "follow_neighbors": False,
        "permitted_prefixes": [],
        "follow_only_infrastructure": True,
        "max_devices": 50,
        "max_depth": 5,
        "concurrency": 5,
        "network_driver_override": "",
        "read_timeout": DEFAULT_READ_TIMEOUT,
        "dry_run": False,
        "retry_backoff_seconds": [],
    }
