"""Tests for the source snapshot of upload-binary."""

from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow_steps.upload_binary import source_file
from workflow_steps.upload_binary.source_file import parse_expected_md5, snapshot_source_file

LFS_POINTER = (
    b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"a" * 64 + b"\nsize 123456789\n"
)


class ParseExpectedMd5Tests(unittest.TestCase):
    def test_empty_is_none_and_value_is_normalised(self) -> None:
        self.assertIsNone(parse_expected_md5("  ", step_id="s"))
        self.assertIsNone(parse_expected_md5(None, step_id="s"))
        self.assertEqual(parse_expected_md5(" " + "AB" * 16 + " ", step_id="s"), "ab" * 16)

    def test_malformed_value_is_refused(self) -> None:
        for bad in ("abc", "g" * 32, "a" * 33):
            with self.assertRaises(ValueError):
                parse_expected_md5(bad, step_id="s")


class SnapshotSourceFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name).resolve()  # macOS: /var -> /private/var
        self.root = base / "repo"
        self.scratch = base / "scratch"  # where the snapshot lands: must be empty after a failure
        self.scratch.mkdir()
        (self.root / "images").mkdir(parents=True)
        (self.root / ".git").mkdir()
        patcher = patch.object(tempfile, "tempdir", str(self.scratch))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write(self, relative: str, data: bytes) -> Path:
        path = self.root / relative
        path.write_bytes(data)
        return path

    def _snapshot(self, relative: str, **kwargs):
        return snapshot_source_file(self.root, relative, step_id="s", **kwargs)

    def _assert_nothing_left(self) -> None:
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_copy_has_the_same_bytes_and_the_md5_of_what_was_copied(self) -> None:
        data = b"\x00\xff\xfe" * (1024 * 1024 // 3 * 2 + 5)  # > one chunk, not valid UTF-8
        original = self._write("images/c.bin", data)
        snap = self._snapshot("images/c.bin")
        self.addCleanup(snap.path.unlink, missing_ok=True)

        self.assertNotEqual(snap.path, original)
        self.assertEqual(snap.path.read_bytes(), data)
        self.assertEqual(snap.size_bytes, len(data))
        self.assertEqual(snap.md5, hashlib.md5(data).hexdigest())  # noqa: S324
        self.assertEqual(snap.path.stat().st_mode & 0o077, 0)  # private to this user

    def test_later_change_of_the_checkout_does_not_reach_the_snapshot(self) -> None:
        original = self._write("images/c.bin", b"original bytes")
        snap = self._snapshot("images/c.bin")
        self.addCleanup(snap.path.unlink, missing_ok=True)
        original.write_bytes(b"swapped bytes!")
        self.assertEqual(snap.path.read_bytes(), b"original bytes")

    def test_escape_git_dir_and_missing_are_refused(self) -> None:
        self._write("images/c.bin", b"x")
        for bad in ("../outside.bin", "images/../../x", ".git/config", "images/nope.bin", "a\x00b"):
            with self.assertRaises(ValueError, msg=bad):
                self._snapshot(bad)
        self._assert_nothing_left()

    def test_symlinked_file_and_symlinked_directory_are_refused(self) -> None:
        target = self._write("images/real.bin", b"data")
        os.symlink(target, self.root / "images" / "link.bin")
        os.symlink(self.root / "images", self.root / "linkdir")
        for bad in ("images/link.bin", "linkdir/real.bin"):
            with self.assertRaises(ValueError, msg=bad):
                self._snapshot(bad)
        self._assert_nothing_left()

    def test_directory_empty_and_oversized_files_are_refused(self) -> None:
        self._write("images/empty.bin", b"")
        self._write("images/big.bin", b"x" * 100)
        for bad, kwargs in (
            ("images", {}),
            ("images/empty.bin", {}),
            ("images/big.bin", {"max_bytes": 99}),
        ):
            with self.assertRaises(ValueError, msg=bad):
                self._snapshot(bad, **kwargs)
        self.assertEqual(self._snapshot("images/big.bin", max_bytes=100).size_bytes, 100)
        self._assert_nothing_left_except_snapshot()

    def _assert_nothing_left_except_snapshot(self) -> None:
        for leftover in self.scratch.iterdir():
            leftover.unlink()

    def test_git_lfs_pointer_is_refused_with_a_hint_and_leaves_no_copy(self) -> None:
        self._write("images/lfs.bin", LFS_POINTER)
        with self.assertRaises(ValueError) as ctx:
            self._snapshot("images/lfs.bin")
        self.assertIn("LFS", str(ctx.exception))
        self._assert_nothing_left()

    def test_small_real_file_starting_differently_is_not_taken_for_a_pointer(self) -> None:
        self._write("images/small.bin", b"version 1\n")
        snap = self._snapshot("images/small.bin")
        self.addCleanup(snap.path.unlink, missing_ok=True)
        self.assertEqual(snap.path.read_bytes(), b"version 1\n")

    def test_file_that_changes_while_it_is_read_is_refused(self) -> None:
        self._write("images/c.bin", b"some bytes")
        real = source_file._signature
        calls = iter([real, lambda info: (0, 0, 0)])

        def _signature(info):
            return next(calls)(info)

        with patch.object(source_file, "_signature", side_effect=_signature):
            with self.assertRaisesRegex(ValueError, "changed"):
                self._snapshot("images/c.bin")
        self._assert_nothing_left()
