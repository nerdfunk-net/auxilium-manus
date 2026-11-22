"""Take a private snapshot of the binary an ``upload-binary`` step copies out of a git checkout.

The checkout is shared and the copy to a device can take minutes, so the step never sends the
checkout file itself. The file is opened once, every path component with ``O_NOFOLLOW`` (a link
swapped in after any check is refused), checked on that descriptor, and copied to a private
temporary file while its MD5 is computed. The MD5, ``expected_md5`` and the bytes sent to the
device are therefore all of the same single read, and the repository lease can be released
before the first device is contacted.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from services.git.safe_read import SafeReadError, open_file_under

# Git LFS stores a large file as a ~130 byte text pointer; the real bytes are fetched separately.
# Copying the pointer to a device would "succeed" and break the boot image, so it is refused.
_LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/"
_LFS_POINTER_MAX_BYTES = 1024
_MD5_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_CHUNK_BYTES = 1024 * 1024

# Ceiling for one file: larger than any Cisco image, small enough that a wrong path (a
# repository archive, a disk image) fails before it fills the disk or holds a worker.
MAX_BINARY_BYTES = 4 * 1024**3

_SAFE_READ_MESSAGES = {
    "outside": "source_path must stay inside the repository (no '..', no '.git')",
    "symlink": "source_path must not go through a symbolic link",
    "unreadable": "source_path could not be read",
    "missing": "source_path does not exist in the repository",
}


@dataclass(frozen=True)
class SourceSnapshot:
    """A private copy of the file. The caller deletes ``path`` when the step is done."""

    path: Path
    size_bytes: int
    md5: str

    def discard(self) -> None:
        """Remove the private copy (safe to call twice)."""
        self.path.unlink(missing_ok=True)


def parse_expected_md5(raw: object, *, step_id: str) -> str | None:
    """The optional vendor checksum: 32 hex characters (case and surrounding space ignored)."""
    value = str(raw or "").strip().lower()
    if not value:
        return None
    if not _MD5_PATTERN.match(value):
        raise ValueError(f"{step_id}: expected_md5 must be 32 hexadecimal characters")
    return value


def _signature(info: os.stat_result) -> tuple[int, int, int]:
    return info.st_ino, info.st_size, info.st_mtime_ns


def _check_descriptor(fd: int, *, step_id: str, max_bytes: int) -> os.stat_result:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"{step_id}: source_path is not a regular file")
    if info.st_size == 0:
        raise ValueError(f"{step_id}: source_path is an empty file")
    if info.st_size > max_bytes:
        raise ValueError(
            f"{step_id}: source_path is larger than the limit of {max_bytes} bytes "
            f"({info.st_size} bytes)"
        )
    return info


def _copy_and_hash(fd: int, out: tempfile._TemporaryFileWrapper, *, size: int, step_id: str) -> str:
    """Stream ``fd`` into ``out`` and return the MD5 of exactly what was written."""
    digest = hashlib.md5(usedforsecurity=False)  # Cisco's `verify /md5`; not a security control
    copied = 0
    with os.fdopen(os.dup(fd), "rb") as source:
        while chunk := source.read(_CHUNK_BYTES):
            if (
                copied == 0
                and size <= _LFS_POINTER_MAX_BYTES
                and chunk.startswith(_LFS_POINTER_PREFIX)
            ):
                raise ValueError(
                    f"{step_id}: source_path is a Git LFS pointer, not the file itself; the "
                    "repository checkout does not contain the real bytes (fetch them with git "
                    "lfs or store the file without LFS)"
                )
            out.write(chunk)
            digest.update(chunk)
            copied += len(chunk)
    out.flush()
    if copied != size:
        raise ValueError(f"{step_id}: source_path changed while it was being read")
    return digest.hexdigest()


def snapshot_source_file(
    root: Path, source_path: str, *, step_id: str, max_bytes: int = MAX_BINARY_BYTES
) -> SourceSnapshot:
    """Copy ``root / source_path`` to a private temporary file and return it with its MD5.

    Blocking (a large file): call it from a worker thread. Raises ``ValueError`` (the step cannot
    run) for a path that leaves the repository or crosses a link, a missing, empty, oversized or
    non-regular file, a Git LFS pointer, or a file that changed while it was read. The temporary
    file is removed again when anything fails.
    """
    try:
        with open_file_under(root, source_path) as fd:
            before = _check_descriptor(fd, step_id=step_id, max_bytes=max_bytes)
            tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115  # kept open past the with-block
                prefix="upload-binary-", suffix=".bin", delete=False
            )
            try:
                with tmp:
                    md5 = _copy_and_hash(fd, tmp, size=before.st_size, step_id=step_id)
                if _signature(os.fstat(fd)) != _signature(before):
                    raise ValueError(f"{step_id}: source_path changed while it was being read")
            except BaseException:
                Path(tmp.name).unlink(missing_ok=True)
                raise
    except SafeReadError as exc:
        raise ValueError(f"{step_id}: {_SAFE_READ_MESSAGES.get(exc.code, exc.code)}") from exc
    return SourceSnapshot(path=Path(tmp.name), size_bytes=before.st_size, md5=md5)
