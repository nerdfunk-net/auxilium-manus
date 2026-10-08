def get_config() -> dict:
    return {
        "smtp_server": "",
        "smtp_port": 587,
        "security": "starttls",
        "verify_tls": True,
        "credential_reference": "",
        "from_address": "",
        "to": "",
        "subject": "Workflow finished: {device_count} device(s)",
        "body": "Workflow finished: {device_count} device(s) ({devices})",
    }
