"""Child process for ``core.textfsm_isolated``: one TextFSM job, then exit.

Reads ``{"platform", "items": [[command, output], ...]}`` as JSON on stdin and writes
``{"ok", "result": [{"rows", "error"}, ...]}`` on stdout. Run with ``python -I`` and an EMPTY
environment. TextFSM compiles and runs its templates with ``re``, which holds the GIL while it
matches, so a slow match in the API process would stall every request; here the operating system
stops it (CPU limit) and the parent kills it on timeout.

The ``error`` of an item is a fixed code (``no_template``, ``no_match``, ``failed``, ``timeout``),
never text from the device or from an exception.
"""

from __future__ import annotations

import contextlib
import json
import sys
from typing import Any

CPU_SECONDS = 20
MEMORY_BYTES = 1024 * 1024 * 1024
ITEM_SECONDS = 8  # one command; ``re`` checks for signals while it matches


def _limit_resources() -> None:
    with contextlib.suppress(ImportError, ValueError, OSError):
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS + 2))
    with contextlib.suppress(ImportError, ValueError, OSError):
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))


class _ItemTimeout(Exception):
    """Raised from the SIGALRM handler when one command takes too long."""


def _on_alarm(signum: int, frame: object) -> None:
    raise _ItemTimeout


def _platforms(platform: str) -> list[str]:
    # Netmiko's own helper retries cisco_xe with the cisco_ios templates: ntc-templates has none
    # for cisco_xe, but IOS-XE is stored under that driver name.
    return [platform, "cisco_ios"] if "cisco_xe" in platform else [platform]


def _parse_one(command: str, output: str, platform: str) -> dict[str, Any]:
    from ntc_templates.parse import ParsingException, parse_output

    template_found = False
    for name in _platforms(platform):
        try:
            rows = parse_output(platform=name, command=command, data=output)
        except ParsingException:
            rows = None  # no template under this platform name; the next name may have one
        else:
            template_found = True
            if rows:
                return {"rows": rows, "error": None}
    return {"rows": None, "error": "no_match" if template_found else "no_template"}


def parse_items(
    platform: str, items: list[list[str]], *, item_seconds: float = ITEM_SECONDS
) -> list[dict[str, Any]]:
    import signal

    timed = hasattr(signal, "setitimer")
    if timed:
        signal.signal(signal.SIGALRM, _on_alarm)
    answers: list[dict[str, Any]] = []
    for command, output in items:
        try:
            if timed:
                signal.setitimer(signal.ITIMER_REAL, item_seconds)
            answers.append(_parse_one(command, output, platform))
        except _ItemTimeout:
            answers.append({"rows": None, "error": "timeout"})
        except Exception:  # a template that crashes on odd output only spoils its own item
            answers.append({"rows": None, "error": "failed"})
        finally:
            if timed:
                signal.setitimer(signal.ITIMER_REAL, 0)
    return answers


def main() -> None:
    _limit_resources()
    request = json.loads(sys.stdin.read())
    answers = parse_items(str(request["platform"]), request["items"])
    sys.stdout.write(json.dumps({"ok": True, "result": answers}, default=str))


if __name__ == "__main__":
    main()
