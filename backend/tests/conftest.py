"""Ensure ``backend/`` is on ``sys.path`` so ``core.*`` / ``services.*`` import.

Allows pytest to be started from either ``backend/`` or the repo root.
Loaded for both ``tests/unit`` and ``tests/integration``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_backend_str = str(_BACKEND_ROOT)
if _backend_str not in sys.path:
    sys.path.insert(0, _backend_str)
