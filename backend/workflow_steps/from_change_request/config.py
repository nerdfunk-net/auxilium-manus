def get_config() -> dict:
    return {
        # Load each device's committed config file as running_config, so the
        # deploy workflow needs no separate read-config step.
        "load_configs": True,
    }
