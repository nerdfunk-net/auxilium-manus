"""Child process for ``core.regex_isolated``: one regex job, then exit.

Reads ``{"op", ...}`` as JSON on stdin and writes ``{"ok", "result" | "error"}`` as JSON on stdout.
Run with ``python -I`` and an EMPTY environment: it imports nothing from the project except
``attribute_regex`` (pure standard library), loaded by path. A regex match holds the GIL, so a
catastrophic pattern would stall the whole API process if it ran in-process; here the operating
system stops it (CPU limit) and the parent kills it on timeout.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import logging
import sys
from pathlib import Path

CPU_SECONDS = 2
MEMORY_BYTES = 512 * 1024 * 1024
_log = logging.getLogger("regex_worker")


def _limit_resources() -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS + 1))
    except (ImportError, ValueError, OSError):
        _log.warning("could not set the CPU limit for the regex worker")
    with contextlib.suppress(ImportError, ValueError, OSError):
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))


def _load_attribute_regex():
    backend = Path(__file__).resolve().parent.parent
    path = backend / "services" / "workflow_context" / "attribute_regex.py"
    spec = importlib.util.spec_from_file_location("_attribute_regex", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_attribute_regex"] = module
    spec.loader.exec_module(module)
    return module


class _ItemTimeout(Exception):
    """Raised from the SIGALRM handler when one question takes too long."""


def _on_alarm(signum: int, frame: object) -> None:
    raise _ItemTimeout


ITEM_SECONDS = 0.25  # one question; re checks for signals while it matches
BATCH_SECONDS = 1.5  # all questions of a batch, inside the parent's 2 s timeout


def _match_many(items: list[dict]) -> list[bool | str]:
    """Answer each ``{text, pattern, mode}``: ``True``/``False``, ``"invalid"`` or ``"stopped"``.

    ``mode`` is "full" (whole string) or "find" (anywhere). A bad or slow pattern only spoils its
    own answer; the rest of the batch is still answered. The empty pattern is "invalid": as a
    search it would match every value. Answers never echo the pattern or the text.
    """
    import re
    import signal
    import time

    timed = hasattr(signal, "setitimer")
    if timed:
        signal.signal(signal.SIGALRM, _on_alarm)
    deadline = time.monotonic() + BATCH_SECONDS
    compiled: dict[str, re.Pattern[str] | str] = {}
    results: list[bool | str] = []
    for item in items:
        pattern = item["pattern"]
        remaining = deadline - time.monotonic()
        if not pattern:
            results.append("invalid")
            continue
        if remaining <= 0:
            results.append("stopped")
            continue
        if timed:
            signal.setitimer(signal.ITIMER_REAL, min(ITEM_SECONDS, remaining))
        try:
            entry = compiled.get(pattern)
            if entry is None:
                try:
                    entry = re.compile(pattern)
                except (re.error, RecursionError, OverflowError):
                    entry = "invalid"
                compiled[pattern] = entry
            if isinstance(entry, str):
                results.append(entry)
            else:
                match = entry.fullmatch if item["mode"] == "full" else entry.search
                results.append(match(item["text"]) is not None)
        except (_ItemTimeout, MemoryError):
            results.append("stopped")
        finally:
            if timed:
                signal.setitimer(signal.ITIMER_REAL, 0)
    return results


def main() -> None:
    _limit_resources()
    request = json.load(sys.stdin)
    regex = _load_attribute_regex()
    flags = regex.RegexFlagsConfig.from_mapping(request.get("flags") or {})
    try:
        if request["op"] == "replace":
            text, count = regex.apply_regex_content_replace(
                source_text=request["text"],
                pattern=request["pattern"],
                replacement=request["replacement"],
                flags=flags,
                replace_all=bool(request.get("replace_all", True)),
            )
            result: object = {"updated_text": text, "match_count": count}
        elif request["op"] == "probe":
            result = regex.probe_regex_transform(
                source_text=request["text"],
                pattern=request["pattern"],
                destination_template=request["destination_template"],
                flags=flags,
            )
        elif request["op"] == "match_many":
            result = _match_many(request["items"])
        else:
            raise ValueError("unknown operation")
    except ValueError as exc:
        json.dump({"ok": False, "error": str(exc)}, sys.stdout)
        return
    json.dump({"ok": True, "result": result}, sys.stdout)


if __name__ == "__main__":
    main()
