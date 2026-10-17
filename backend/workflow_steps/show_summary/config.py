from __future__ import annotations


def get_config() -> dict:
    # Show Summary has no user-configurable fields — the table is always the
    # same shape, derived from the run's step results at display time.
    return {}
