"""Feature flag for developer-only HTTP routes and UI."""

from __future__ import annotations

import os


def dev_tools_enabled() -> bool:
    return os.environ.get("ENABLE_DEV_TOOLS", "").strip().lower() in {"true", "1", "yes"}
