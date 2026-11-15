from __future__ import annotations


def get_config() -> dict:
    return {
        # Agent source configured under Settings -> Sources -> Agents.
        "agent_source_id": "",
        # Name of the handler the agent runs; the app never sends code.
        "handler": "",
        # Rows of {"name": ..., "value": ...} sent to the handler as inputs["attributes"].
        # A value is fixed text or a whole-value "{run_input.<name>}" reference.
        "attributes": [],
        "timeout_seconds": 30,
        "fan_out": {
            "enabled": False,
            "mode": "per_device",
            "chunk_size": 1,
            "max_concurrency": 0,
        },
    }
