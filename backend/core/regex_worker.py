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
MAX_CPU_SECONDS = 30  # upper bound of the optional first argument (the step jobs pass 10)
MEMORY_BYTES = 512 * 1024 * 1024
_log = logging.getLogger("regex_worker")


def _cpu_seconds(argv: list[str]) -> int:
    """The CPU limit: ``CPU_SECONDS``, or the first argument within 1..``MAX_CPU_SECONDS``."""
    if not argv:
        return CPU_SECONDS
    try:
        return min(max(int(argv[0]), 1), MAX_CPU_SECONDS)
    except ValueError:
        return CPU_SECONDS


def _limit_resources(cpu_seconds: int) -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    except ImportError, ValueError, OSError:
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
                except re.error, RecursionError, OverflowError:
                    entry = "invalid"
                compiled[pattern] = entry
            if isinstance(entry, str):
                results.append(entry)
            else:
                match = entry.fullmatch if item["mode"] == "full" else entry.search
                results.append(match(item["text"]) is not None)
        except _ItemTimeout, MemoryError:
            results.append("stopped")
        finally:
            if timed:
                signal.setitimer(signal.ITIMER_REAL, 0)
    return results


def _match_any(request: dict) -> list[bool | str]:
    """For each text: ``True`` when any of the patterns is found in it, else ``False``.

    ``ignore_case`` applies to all patterns. A pattern that does not compile fails the whole
    request (``ValueError``: the caller validated it, so this is a bug or a mismatch). A text that
    takes too long answers ``"stopped"`` (and so does every text after the batch budget): the
    caller must not treat that as "no match". Answers never echo a pattern or a text.
    """
    import re
    import signal
    import time

    flags = re.IGNORECASE if request.get("ignore_case") else 0
    try:
        compiled = [re.compile(p, flags) for p in request["patterns"] if p]
    except (re.error, RecursionError, OverflowError) as exc:
        raise ValueError("invalid pattern") from exc
    timed = hasattr(signal, "setitimer")
    if timed:
        signal.signal(signal.SIGALRM, _on_alarm)
    deadline = time.monotonic() + BATCH_SECONDS
    results: list[bool | str] = []
    for text in request["texts"]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            results.append("stopped")
            continue
        if timed:
            signal.setitimer(signal.ITIMER_REAL, min(ITEM_SECONDS, remaining))
        try:
            results.append(any(p.search(text) is not None for p in compiled))
        except _ItemTimeout, MemoryError:
            results.append("stopped")
        finally:
            if timed:
                signal.setitimer(signal.ITIMER_REAL, 0)
    return results


def _search_lines(regex, request: dict) -> list[dict]:
    """For each ``{id, text}``: the first ``max_lines`` lines (1-based number, line cut to 200
    characters) where the pattern is found. An item that takes too long gets ``stopped: true``
    and no lines; the rest of the batch is still answered. Answers never echo the pattern."""
    import signal
    import time

    flags = regex.RegexFlagsConfig.from_mapping(request.get("flags") or {})
    compiled = regex.compile_pattern(request["pattern"], flags)  # ValueError: invalid pattern
    max_lines = int(request.get("max_lines", 3))
    timed = hasattr(signal, "setitimer")
    if timed:
        signal.signal(signal.SIGALRM, _on_alarm)
    deadline = time.monotonic() + BATCH_SECONDS
    results: list[dict] = []
    for item in request["items"]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            results.append({"id": item["id"], "lines": [], "stopped": True})
            continue
        if timed:
            signal.setitimer(signal.ITIMER_REAL, min(ITEM_SECONDS, remaining))
        try:
            lines: list[list] = []
            for number, line in enumerate(item["text"].splitlines(), start=1):
                if compiled.search(line):
                    lines.append([number, line[:200]])
                    if len(lines) >= max_lines:
                        break
            results.append({"id": item["id"], "lines": lines})
        except _ItemTimeout, MemoryError:
            results.append({"id": item["id"], "lines": [], "stopped": True})
        finally:
            if timed:
                signal.setitimer(signal.ITIMER_REAL, 0)
    return results


