"""Read a file from a checked-out repository without ever following a link out of it.

Used by the assistant's git readers (config backups, the CSV comparison). Every path component
below the root is checked with ``lstat`` before anything is resolved, a file is opened with
``O_NOFOLLOW`` and must be a regular file, and the text must be strict UTF-8. Errors carry a short
``code`` so each caller words its own message (no path or file content in an error).
"""

from __future__ import annotations

import codecs
import errno
import logging
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)
_OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
GIT_DIR = ".git"


class SafeReadError(Exception):
    """``code``: outside, symlink, missing, unreadable, not_regular, not_utf8, too_large,
    too_many_files."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def contain(root: Path, relative: str) -> Path:
    """``root / relative``; refuses a path that leaves ``root``, enters ``.git`` or crosses a link.

    A symlink (a file or a directory) is refused even when it points at another file in the same
    checkout: the bytes of one file must not be reported as another's.
    """
    resolved_root = root.resolve()
    candidate = resolved_root / relative
    try:
        parts = candidate.relative_to(resolved_root).parts
    except ValueError as exc:
        raise SafeReadError("outside") from exc
    if ".." in parts or GIT_DIR in parts:
        raise SafeReadError("outside")
    current = resolved_root
    for part in parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            break  # the rest does not exist; the read reports a missing file
        except OSError as exc:
            raise SafeReadError("unreadable") from exc
        if stat.S_ISLNK(mode):
            raise SafeReadError("symlink")
    return candidate


def cut_on_line(text: str, limit: int) -> str:
    """At most ``limit`` characters, ending on a line boundary when one is near the end, so a
    one-line secret is never split before redaction."""
    head = text[:limit]
    newline = head.rfind("\n")
    return head[:newline] if newline > limit // 2 else head


def _read_regular_file(fd: int, *, max_chars: int, max_bytes: int | None) -> tuple[str, bool]:
    """``(text, truncated)`` from an open descriptor (the caller closes it)."""
    try:
        info = os.fstat(fd)
        if stat.S_ISDIR(info.st_mode):
            raise SafeReadError("missing")
        if not stat.S_ISREG(info.st_mode):
            raise SafeReadError("not_regular")
        # Four bytes per character is the UTF-8 maximum, so the character cap never cuts a limit
        # short. A byte cap is a separate, hard ceiling: a file above it is refused, never cut.
        limit = max_chars * 4
        if max_bytes is not None:
            if info.st_size > max_bytes:
                raise SafeReadError("too_large")
            limit = min(limit, max_bytes)
        with os.fdopen(fd, "rb", closefd=False) as handle:
            data = handle.read(limit + 1)
    except OSError as exc:
        raise SafeReadError("unreadable") from exc
    if max_bytes is not None and len(data) > max_bytes:
        raise SafeReadError("too_large")  # the file grew while it was read
    cut_bytes = len(data) > limit
    try:
        # With ``final=False`` a character split by the byte cap is held back, not an error.
        text = codecs.getincrementaldecoder("utf-8")().decode(data[:limit], final=not cut_bytes)
    except UnicodeDecodeError as exc:
        raise SafeReadError("not_utf8") from exc
    if cut_bytes or len(text) > max_chars:
        return cut_on_line(text, max_chars), True
    return text, False


def read_text_file(
    target: Path, *, max_chars: int, max_bytes: int | None = None
) -> tuple[str, bool]:
    """``(text, truncated)``: a regular file (no symlink), strict UTF-8, ``max_chars`` at most.

    ``max_bytes`` (optional) refuses a larger file instead of cutting it.
    """
    try:
        fd = os.open(target, _OPEN_FLAGS)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise SafeReadError("missing") from exc
    except OSError as exc:  # includes a symlink, refused by O_NOFOLLOW
        raise SafeReadError("unreadable") from exc
    try:
        return _read_regular_file(fd, max_chars=max_chars, max_bytes=max_bytes)
    finally:
        os.close(fd)


def _components(relative: str) -> list[str]:
    parts = relative.split("/")
    if not relative or "\x00" in relative or any(p in ("", ".", "..", GIT_DIR) for p in parts):
        raise SafeReadError("outside")
    return parts


def _open_at(name: str, *, dir_fd: int, flags: int) -> int:
    try:
        return os.open(name, flags, dir_fd=dir_fd)
    except OSError as exc:
        if exc.errno == errno.ELOOP:  # O_NOFOLLOW met a symlink
            raise SafeReadError("symlink") from exc
        if exc.errno in (errno.ENOENT, errno.ENOTDIR):
            raise SafeReadError("missing") from exc
        raise SafeReadError("unreadable") from exc


@contextmanager
def open_file_under(root: Path, relative: str) -> Iterator[int]:
    """Yield a read-only descriptor of ``root / relative``, never following a link.

    Every component is opened with ``O_NOFOLLOW`` relative to the descriptor of its parent, so a
    directory replaced by a symlink after any ``contain`` check is refused as well. The caller
    checks the type (``fstat``) and reads from the descriptor; all descriptors close on exit.
    """
    parts = _components(relative)
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        current = os.open(root.resolve(), os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    except OSError as exc:
        raise SafeReadError("unreadable") from exc
    opened = [current]
    try:
        for part in parts[:-1]:
            current = _open_at(part, dir_fd=current, flags=flags)
            opened.append(current)
            if not stat.S_ISDIR(os.fstat(current).st_mode):
                raise SafeReadError("missing")
        fd = _open_at(parts[-1], dir_fd=current, flags=_OPEN_FLAGS)
        opened.append(fd)
        yield fd
    finally:
        for descriptor in opened:
            os.close(descriptor)


def read_text_under(
    root: Path, relative: str, *, max_chars: int, max_bytes: int | None = None
) -> tuple[str, bool]:
    """Read ``root / relative`` without ever following a link, even one swapped in meanwhile.

    ``contain`` checks the path with ``lstat`` first, which leaves a window before the open;
    ``open_file_under`` closes it. Same result and caps as ``read_text_file``.
    """
    with open_file_under(root, relative) as fd:
        return _read_regular_file(fd, max_chars=max_chars, max_bytes=max_bytes)


def find_files_named(
    root: Path,
    name: str,
    *,
    suffixes: tuple[str, ...],
    max_entries: int = 20_000,
    max_depth: int = 8,
) -> list[str]:
    """Sorted relative paths of regular files called ``name`` (exact, case-sensitive).

    Skips ``.git`` and every symlink (files and directories), looks at most ``max_depth`` levels
    down and raises ``SafeReadError("too_many_files")`` after ``max_entries`` entries, so a huge
    repository cannot keep a worker busy. The name must end in one of ``suffixes``.
    """
    if not name.lower().endswith(suffixes):
        return []
    base = root.resolve()
    found: list[str] = []
    seen = 0
    stack: list[tuple[Path, int]] = [(base, 0)]
    while stack:
        directory, depth = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            logger.debug("safe_read: a directory could not be listed")
            continue
        for entry in entries:
            seen += 1
            if seen > max_entries:
                raise SafeReadError("too_many_files")
            if entry.name == GIT_DIR or entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                if depth < max_depth:
                    stack.append((Path(entry.path), depth + 1))
            elif entry.name == name and entry.is_file(follow_symlinks=False):
                found.append(Path(entry.path).relative_to(base).as_posix())
    return sorted(found)
