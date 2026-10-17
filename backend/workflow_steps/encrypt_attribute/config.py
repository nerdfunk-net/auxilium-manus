def get_config() -> dict:
    return {
        "source_path": "",
        "destination_path": "",
        "credential_reference": "",
        # Blank -> use the shared-secret credential's configured algorithm.
        "algorithm": "",
    }
