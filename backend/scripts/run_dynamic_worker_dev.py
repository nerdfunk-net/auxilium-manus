"""Dev-only auto-restart wrapper for the Hatchet dynamic (background-tier) worker.

Unlike scripts/run_worker_dev.py (which can rely on plain watchfiles.run_process,
since worker.py never exits on its own), this worker exits itself on purpose —
whenever hatchet/dynamic_worker.py's poll loop notices a published-workflow
change, it sends itself SIGTERM to pick up the fresh registration on restart
(see _self_restart_on_change there). watchfiles.run_process only restarts its
target on a *file* change; it does not notice the target process exiting for
any other reason, so it can't be used alone here — in production this gap is
covered by supervisord's autorestart=true, which this script re-implements
for local dev: it restarts the worker both on a .py file change (like
run_worker_dev.py) and whenever the process exits on its own (self-restart or
a crash).

Usage (from backend/, with the venv active):
    python scripts/run_dynamic_worker_dev.py
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

from watchfiles import PythonFilter, watch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CMD = [sys.executable, "-m", "hatchet.dynamic_worker"]


def _watch_for_file_changes(proc: subprocess.Popen[bytes], stop_event: threading.Event) -> None:
    """Terminate `proc` on the first watched .py change; exits quietly if
    `stop_event` fires first (the process already exited on its own)."""
    for changes in watch(
        BACKEND_ROOT, watch_filter=PythonFilter(), stop_event=stop_event
    ):
        print(
            f"[run_dynamic_worker_dev] change detected, restarting worker: {sorted(changes)}",
            flush=True,
        )
        proc.terminate()
        return


def main() -> None:
    while True:
        proc = subprocess.Popen(CMD, cwd=BACKEND_ROOT)
        stop_event = threading.Event()
        watcher = threading.Thread(
            target=_watch_for_file_changes, args=(proc, stop_event), daemon=True
        )
        watcher.start()

        return_code = proc.wait()
        stop_event.set()

        print(
            f"[run_dynamic_worker_dev] worker exited (code={return_code}), restarting…",
            flush=True,
        )


if __name__ == "__main__":
    main()
