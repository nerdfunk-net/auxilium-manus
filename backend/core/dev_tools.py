"""Feature flag for developer-only HTTP routes and UI."""

from __future__ import annotations

import os

from fastapi import HTTPException, status


def dev_tools_enabled() -> bool:
    return os.environ.get("ENABLE_DEV_TOOLS", "").strip().lower() in {"true", "1", "yes"}


def require_dev_tools() -> None:
    if not dev_tools_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
