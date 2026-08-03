"""Worker identity/capacity constants, shared with the read-only Hatchet settings display.

Kept separate from worker.py so the settings service (running in the FastAPI
process) can report these values without importing worker.py itself, which
pulls in heavy service startup code meant only for the worker process.
"""

from __future__ import annotations

WORKER_NAME = "auxilium-manus-worker"
WORKER_SLOTS = 10
