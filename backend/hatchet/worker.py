"""Hatchet worker entry point.

Run as a separate process alongside the FastAPI server:

    cd backend
    source ../.venv/bin/activate
    python -m hatchet.worker
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure backend root is on sys.path when invoked via `python -m hatchet.worker`
_backend_root = Path(__file__).resolve().parents[1]
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

from hatchet.client import hatchet  # noqa: E402 (after path setup)
from hatchet.workflows.workflow_run import WorkflowExecutionWorkflow  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    worker = hatchet.worker("auxilium-manus-worker", max_runs=10)
    worker.register_workflow(WorkflowExecutionWorkflow())
    logger.info("Starting Hatchet worker — listening for workflow:run events")
    worker.start()


if __name__ == "__main__":
    main()
