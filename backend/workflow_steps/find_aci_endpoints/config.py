from __future__ import annotations


def get_config() -> dict:
    return {
        # The Cisco ACI source (APIC) to ask.
        "aci_source_id": "",
        # Device attribute holding the IPv4 or MAC address to look up.
        "address_path": "primary_ip4",
        # Where the result lands: parsed.<parsed_output_key>.endpoints = {parsed, error}.
        "parsed_output_key": "aci_endpoint",
    }
