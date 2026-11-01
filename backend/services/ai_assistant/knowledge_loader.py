"""One loader for the assistant's knowledge files (doc/AI_TOOL_CHAIN.md §25.10 (1)).

A knowledge file is a built-in markdown file in ``knowledge/`` plus an optional local overlay,
``${DATA_DIRECTORY}/ai/knowledge/<name>.local.md``, written by the operator. The overlay is
placed first, under a "Local additions" heading. Playbooks (``playbooks.py``) read their files
through the same cached reader.

Rules:

* A path is built here from a plain identifier (``[a-z][a-z0-9_]*``) the *code* passes. Nothing the
  model sends ever reaches this module.
* A missing local file or directory is "nothing". A missing built-in file is a packaging error and
  raises, as before.
* Files are opened without following symlinks and must be regular files: a link to some other file
  is not read, and a FIFO cannot block the worker.
* Text must be valid UTF-8 (a character cut in half by the size cap is dropped, bad bytes are not
  repaired).
* The combined text is capped at the tool output cap (20,000 characters, ``tools/base.py``), which
  would otherwise cut the *end*. The local overlay therefore comes first (at most
  ``MAX_OVERLAY_CHARS``) and the built-in tail is the part that is cut, with a marker.
* Reads are cached by ``(path, mtime, size)``, so an edit is live without a restart.
"""

from __future__ import annotations

import codecs
import logging
import os
import re
import stat
from pathlib import Path
from typing import BinaryIO

from core.config import settings

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"
LOCAL_HEADING = "## Local additions"
MAX_FILE_CHARS = 20_000
# Equal to ``tools.base.MAX_TOOL_OUTPUT_CHARS`` (pinned by a test): the model's view is cut there.
MAX_COMBINED_CHARS = 20_000
MAX_OVERLAY_CHARS = 8_000

_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
_TRUNCATION_MARKER = "\n…[file truncated: limit {limit} characters]"
_OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)

# path -> (mtime_ns, size, max_chars, text). Replaced per path, never mutated in place.
_cache: dict[Path, tuple[int, int, int, str]] = {}


class NotRegularFileError(OSError):
    """The path is a FIFO, device or socket (a symlink fails earlier, in ``os.open``)."""


def clear_cache() -> None:
    _cache.clear()


def local_knowledge_dir() -> Path:
    return settings.data_directory / "ai" / "knowledge"


def local_playbook_dir() -> Path:
    return settings.data_directory / "ai" / "playbooks"


def _read_file(handle: BinaryIO, max_chars: int) -> str:
    """Read at most ``max_chars`` characters; raises ``UnicodeDecodeError`` on bad bytes."""
    # Four bytes per character is the UTF-8 maximum, so the byte cap never cuts a limit short.
    limit = max_chars * 4
    data = handle.read(limit + 1)
    cut_bytes = len(data) > limit
    # With ``final=False`` a character split by the byte cap is held back, not an error.
    text = codecs.getincrementaldecoder("utf-8")().decode(data[:limit], final=not cut_bytes)
    if cut_bytes or len(text) > max_chars:
        return text[:max_chars] + _TRUNCATION_MARKER.format(limit=max_chars)
    return text


def read_cached(path: Path, max_chars: int = MAX_FILE_CHARS) -> str:
    """The file's text, re-read only when its mtime or size changed. Raises on a missing file.

    The file is opened without following a symlink and must be a regular file; the cache check
    uses the open descriptor, so a swap between check and read cannot slip through.
    """
    fd = os.open(path, _OPEN_FLAGS)
    try:
        info = os.fstat(fd)
        if stat.S_ISDIR(info.st_mode):
            raise IsADirectoryError(path.name)
        if not stat.S_ISREG(info.st_mode):
            raise NotRegularFileError(f"{path.name} is not a regular file")
        hit = _cache.get(path)
        if hit is not None and hit[:3] == (info.st_mtime_ns, info.st_size, max_chars):
            return hit[3]
        with os.fdopen(fd, "rb", closefd=False) as handle:
            text = _read_file(handle, max_chars)
    finally:
        os.close(fd)
    _cache[path] = (info.st_mtime_ns, info.st_size, max_chars, text)
    return text


def read_optional(path: Path, max_chars: int = MAX_FILE_CHARS) -> str:
    """Like ``read_cached`` but a missing or unreadable file is empty (unreadable: logged)."""
    try:
        return read_cached(path, max_chars)
    except FileNotFoundError, NotADirectoryError, IsADirectoryError:
        _cache.pop(path, None)
        return ""
    except OSError, UnicodeDecodeError:
        _cache.pop(path, None)
        logger.warning("AI assistant knowledge file %s could not be read; ignoring it", path.name)
        return ""


def _cut(text: str, room: int) -> str:
    if len(text) <= room:
        return text
    marker = _TRUNCATION_MARKER.format(limit=MAX_COMBINED_CHARS)
    return text[: max(room - len(marker), 0)] + marker


def load_knowledge(
    name: str, *, builtin_dir: Path = KNOWLEDGE_DIR, local_dir: Path | None = None
) -> str:
    """The local overlay (``<name>.local.md``, first) and the built-in ``<name>.md``."""
    if not _NAME.fullmatch(name):
        raise ValueError(f"invalid knowledge file name: {name!r}")
    base = read_cached(builtin_dir / f"{name}.md")
    overlay_dir = local_knowledge_dir() if local_dir is None else local_dir
    overlay = read_optional(overlay_dir / f"{name}.local.md").strip()
    if not overlay:
        return base
    head = f"{LOCAL_HEADING}\n\n{_cut(overlay, MAX_OVERLAY_CHARS)}\n\n"
    return head + _cut(base, MAX_COMBINED_CHARS - len(head))
