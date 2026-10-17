from __future__ import annotations


def get_config() -> dict:
    return {
        "nautobot_source_id": "",
        "name_filter": "",
        "name_match": "exact",
        "split_members": False,
        "index_regex": r":(\d+)",
        "index_offset": -1,
        "index_default": 0,
        "attribute_bag": "virtual_chassis",
        "index_key": "stack_index",
    }
