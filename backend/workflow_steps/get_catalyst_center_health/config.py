from __future__ import annotations


def get_config() -> dict:
    return {
        # Where the health lands: parsed.<parsed_output_key>.health = {parsed, error}.
        "parsed_output_key": "catalyst_health",
    }
