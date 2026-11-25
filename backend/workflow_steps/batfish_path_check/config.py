def get_config() -> dict:
    return {
        "start_node": "",
        "end_node": "",
        "dst_ips": "",
        "src_ips": "",
        "applications": [],
        "ip_protocols": "",
        "max_traces": None,
        "ignore_filters": False,
        "output_key": "batfish_path_check",
        "batfish_source_id": "",
        "network": "",
        "snapshot": "",
    }
