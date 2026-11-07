from services.network.netmiko.connection import DEFAULT_READ_TIMEOUT


def get_config() -> dict:
    return {
        "credential_reference": "",
        "credential_source": "fixed",
        "credential_param": "",
        "collect_ip_address": True,
        "collect_mac_address": True,
        "collect_vrfs": True,
        "collect_hostname": False,
        "dns_timeout_seconds": 2,
        "dns_concurrency": 20,
        "network_driver_override": "",
        "read_timeout": DEFAULT_READ_TIMEOUT,
        "dry_run": False,
        "retry_backoff_seconds": [],
    }
