"""Dev-only auto-restart wrapper for the Hatchet worker.

The worker (`hatchet/worker.py`) has no hot-reload — Python only picks up code
at process start, unlike the FastAPI app which runs under uvicorn's
`reload=True`. This mirrors that behaviour for the worker: watchfiles restarts
`python -m hatchet.worker` whenever a watched .py file under backend/ changes.

Usage (from backend/, with the venv active):
    python scripts/run_worker_dev.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

from watchfiles import Change, PythonFilter, run_process

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _log_reload(changes: Iterable[tuple[Change, str]]) -> None:
    print(f"[run_worker_dev] change detected, restarting worker: {sorted(changes)}", flush=True)


def main() -> None:
    run_process(
        BACKEND_ROOT,
        target=f"{sys.executable} -m hatchet.worker",
        target_type="command",
        watch_filter=PythonFilter(),
        callback=_log_reload,
    )


if __name__ == "__main__":
    main()
