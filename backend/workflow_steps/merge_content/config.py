def get_config() -> dict:
    return {
        "content_source": "command_output",
        "source_step_node_ids": [],
        "merge_mode": "text_sectioned",
        "section_separator": "\n",
        "include_command_header": True,
    }
