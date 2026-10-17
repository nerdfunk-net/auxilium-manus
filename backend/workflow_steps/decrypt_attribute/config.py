def get_config() -> dict:
    return {
        "source_path": "",
        "destination_path": "",
        "credential_reference": "",
        # Blank -> use the shared-secret credential's configured algorithm.
        "algorithm": "",
        # Blank -> scalar mode (source_path is one token). Set to a field name
        # -> list mode: source_path is a list, decrypt that field on every entry.
        "item_field": "",
    }
