"""The knowledge loader: built-in file plus the local overlay (doc/AI_TOOL_CHAIN.md §25.10 (1))."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from services.ai_assistant import knowledge_loader as kl


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    kl.clear_cache()


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    builtin = tmp_path / "builtin"
    local = tmp_path / "data" / "ai" / "knowledge"
    builtin.mkdir()
    return builtin, local


def test_builtin_text_is_returned_unchanged_without_overlay(tmp_path: Path) -> None:
    builtin, local = _dirs(tmp_path)
    (builtin / "guide.md").write_text("# Guide\nbody\n", encoding="utf-8")

    assert kl.load_knowledge("guide", builtin_dir=builtin, local_dir=local) == "# Guide\nbody\n"


def test_missing_builtin_file_is_an_error(tmp_path: Path) -> None:
    builtin, local = _dirs(tmp_path)

    with pytest.raises(FileNotFoundError):
        kl.load_knowledge("guide", builtin_dir=builtin, local_dir=local)


def test_local_overlay_is_placed_first_under_a_heading(tmp_path: Path) -> None:
    builtin, local = _dirs(tmp_path)
    (builtin / "guide.md").write_text("base", encoding="utf-8")
    local.mkdir(parents=True)
    (local / "guide.local.md").write_text("site rule", encoding="utf-8")

    text = kl.load_knowledge("guide", builtin_dir=builtin, local_dir=local)

    assert text.startswith(kl.LOCAL_HEADING)
    assert text.endswith("base")
    assert text.index(kl.LOCAL_HEADING) < text.index("site rule") < text.index("base")


def test_empty_overlay_adds_no_heading(tmp_path: Path) -> None:
    builtin, local = _dirs(tmp_path)
    (builtin / "guide.md").write_text("base", encoding="utf-8")
    local.mkdir(parents=True)
    (local / "guide.local.md").write_text("  \n", encoding="utf-8")

    assert kl.load_knowledge("guide", builtin_dir=builtin, local_dir=local) == "base"


def test_missing_local_directory_and_file_are_empty(tmp_path: Path) -> None:
    builtin, local = _dirs(tmp_path)
    (builtin / "guide.md").write_text("base", encoding="utf-8")

    assert kl.read_optional(local / "nope.md") == ""
    assert kl.load_knowledge("guide", builtin_dir=builtin, local_dir=local) == "base"


def test_local_path_that_is_a_directory_is_empty(tmp_path: Path) -> None:
    builtin, local = _dirs(tmp_path)
    (builtin / "guide.md").write_text("base", encoding="utf-8")
    (local / "guide.local.md").mkdir(parents=True)

    assert kl.load_knowledge("guide", builtin_dir=builtin, local_dir=local) == "base"


def test_unreadable_encoding_in_overlay_is_ignored(tmp_path: Path) -> None:
    builtin, local = _dirs(tmp_path)
    (builtin / "guide.md").write_text("base", encoding="utf-8")
    local.mkdir(parents=True)
    (local / "guide.local.md").write_bytes(b"\xff\xfe\x00bad")

    assert kl.load_knowledge("guide", builtin_dir=builtin, local_dir=local) == "base"


@pytest.mark.parametrize("name", ["../etc/passwd", "a/b", "Guide", "", "a.b", "x" * 80, "guide.md"])
def test_names_that_are_not_plain_identifiers_are_refused(tmp_path: Path, name: str) -> None:
    builtin, local = _dirs(tmp_path)

    with pytest.raises(ValueError):
        kl.load_knowledge(name, builtin_dir=builtin, local_dir=local)


def test_oversized_overlay_file_is_cut_with_a_marker(tmp_path: Path) -> None:
    builtin, local = _dirs(tmp_path)
    (builtin / "guide.md").write_text("base", encoding="utf-8")
    local.mkdir(parents=True)
    (local / "guide.local.md").write_text("x" * (kl.MAX_FILE_CHARS * 3), encoding="utf-8")

    text = kl.load_knowledge("guide", builtin_dir=builtin, local_dir=local)

    assert len(text) <= kl.MAX_COMBINED_CHARS
    assert "truncated" in text
    assert text.endswith("base")  # the built-in text is whole; only the overlay was cut


def test_combined_size_is_capped_even_when_both_files_are_large(tmp_path: Path) -> None:
    builtin, local = _dirs(tmp_path)
    (builtin / "guide.md").write_text("b" * (kl.MAX_FILE_CHARS - 10), encoding="utf-8")
    local.mkdir(parents=True)
    (local / "guide.local.md").write_text("l" * (kl.MAX_FILE_CHARS - 10), encoding="utf-8")

    text = kl.load_knowledge("guide", builtin_dir=builtin, local_dir=local)

    assert len(text) <= kl.MAX_COMBINED_CHARS
    assert text.startswith(kl.LOCAL_HEADING + "\n\n" + "l" * 100)
    assert text.count("l") <= kl.MAX_OVERLAY_CHARS
    assert text.count("b") >= kl.MAX_COMBINED_CHARS - kl.MAX_OVERLAY_CHARS - 200
    assert "truncated" in text.splitlines()[-1]  # the built-in tail is the part that was cut


def test_edit_is_picked_up_without_restart(tmp_path: Path) -> None:
    builtin, local = _dirs(tmp_path)
    (builtin / "guide.md").write_text("base", encoding="utf-8")
    local.mkdir(parents=True)
    overlay = local / "guide.local.md"
    overlay.write_text("one", encoding="utf-8")
    first = kl.load_knowledge("guide", builtin_dir=builtin, local_dir=local)

    overlay.write_text("two!", encoding="utf-8")
    os.utime(overlay, ns=(1, 1))  # a different mtime even on a coarse clock
    second = kl.load_knowledge("guide", builtin_dir=builtin, local_dir=local)

    assert "one" in first
    assert "two!" in second and "one" not in second


def test_unchanged_file_is_not_read_again(tmp_path: Path, monkeypatch) -> None:
    builtin, local = _dirs(tmp_path)
    (builtin / "guide.md").write_text("base", encoding="utf-8")
    reads: list[Path] = []
    real = kl._read_file

    def spy(handle, max_chars: int) -> str:
        reads.append(handle)
        return real(handle, max_chars)

    monkeypatch.setattr(kl, "_read_file", spy)

    kl.load_knowledge("guide", builtin_dir=builtin, local_dir=local)
    kl.load_knowledge("guide", builtin_dir=builtin, local_dir=local)

    assert len(reads) == 1  # the second call hit the cache; the missing overlay is never opened


def test_deleted_overlay_disappears(tmp_path: Path) -> None:
    builtin, local = _dirs(tmp_path)
    (builtin / "guide.md").write_text("base", encoding="utf-8")
    local.mkdir(parents=True)
    overlay = local / "guide.local.md"
    overlay.write_text("one", encoding="utf-8")
    assert "one" in kl.load_knowledge("guide", builtin_dir=builtin, local_dir=local)

    overlay.unlink()

    assert kl.load_knowledge("guide", builtin_dir=builtin, local_dir=local) == "base"


def test_default_local_dir_is_under_the_data_directory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(kl.settings, "data_directory", tmp_path)

    assert kl.local_knowledge_dir() == tmp_path / "ai" / "knowledge"
    assert kl.local_playbook_dir() == tmp_path / "ai" / "playbooks"


def test_the_shipped_files_load() -> None:
    for name in (
        "inventory_reference",
        "template_reference",
        "workflow_reference",
        "workflow_recipes",
    ):
        text = kl.load_knowledge(name, local_dir=Path("/nonexistent/ai/knowledge"))
        assert text.strip()
        assert text == (kl.KNOWLEDGE_DIR / f"{name}.md").read_text(encoding="utf-8")


def test_single_file_read_is_cut_at_the_character_cap_with_a_marker(tmp_path: Path) -> None:
    path = tmp_path / "big.md"
    path.write_text("y" * 100, encoding="utf-8")

    text = kl.read_optional(path, 10)

    assert text.startswith("y" * 10 + "\n")
    assert "truncated" in text
    assert len(text) < 100


def test_file_beyond_the_byte_limit_is_cut_not_rejected(tmp_path: Path) -> None:
    path = tmp_path / "huge.md"
    path.write_bytes("é".encode() * 100)  # 200 bytes, 100 characters

    text = kl.read_optional(path, 10)  # byte limit 40: the read stops mid-file

    assert text.startswith("é" * 10)
    assert "truncated" in text


def test_text_within_the_cap_is_not_marked(tmp_path: Path) -> None:
    path = tmp_path / "ok.md"
    path.write_text("short", encoding="utf-8")

    assert kl.read_optional(path, 10) == "short"


def test_file_between_the_cap_and_the_byte_limit_is_cut(tmp_path: Path) -> None:
    path = tmp_path / "mid.md"
    path.write_text("y" * 20, encoding="utf-8")  # 20 bytes: over 10 characters, under 40 bytes

    text = kl.read_optional(path, 10)

    assert text.startswith("y" * 10 + "\n")
    assert "truncated" in text


def test_four_byte_characters_cut_at_the_byte_limit_are_still_marked(tmp_path: Path) -> None:
    path = tmp_path / "emoji.md"
    path.write_text("😀" * 50, encoding="utf-8")  # 4 bytes each: the byte limit holds exactly 10

    text = kl.read_optional(path, 10)

    assert "truncated" in text


def test_missing_and_directory_paths_are_silent_but_unreadable_ones_are_logged(
    tmp_path: Path, caplog
) -> None:
    (tmp_path / "dir.md").mkdir()
    (tmp_path / "bad.md").write_bytes(b"\xff\xfe\x00bad")

    with caplog.at_level("WARNING", logger=kl.logger.name):
        kl.read_optional(tmp_path / "nope.md")
        kl.read_optional(tmp_path / "dir.md")
        assert not caplog.records
        kl.read_optional(tmp_path / "bad.md")

    assert len(caplog.records) == 1
    assert "bad.md" in caplog.text


@pytest.mark.parametrize(
    ("tool_name", "knowledge_name"),
    [
        ("get_inventory_reference", "inventory_reference"),
        ("get_template_reference", "template_reference"),
        ("get_workflow_reference", "workflow_reference"),
        ("get_workflow_recipes", "workflow_recipes"),
    ],
)
def test_the_four_reference_tools_return_the_local_overlay(
    tmp_path: Path, monkeypatch, tool_name: str, knowledge_name: str
) -> None:
    from services.ai_assistant.redaction import Redactor
    from services.ai_assistant.tools.base import ToolContext
    from services.ai_assistant.tools.inventory_filter_tools import INVENTORY_FILTER_TOOLS
    from services.ai_assistant.tools.template_tools import TEMPLATE_EDITOR_TOOLS
    from services.ai_assistant.tools.workflow_tools import WORKFLOW_EDITOR_TOOLS

    overlay_dir = tmp_path / "ai" / "knowledge"
    overlay_dir.mkdir(parents=True)
    (overlay_dir / f"{knowledge_name}.local.md").write_text("SITE-RULE-42", encoding="utf-8")
    monkeypatch.setattr(kl.settings, "data_directory", tmp_path)
    tools = {
        t.name: t for t in (*INVENTORY_FILTER_TOOLS, *TEMPLATE_EDITOR_TOOLS, *WORKFLOW_EDITOR_TOOLS)
    }
    tool = tools[tool_name]

    out = asyncio.run(tool.handler(ToolContext(user_id=1, redactor=Redactor()), tool.input_model()))

    assert not out.is_error
    builtin_text = (kl.KNOWLEDGE_DIR / f"{knowledge_name}.md").read_text(encoding="utf-8")
    assert out.content.startswith(kl.LOCAL_HEADING)
    assert "SITE-RULE-42" in out.content.split(builtin_text[:40])[0]
    assert builtin_text in out.content  # nothing of the shipped text is lost to the overlay
    assert not out.truncated


# -- review findings: confinement, strict decoding, budget ----------------------------------


def _with_timeout(seconds: int = 5):
    import signal

    def handler(signum, frame):
        raise TimeoutError("read blocked")

    signal.signal(signal.SIGALRM, handler)
    signal.alarm(seconds)


def test_symlinked_overlay_is_not_followed(tmp_path: Path, caplog) -> None:
    builtin, local = _dirs(tmp_path)
    (builtin / "guide.md").write_text("base", encoding="utf-8")
    local.mkdir(parents=True)
    secret = tmp_path / "secret.txt"
    secret.write_text("PRIVATE-DATA", encoding="utf-8")
    (local / "guide.local.md").symlink_to(secret)

    text = kl.load_knowledge("guide", builtin_dir=builtin, local_dir=local)

    assert text == "base"
    assert "PRIVATE-DATA" not in text


def test_fifo_overlay_does_not_block_the_reader(tmp_path: Path, caplog) -> None:
    import time

    builtin, local = _dirs(tmp_path)
    (builtin / "guide.md").write_text("base", encoding="utf-8")
    local.mkdir(parents=True)
    os.mkfifo(local / "guide.local.md")
    # A blocked open ends with the alarm's TimeoutError, which is an OSError the reader would
    # swallow; the elapsed time is what shows it did not block.
    _with_timeout(2)
    started = time.monotonic()
    try:
        with caplog.at_level("WARNING", logger=kl.logger.name):
            text = kl.load_knowledge("guide", builtin_dir=builtin, local_dir=local)
    finally:
        import signal

        signal.alarm(0)

    assert time.monotonic() - started < 1
    assert text == "base"
    assert "guide.local.md" in caplog.text  # refused as a non-regular file, and logged


def test_bad_bytes_are_rejected_whether_or_not_the_file_is_over_the_byte_cap(
    tmp_path: Path,
) -> None:
    short = tmp_path / "short.md"
    short.write_bytes(b"\xffabc")
    long = tmp_path / "long.md"
    long.write_bytes(b"\xff" + b"x" * 100)

    assert kl.read_optional(short, 10) == ""
    assert kl.read_optional(long, 10) == ""  # byte limit 40: the same bad byte, same result


def test_a_character_cut_in_half_at_the_byte_limit_is_dropped_not_an_error(tmp_path: Path) -> None:
    path = tmp_path / "split.md"
    path.write_bytes(b"abc" + "é".encode() * 30)  # byte limit 4*10=40 falls inside an "é"

    text = kl.read_optional(path, 10)

    assert text.startswith("abc" + "é" * 7 + "\n")
    assert "truncated" in text


def test_overlay_comes_first_and_the_builtin_tail_is_cut_to_fit(
    tmp_path: Path, monkeypatch
) -> None:
    builtin, local = _dirs(tmp_path)
    monkeypatch.setattr(kl, "MAX_COMBINED_CHARS", 400)
    monkeypatch.setattr(kl, "MAX_OVERLAY_CHARS", 100)
    (builtin / "guide.md").write_text("B" * 1000, encoding="utf-8")
    local.mkdir(parents=True)
    (local / "guide.local.md").write_text("SITE-RULE " + "s" * 50, encoding="utf-8")

    text = kl.load_knowledge("guide", builtin_dir=builtin, local_dir=local)

    assert text.startswith(kl.LOCAL_HEADING)
    assert "SITE-RULE" in text
    assert len(text) <= 400
    assert "truncated" in text.splitlines()[-1]


def test_the_combined_cap_matches_the_tool_output_cap() -> None:
    from services.ai_assistant.tools.base import MAX_TOOL_OUTPUT_CHARS

    assert kl.MAX_COMBINED_CHARS == MAX_TOOL_OUTPUT_CHARS


def test_a_complete_file_ending_in_half_a_character_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "tail.md"
    path.write_bytes(b"abc\xc3")  # a short file: nothing was cut by the cap, the file is damaged

    assert kl.read_optional(path, 10) == ""