def _search_many(regex, request: dict) -> list[dict]:
    """For each ``{text, pattern}``: ``{status, match, groups}``.

    ``status`` is ``match``, ``nomatch``, ``invalid`` (empty or bad pattern) or ``stopped``
    (took too long). ``match`` and every group are cut to ``max_text`` characters. A bad or slow
    pattern only spoils its own answer; answers never echo the pattern.
    """
    import re
    import signal
    import time

    flags = regex.RegexFlagsConfig.from_mapping(request.get("flags") or {})
    max_text = int(request.get("max_text", 200))
    timed = hasattr(signal, "setitimer")
    if timed:
        signal.signal(signal.SIGALRM, _on_alarm)
    deadline = time.monotonic() + BATCH_SECONDS
    compiled: dict[str, re.Pattern[str] | str] = {}
    results: list[dict] = []
    for item in request["items"]:
        pattern = item["pattern"]
        remaining = deadline - time.monotonic()
        if not pattern:
            results.append({"status": "invalid"})
            continue
        if remaining <= 0:
            results.append({"status": "stopped"})
            continue
        if timed:
            signal.setitimer(signal.ITIMER_REAL, min(ITEM_SECONDS, remaining))
        try:
            entry = compiled.get(pattern)
            if entry is None:
                try:
                    entry = regex.compile_pattern(pattern, flags)
                except ValueError, RecursionError, OverflowError:
                    entry = "invalid"
                compiled[pattern] = entry
            if isinstance(entry, str):
                results.append({"status": entry})
                continue
            found = entry.search(item["text"])
            if found is None:
                results.append({"status": "nomatch"})
            else:
                results.append(
                    {
                        "status": "match",
                        "match": found.group(0)[:max_text],
                        "groups": [None if g is None else g[:max_text] for g in found.groups()],
                    }
                )
        except _ItemTimeout, MemoryError:
            results.append({"status": "stopped"})
        finally:
            if timed:
                signal.setitimer(signal.ITIMER_REAL, 0)
    return results


def _replace_many(regex, request: dict) -> dict:
    """Apply ``rules`` (``{pattern, replacement, flags, replace_all}``) in order to ``text``.

    ``{"too_large": True}`` when the text grows above ``max_chars`` after a rule; otherwise
    ``{"updated_text", "match_counts"}``. A bad replacement template is a ``ValueError`` with the
    text of ``attribute_regex`` (no pattern or content in it)."""
    text = request["text"]
    max_chars = int(request["max_chars"])
    counts: list[int] = []
    for rule in request["rules"]:
        text, count = regex.apply_regex_content_replace(
            source_text=text,
            pattern=rule["pattern"],
            replacement=rule["replacement"],
            flags=regex.RegexFlagsConfig.from_mapping(rule.get("flags") or {}),
            replace_all=bool(rule.get("replace_all", True)),
        )
        if len(text) > max_chars:
            return {"too_large": True}
        counts.append(count)
    return {"updated_text": text, "match_counts": counts}


def main() -> None:
    _limit_resources(_cpu_seconds(sys.argv[1:]))
    request = json.loads(sys.stdin.buffer.read())
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
        elif request["op"] == "search_lines":
            result = _search_lines(regex, request)
        elif request["op"] == "search_many":
            result = _search_many(regex, request)
        elif request["op"] == "match_any":
            result = _match_any(request)
        elif request["op"] == "match_many":
            result = _match_many(request["items"])
        elif request["op"] == "replace_many":
            result = _replace_many(regex, request)
        else:
            raise ValueError("unknown operation")
    except ValueError as exc:
        _write({"ok": False, "error": str(exc)})
        return
    _write({"ok": True, "result": result})


def _write(answer: dict) -> None:
    # Bytes, not the text stream: the empty environment leaves the stream encoding to the locale.
    sys.stdout.buffer.write(json.dumps(answer, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    main()
