from __future__ import annotations


def get_config() -> dict:
    return {
        # Which facts to read (checkboxes): device, software, interfaces, vlans, compliance.
        "facts": ["device", "interfaces"],
        # Where the facts land: parsed.<parsed_output_key>.<fact> = {parsed, error}.
        "parsed_output_key": "catalyst_details",
    }
