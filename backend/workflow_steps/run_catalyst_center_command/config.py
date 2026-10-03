from __future__ import annotations


def get_config() -> dict:
    return {
        # Read-only CLI commands run through the Catalyst Center command runner, in order.
        "commands": ["show version"],
        # Seconds the controller may spend on the whole request (1-300).
        "timeout": 300,
        # "none" keeps raw text only; "textfsm" also parses each command into rows.
        "parser": "none",
        # Where parsed output lands: parsed.<parsed_output_key>.<command> = {parsed, error}.
        "parsed_output_key": "parsed",
        # Netmiko device type for TextFSM templates when the device has no network_driver.
        "network_driver_override": "",
    }
