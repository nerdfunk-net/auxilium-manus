def get_config() -> dict:
    return {
        # Also check out the change request's manus/cr-{id} branch into the
        # repository working tree, so later git-reading steps see it.
        "checkout_branch": True,
        # Load each device's committed config file as running_config, so the
        # deploy workflow needs no separate read-config step.
        "load_configs": True,
    }
