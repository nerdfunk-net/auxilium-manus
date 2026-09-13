def get_config() -> dict:
    # Start Batfish Run has no user-configurable fields -- it only exists to
    # seed an empty device context so a git-mode Init Batfish Snapshot step
    # (which needs no real devices) can still satisfy the canvas's
    # requires: [identity] connection rule.
    return {}
