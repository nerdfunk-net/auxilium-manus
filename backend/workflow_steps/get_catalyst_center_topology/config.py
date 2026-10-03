from __future__ import annotations


def get_config() -> dict:
    return {
        # Which graphs to read (checkboxes): physical, l3_ospf, l3_isis, l3_eigrp, l3_static.
        "topologies": ["physical"],
        # Where the result lands: parsed.<parsed_output_key>.<topology> = {parsed, error}.
        "parsed_output_key": "catalyst_topology",
    }
