def get_config() -> dict:
    return {
        "nodes": "",
        "include_process": True,
        "include_peers": True,
        "include_sessions": True,
        "include_edges": True,
        "output_key": "batfish_bgp_facts",
        "batfish_source_id": "",
        "network": "",
        "snapshot": "",
    }
