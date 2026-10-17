from __future__ import annotations


def get_config() -> dict:
    # Fan-in is a pass-through join marker; the only setting is an optional label.
    return {"label": ""}
