"""Worker identity/capacity/polling settings for the dynamic (background-tier)
worker, mirroring hatchet/worker_config.py. Kept separate from
dynamic_worker.py so a future read-only settings display can report these
values without importing worker startup code.
"""

from __future__ import annotations

import os

DYNAMIC_WORKER_NAME = os.environ.get(
    "HATCHET_DYNAMIC_WORKER_NAME", "auxilium-manus-background-worker"
)
DYNAMIC_WORKER_SLOTS = int(os.environ.get("HATCHET_DYNAMIC_WORKER_SLOTS", "10"))
# How often the dynamic worker re-checks Postgres for published/edited/
# unpublished background-tier workflows. On a change it exits (SIGTERM, same
# signal a normal supervised stop already sends) so supervisord's
# autorestart=true brings it back with a freshly-registered workflow set.
DYNAMIC_WORKER_POLL_INTERVAL_SECONDS = int(
    os.environ.get("HATCHET_DYNAMIC_WORKER_POLL_INTERVAL_SECONDS", "30")
)
