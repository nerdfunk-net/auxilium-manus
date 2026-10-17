def get_config() -> dict:
    # The SMTP server, port, security, credential and sender are NOT step settings: mail is sent
    # through the server an administrator configured under Settings -> Mail (S3-02 / S4-09).
    return {
        "to": "",
        "subject": "Workflow finished: {device_count} device(s)",
        "body": "Workflow finished: {device_count} device(s) ({devices})",
    }
