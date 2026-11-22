"""Tests for the symlink-free, contained file read shared by the assistant's git readers."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from services.git import safe_read as sr


@pytest.mark.parametrize("relative", ["../x", "/etc/passwd", ".git/config", "a/../../x"])
def test_contain_refuses_escapes(tmp_path: Path, relative: str) -> None:
    with pytest.raises(sr.SafeReadError) as info:
        sr.contain(tmp_path, relative)
    assert info.value.code == "outside"


def test_contain_accepts_a_path_that_does_not_exist_yet(tmp_path: Path) -> None:
    assert sr.contain(tmp_path, "a/b.csv") == tmp_path.resolve() / "a" / "b.csv"


def test_contain_refuses_a_symlinked_file_and_directory(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "f.csv").write_text("x")
    os.symlink(tmp_path / "real", tmp_path / "dirlink")
    os.symlink(tmp_path / "real" / "f.csv", tmp_path / "filelink.csv")
    for relative in ("dirlink/f.csv", "filelink.csv"):
        with pytest.raises(sr.SafeReadError) as info:
            sr.contain(tmp_path, relative)
        assert info.value.code == "symlink"


def test_read_text_file(tmp_path: Path) -> None:
    real = tmp_path / "real.csv"
    real.write_text("serial;data\n1;a\n", encoding="utf-8")
    assert sr.read_text_file(real, max_chars=1000) == ("serial;data\n1;a\n", False)


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("link.csv", "unreadable"),
        ("dir", "missing"),
        ("bad.csv", "not_utf8"),
        ("nope.csv", "missing"),
    ],
)
def test_read_text_file_refusals(tmp_path: Path, name: str, code: str) -> None:
    (tmp_path / "real.csv").write_text("x")
    os.symlink(tmp_path / "real.csv", tmp_path / "link.csv")
    (tmp_path / "dir").mkdir()
    (tmp_path / "bad.csv").write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(sr.SafeReadError) as info:
        sr.read_text_file(tmp_path / name, max_chars=1000)
    assert info.value.code == code


def test_a_fifo_is_not_a_regular_file(tmp_path: Path) -> None:
    fifo = tmp_path / "pipe.csv"
    os.mkfifo(fifo)
    with pytest.raises(sr.SafeReadError) as info:
        sr.read_text_file(fifo, max_chars=1000)
    assert info.value.code == "not_regular"


def test_a_file_over_the_cap_is_cut_on_a_line_and_flagged(tmp_path: Path) -> None:
    path = tmp_path / "big.csv"
    path.write_text("line of text\n" * 20, encoding="utf-8")
    text, truncated = sr.read_text_file(path, max_chars=100)
    assert truncated and len(text) <= 100
    assert text.endswith("line of text")


def test_cut_on_line_only_uses_a_newline_near_the_end() -> None:
    assert sr.cut_on_line("aaaaa\nbbbbb", 8) == "aaaaa"  # newline at 5 > 4: cut there
    assert sr.cut_on_line("abc\ndefghij", 6) == "abc\nde"  # newline too early: keep the head
    assert sr.cut_on_line("a" * 10, 4) == "aaaa"


def _tree(root: Path) -> None:
    (root / "a").mkdir()
    (root / "a" / "compare.csv").write_text("x")
    (root / "b" / "deep").mkdir(parents=True)
    (root / "b" / "deep" / "compare.csv").write_text("x")
    (root / "b" / "other.csv").write_text("x")
    (root / ".git").mkdir()
    (root / ".git" / "compare.csv").write_text("x")
    (root / "real").mkdir()
    os.symlink(root / "real", root / "linked")
    (root / "real" / "compare.csv").write_text("x")
    os.symlink(root / "a" / "compare.csv", root / "alias.csv")


def test_find_files_named_returns_sorted_relative_paths(tmp_path: Path) -> None:
    _tree(tmp_path)
    found = sr.find_files_named(tmp_path, "compare.csv", suffixes=(".csv",))
    # no .git, no symlinked directory, sorted
    assert found == ["a/compare.csv", "b/deep/compare.csv", "real/compare.csv"]


def test_find_files_named_is_exact_and_filters_the_suffix(tmp_path: Path) -> None:
    _tree(tmp_path)
    assert sr.find_files_named(tmp_path, "COMPARE.CSV", suffixes=(".csv",)) == []
    assert sr.find_files_named(tmp_path, "compare.csv", suffixes=(".txt",)) == []


def test_find_files_named_skips_symlinked_files(tmp_path: Path) -> None:
    _tree(tmp_path)
    assert "alias.csv" not in sr.find_files_named(tmp_path, "alias.csv", suffixes=(".csv",))


def test_find_files_named_caps_entries_and_depth(tmp_path: Path) -> None:
    for i in range(5):
        (tmp_path / f"f{i}.csv").write_text("x")
    with pytest.raises(sr.SafeReadError) as info:
        sr.find_files_named(tmp_path, "x.csv", suffixes=(".csv",), max_entries=3)
    assert info.value.code == "too_many_files"
    deep = tmp_path / "d1" / "d2" / "d3"
    deep.mkdir(parents=True)
    (deep / "t.csv").write_text("x")
    assert sr.find_files_named(tmp_path, "t.csv", suffixes=(".csv",), max_depth=2) == []
    assert sr.find_files_named(tmp_path, "t.csv", suffixes=(".csv",), max_depth=3) == [
        "d1/d2/d3/t.csv"
    ]


def test_a_byte_cap_refuses_a_file_even_when_its_characters_fit(tmp_path: Path) -> None:
    path = tmp_path / "wide.csv"
    path.write_text("\U0001f600" * 30, encoding="utf-8")  # 30 characters, 120 bytes
    assert sr.read_text_file(path, max_chars=100)[1] is False
    with pytest.raises(sr.SafeReadError) as info:
        sr.read_text_file(path, max_chars=100, max_bytes=100)
    assert info.value.code == "too_large"


def test_a_byte_cap_allows_a_file_at_the_cap(tmp_path: Path) -> None:
    path = tmp_path / "ok.csv"
    path.write_text("a" * 100, encoding="utf-8")
    assert sr.read_text_file(path, max_chars=1000, max_bytes=100) == ("a" * 100, False)


def test_read_text_under_reads_a_nested_file(tmp_path: Path) -> None:
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "f.csv").write_text("serial\n1\n", encoding="utf-8")
    assert sr.read_text_under(tmp_path, "a/b/f.csv", max_chars=100) == ("serial\n1\n", False)


@pytest.mark.parametrize(
    "relative", ["../x.csv", "/etc/x.csv", ".git/x", "a/../../x", "a//b.csv", ""]
)
def test_read_text_under_refuses_escapes(tmp_path: Path, relative: str) -> None:
    with pytest.raises(sr.SafeReadError) as info:
        sr.read_text_under(tmp_path, relative, max_chars=100)
    assert info.value.code == "outside"


def test_read_text_under_refuses_a_symlinked_directory_even_after_a_clean_contain_check(
    tmp_path: Path, monkeypatch
) -> None:
    # Simulate the race: the lstat check saw a real directory, then it became a symlink.
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "f.csv").write_text("x")
    os.symlink(tmp_path / "real", tmp_path / "swapped")
    monkeypatch.setattr(sr, "contain", lambda root, relative: root / relative)
    with pytest.raises(sr.SafeReadError) as info:
        sr.read_text_under(tmp_path, "swapped/f.csv", max_chars=100)
    assert info.value.code == "symlink"


def test_read_text_under_refuses_a_symlinked_file_and_reports_a_missing_one(tmp_path: Path) -> None:
    (tmp_path / "real.csv").write_text("x")
    os.symlink(tmp_path / "real.csv", tmp_path / "link.csv")
    (tmp_path / "dir").mkdir()
    cases = {"link.csv": "symlink", "nope.csv": "missing", "dir": "missing", "dir/x.csv": "missing"}
    for relative, code in cases.items():
        with pytest.raises(sr.SafeReadError) as info:
            sr.read_text_under(tmp_path, relative, max_chars=100)
        assert info.value.code == code, relative


def test_read_text_under_applies_the_caps(tmp_path: Path) -> None:
    (tmp_path / "big.csv").write_text("line of text\n" * 20, encoding="utf-8")
    text, truncated = sr.read_text_under(tmp_path, "big.csv", max_chars=100)
    assert truncated and len(text) <= 100
    with pytest.raises(sr.SafeReadError) as info:
        sr.read_text_under(tmp_path, "big.csv", max_chars=1000, max_bytes=50)
    assert info.value.code == "too_large"


def test_open_file_under_yields_a_readable_descriptor_and_closes_it(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "image.bin").write_bytes(b"\x00\xff binary")
    with sr.open_file_under(tmp_path, "a/image.bin") as fd:
        assert os.read(fd, 100) == b"\x00\xff binary"
    with pytest.raises(OSError):
        os.fstat(fd)


def test_open_file_under_refuses_a_symlink_swapped_in_after_a_check(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "image.bin").write_bytes(b"x")
    os.symlink(tmp_path / "real", tmp_path / "swapped")
    with pytest.raises(sr.SafeReadError) as info:
        with sr.open_file_under(tmp_path, "swapped/image.bin"):
            pass
    assert info.value.code == "symlink"
