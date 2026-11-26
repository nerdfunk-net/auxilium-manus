"""Child process for ``workflow_steps.common.jinja_render``: one step render, then exit (S4-07).

Reads ``{"template", "context", "allow_multiline_values", "max_output_chars"}`` as JSON on stdin
and writes the result of ``jinja_sandbox.render_plain`` as JSON on stdout. Run with ``python -I``
and an empty environment: it imports nothing from the project except ``jinja_sandbox`` (Jinja2
and the standard library only), loaded by path. CPU and address-space limits make the operating
system stop a runaway template; the parent also kills the process at its timeout.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import sys
from pathlib import Path

CPU_SECONDS = 10
MEMORY_BYTES = 1024 * 1024 * 1024


def _limit_resources() -> None:
    # No `resource` module (Windows) or a platform that refuses RLIMIT_AS (macOS): the parent's
    # timeout kill and the CPU limit still apply where available.
    with contextlib.suppress(ImportError, ValueError, OSError):
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS + 1))
    with contextlib.suppress(ImportError, ValueError, OSError):
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))


def _load_sandbox():
    backend = Path(__file__).resolve().parent.parent
    path = backend / "services" / "workflow_context" / "jinja_sandbox.py"
    spec = importlib.util.spec_from_file_location("_jinja_sandbox", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_jinja_sandbox"] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    _limit_resources()
    request = json.loads(sys.stdin.buffer.read())
    result = _load_sandbox().render_plain(
        request["template"],
        request["context"],
        allow_multiline_values=bool(request["allow_multiline_values"]),
        max_output_chars=int(request["max_output_chars"]),
    )
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    main()
