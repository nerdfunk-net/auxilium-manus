"""Child process for ``render_isolated``: one trial render, then exit.

Reads ``{"content", "context"}`` as JSON on stdin and writes the ``RenderOutcome`` as JSON on
stdout. Run with ``python -I`` so it imports nothing from the project except ``template_render``
(which needs only Jinja2), loaded by path. CPU and address-space limits make the operating system
stop a runaway template even if the parent is busy; the parent also kills the process on timeout.
"""

from __future__ import annotations

import contextlib
import dataclasses
import importlib.util
import json
import sys
from pathlib import Path

CPU_SECONDS = 5
MEMORY_BYTES = 1024 * 1024 * 1024
MAX_OUTPUT_CHARS = 1_000_000


def _limit_resources() -> None:
    # No `resource` module (Windows) or a platform that refuses RLIMIT_AS (macOS): the parent's
    # timeout kill and the CPU limit still apply where available.
    with contextlib.suppress(ImportError, ValueError, OSError):
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS + 1))
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))


def _load_template_render():
    path = Path(__file__).with_name("template_render.py")
    spec = importlib.util.spec_from_file_location("_template_render", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_template_render"] = module  # dataclasses resolves the module by name
    spec.loader.exec_module(module)
    return module


def main() -> None:
    _limit_resources()
    request = json.load(sys.stdin)
    outcome = _load_template_render().render_lenient(request["content"], request["context"])
    result = dataclasses.asdict(outcome)
    result["output"] = result["output"][:MAX_OUTPUT_CHARS]
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
