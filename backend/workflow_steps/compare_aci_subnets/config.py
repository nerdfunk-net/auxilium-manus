from __future__ import annotations


def get_config() -> dict:
    return {
        # The Cisco ACI source (APIC) and the Nautobot source to compare.
        "aci_source_id": "",
        "nautobot_source_id": "",
        # Nautobot namespace the ACI subnets are compared in (ignored with namespace_from_vrf).
        "namespace": "Global",
        # Use the name of each subnet's VRF as the Nautobot namespace instead.
        "namespace_from_vrf": False,
        # Nautobot networks inside these prefixes that ACI lacks are reported too; empty = skip.
        "scope_prefixes": [],
        # Metadata entry "<node id>.<output_key>" holds the summary; the full report is an artifact.
        "output_key": "aci_subnet_report",
    }
