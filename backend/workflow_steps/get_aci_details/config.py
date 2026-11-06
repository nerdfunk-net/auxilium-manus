from __future__ import annotations


def get_config() -> dict:
    return {
        # Which facts to read (checkboxes): device, software, hardware, interfaces, neighbors,
        # vlans, health, faults, routes, protocols, endpoints, vpc.
        "facts": ["device", "software", "interfaces"],
        # Where the facts land: parsed.<parsed_output_key>.<fact> = {parsed, error}.
        "parsed_output_key": "aci_details",
    }
