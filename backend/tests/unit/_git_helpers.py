"""Stand-ins for ``services.git.sync.git_checkout`` / ``agit_checkout`` in unit tests.

Both are context managers that yield the repository root, so a test patches the name used by the
module under test with ``return_value=checkout_of(path)`` / ``acheckout_of(path)``.
"""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from typing import Any


def checkout_of(path: Path) -> Any:
    """Reusable sync context manager yielding *path* (for ``git_checkout``)."""
    return nullcontext(path)


class _AsyncCheckout:
    def __init__(self, path: Path) -> None:
        self._path = path

    async def __aenter__(self) -> Path:
        return self._path

    async def __aexit__(self, *exc_info: object) -> None:
        return None


def acheckout_of(path: Path) -> Any:
    """Reusable async context manager yielding *path* (for ``agit_checkout``)."""
    return _AsyncCheckout(path)
