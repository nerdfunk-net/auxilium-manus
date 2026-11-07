from __future__ import annotations


def get_config() -> dict:
    return {
        # Where the result lands: parsed.<parsed_output_key>.epgs.parsed and
        # parsed.<parsed_output_key>.contracts.parsed (each {parsed, error}).
        "parsed_output_key": "aci_policy",
    }
