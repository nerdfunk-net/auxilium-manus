"""Worker identity/capacity settings, shared with the read-only Hatchet settings display.

Kept separate from worker.py so the settings service (running in the FastAPI
process) can report these values without importing worker.py itself, which
pulls in heavy service startup code meant only for the worker process.

Both values are read from the environment (with the prior hardcoded values as
defaults) so operators can tune worker capacity per-deployment without a code
change. Like the rest of the HATCHET_CLIENT_* settings, a change only takes
effect after restarting the worker process — slots are passed to the Hatchet
SDK's worker() constructor at startup and cannot be changed on a running worker.
"""

from __future__ import annotations

import os

WORKER_NAME = os.environ.get("HATCHET_WORKER_NAME", "auxilium-manus-worker")
WORKER_SLOTS = int(os.environ.get("HATCHET_WORKER_SLOTS", "10"))
