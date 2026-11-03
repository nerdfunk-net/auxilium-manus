"""search_config_backups: which devices have a text or pattern in their backed-up config."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from core.regex_isolated import run_regex
from services.ai_assistant import config_backup as cb
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.results.store import InMemoryResultBackend, ResultStore
from services.ai_assistant.tools import config_backup_tools as tools
from services.ai_assistant.tools.base import ToolContext
from services.ai_assistant.tools.result_tools import RESULT_STORE_KEY

RUNNING = "{nautobot.location.name}/{device.name}.running.cfg"
REPO = {
    "name": "backups",
    "branch": "main",
    "is_active": True,
    "last_sync": None,
    "config_path_running": RUNNING,
    "config_path_startup": None,
}


def _ID(text: str) -> str:
    return text


def _write(root: Path, rel: str, text: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    _write(tmp_path, "Berlin/R1.running.cfg", "hostname R1\nlogging host 1.2.3.4\n")
    _write(tmp_path, "Berlin/R2.running.cfg", "hostname R2\nlogging host 5.6.7.8\n")
    _write(tmp_path, "Paris/R3.running.cfg", "hostname R3\nLOGGING HOST 1.2.3.4\n")
    _write(tmp_path, "Paris/R3.startup.cfg", "logging host 1.2.3.4\n")  # other kind
    _write(tmp_path, "Paris/notes.txt", "logging host 1.2.3.4\n")  # not a backup
    _write(tmp_path, ".git/x.running.cfg", "logging host 1.2.3.4\n")
    return tmp_path


def _reader(root: Path, repos=None) -> cb.DbConfigBackupReader:
    @asynccontextmanager
    async def checkout(_repo):
        yield root

    return cb.DbConfigBackupReader(
        7,
        resolver=None,  # type: ignore[arg-type]
        checkout=checkout,
        load_repositories=lambda: [REPO] if repos is None else repos,
        check_permission=lambda: None,
        check_rate=lambda: None,
        check_search_rate=lambda: None,
    )


# -- template -> regex --------------------------------------------------------------------------


def test_template_to_regex_captures_the_device_name() -> None:
    pattern = cb.template_to_regex(RUNNING)

    found = pattern.fullmatch("Berlin/R1.running.cfg")
    assert found is not None and found.group("device") == "R1"
    assert pattern.fullmatch("Berlin/sub/R1.running.cfg") is None
    assert pattern.fullmatch("Berlin/R1Xrunning.cfg") is None  # the dot is literal


def test_template_without_device_name_is_refused() -> None:
    with pytest.raises(cb.ConfigBackupError, match="device.name"):
        cb.template_to_regex("{nautobot.id}.cfg")


# -- scanning -----------------------------------------------------------------------------------


def test_text_search_is_case_insensitive_by_default(tree: Path) -> None:
    result = asyncio.run(
        _reader(tree).search("logging host 1.2.3.4", "text", "running", False, None, 50, _ID)
    )

    assert [h.device for h in result.hits] == ["R1", "R3"]
    assert result.files_scanned == 3
    assert not result.partial
    assert result.hits[0].lines[0] == (2, "logging host 1.2.3.4")


def test_text_search_case_sensitive(tree: Path) -> None:
    result = asyncio.run(
        _reader(tree).search("logging host 1.2.3.4", "text", "running", True, None, 50, _ID)
    )

    assert [h.device for h in result.hits] == ["R1"]


def test_regex_search_runs_in_the_isolated_worker(tree: Path) -> None:
    result = asyncio.run(
        _reader(tree).search(r"host 5\.6\.\d+\.8", "regex", "running", False, None, 50, _ID)
    )

    assert [h.device for h in result.hits] == ["R2"]


def test_invalid_regex_is_a_fixed_error(tree: Path) -> None:
    with pytest.raises(cb.ConfigBackupError, match="regular expression"):
        asyncio.run(_reader(tree).search("(", "regex", "running", False, None, 50, _ID))


def test_catastrophic_regex_is_stopped_and_reported_partial(tmp_path: Path) -> None:
    _write(tmp_path, "A/R1.running.cfg", "a" * 40 + "!\n")

    result = asyncio.run(
        _reader(tmp_path).search("(a+)+$", "regex", "running", False, None, 50, _ID)
    )

    assert result.partial and result.hits == ()


def test_limit_truncates_but_counts_all(tree: Path) -> None:
    result = asyncio.run(_reader(tree).search("hostname", "text", "running", False, None, 2, _ID))

    assert len(result.hits) == 2 and result.total_files == 3 and result.truncated


def test_skips_symlinks_binary_and_oversize_files(tree: Path) -> None:
    os.symlink(tree / "Berlin/R1.running.cfg", tree / "Berlin/R9.running.cfg")
    (tree / "Berlin/R8.running.cfg").write_bytes(b"\xff\xfe logging host 1.2.3.4")
    _write(tree, "Berlin/R7.running.cfg", "x" * (cb.MAX_SEARCH_FILE_BYTES + 1))

    result = asyncio.run(
        _reader(tree).search("logging host 1.2.3.4", "text", "running", False, None, 50, _ID)
    )

    assert [h.device for h in result.hits] == ["R1", "R3"]
    assert result.skipped == 3 and result.partial


def test_file_cap_marks_the_result_partial(tree: Path, monkeypatch) -> None:
    monkeypatch.setattr(cb, "MAX_SEARCH_FILES", 2)

    result = asyncio.run(_reader(tree).search("hostname", "text", "running", False, None, 50, _ID))

    assert result.partial and result.files_scanned == 2


def test_kind_without_template_is_an_error(tree: Path) -> None:
    with pytest.raises(cb.ConfigBackupError, match="startup"):
        asyncio.run(_reader(tree).search("x", "text", "startup", False, None, 50, _ID))


# -- worker op ----------------------------------------------------------------------------------


def test_search_lines_op_returns_first_lines_per_item() -> None:
    outcome = asyncio.run(
        run_regex(
            {
                "op": "search_lines",
                "pattern": r"host \d",
                "flags": {"case_insensitive": True},
                "items": [{"id": "a", "text": "x\nHOST 1\nhost 2\nhost 3\nhost 4"}],
                "max_lines": 3,
            }
        )
    )

    assert outcome.ok
    assert outcome.result == [{"id": "a", "lines": [[2, "HOST 1"], [3, "host 2"], [4, "host 3"]]}]


# -- tool ---------------------------------------------------------------------------------------


class FakeReader:
    def __init__(self, result=None, error=None) -> None:
        self.result, self.error, self.calls = result, error, []

    async def list_repositories(self):
        return []

    async def search(self, *args):
        self.calls.append(args)
        if self.error:
            raise self.error
        return self.result


def _ctx(reader, *, content=True, secrets=("hunter2hunter2",)) -> ToolContext:
    redactor = Redactor()
    redactor.add_known_secrets(secrets)
    return ToolContext(
        user_id=7,
        redactor=redactor,
        extras={
            tools.CONFIG_READER_KEY: reader,
            RESULT_STORE_KEY: ResultStore(InMemoryResultBackend()),
        },
        sharing=SharingPolicy(inventory=True, content=content),
    )


def _call(ctx: ToolContext, **kwargs):
    tool = next(t for t in tools.build_config_backup_tools() if t.name == "search_config_backups")
    return asyncio.run(tool.handler(ctx, tool.input_model(**kwargs)))


RESULT = cb.ConfigSearchResult(
    repository="backups",
    branch="main",
    kind="running",
    hits=(
        cb.ConfigSearchHit("R1", "A/R1.running.cfg", ((2, "snmp-server community xx RO"),)),
        cb.ConfigSearchHit("R3", "B/R3.running.cfg", ((5, "logging host 1.2.3.4"),)),
    ),
    total_files=2,
    total_devices=2,
    files_scanned=10,
    skipped=0,
    partial=False,
    truncated=False,
)


def test_tool_lists_devices_and_paths() -> None:
    reader = FakeReader(RESULT)
    ctx = _ctx(reader)

    out = _call(ctx, query="snmp-server community")
    data = json.loads(out.content)

    assert [d["device"] for d in data["matches"]] == ["R1", "R3"]
    assert data["matches"][0]["path"] == "A/R1.running.cfg"
    assert data["total_devices"] == 2 and data["source"].startswith("git backup")
    assert reader.calls[0][:6] == ("snmp-server community", "text", "running", False, None, 50)
    assert "config-search:backups" in ctx.audit_refs


def test_tool_needs_the_content_opt_in() -> None:
    reader = FakeReader(RESULT)

    out = _call(_ctx(reader, content=False), query="x")

    assert json.loads(out.content)["not_shared"] == "content_data"
    assert reader.calls == []


def test_tool_error_is_the_fixed_message() -> None:
    out = _call(_ctx(FakeReader(error=cb.ConfigBackupError("No repo"))), query="x")

    assert out.is_error and out.content == "No repo"


def test_tool_reports_partial_and_truncated() -> None:
    partial = cb.ConfigSearchResult(
        "backups", "main", "running", (), 0, 0, 4, skipped=2, partial=True, truncated=False
    )

    data = json.loads(_call(_ctx(FakeReader(partial)), query="x").content)

    assert data["partial"] is True and "incomplete" in data["note"]


def test_tool_rejects_an_empty_or_oversized_query() -> None:
    tool = next(t for t in tools.build_config_backup_tools() if t.name == "search_config_backups")
    with pytest.raises(ValueError):
        tool.input_model(query="")
    with pytest.raises(ValueError):
        tool.input_model(query="x" * 201)


# -- review findings (doc/analysis/REVIEW.md) ---------------------------------------------------


def test_same_device_name_at_two_sites_is_two_hits(tmp_path: Path) -> None:  # finding 1
    for site in ("Berlin", "Paris", "Rome"):
        _write(tmp_path, f"{site}/R1.running.cfg", "logging host 1.2.3.4\nlogging host 1.2.3.4\n")

    result = asyncio.run(
        _reader(tmp_path).search("logging host", "text", "running", False, None, 2, _ID)
    )

    assert [h.path for h in result.hits] == ["Berlin/R1.running.cfg", "Paris/R1.running.cfg"]
    assert result.total_files == 3 and result.total_devices == 1 and result.truncated


def test_a_secret_across_the_line_cut_is_redacted_before_the_cut(tmp_path: Path) -> None:  # 2
    secret = "hunter2hunter2"
    _write(tmp_path, "A/R1.running.cfg", "snmp " + "x" * 190 + f" {secret} tail\n")
    redactor = Redactor()
    redactor.add_known_secrets([secret])

    result = asyncio.run(
        _reader(tmp_path).search(
            "snmp",
            "text",
            "running",
            False,
            None,
            5,
            lambda t: redactor.fork(max_chars=10_000).redact(t),
        )
    )

    shown = result.hits[0].lines[0][1]
    assert secret not in shown and "hunter2" not in shown and len(shown) <= cb.MAX_LINE_CHARS


def test_private_key_block_lines_are_not_returned(tmp_path: Path) -> None:  # finding 2
    body = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC"
    _write(
        tmp_path,
        "A/R1.running.cfg",
        f"-----BEGIN PRIVATE KEY-----\n{body}\n-----END PRIVATE KEY-----\n",
    )

    result = asyncio.run(
        _reader(tmp_path).search(
            "MIIEvQ", "text", "running", False, None, 5, lambda t: Redactor().redact(t)
        )
    )

    assert all(body not in text for h in result.hits for _n, text in h.lines)


def test_passed_over_files_do_not_use_up_the_file_cap(tmp_path: Path, monkeypatch) -> None:  # 4
    monkeypatch.setattr(cb, "MAX_SEARCH_FILES", 2)
    _write(tmp_path, "Z/R1.running.cfg", "hostname R1\n")
    for name in ("A1", "A2", "A3"):
        os.symlink(tmp_path / "Z/R1.running.cfg", tmp_path / f"Z/{name}.running.cfg")
    _write(tmp_path, "Z/R8.running.cfg", "hostname R8\n")

    result = asyncio.run(
        _reader(tmp_path).search("hostname", "text", "running", False, None, 50, _ID)
    )

    assert {h.device for h in result.hits} == {"R1", "R8"} and result.partial  # links reported


def test_walk_does_not_descend_below_the_template_depth(tmp_path: Path) -> None:  # finding 4
    _write(tmp_path, "Berlin/deep/er/R1.running.cfg", "hostname R1\n")
    files, capped, passed = cb.list_backup_files(tmp_path, cb.template_to_regex(RUNNING), 2)

    assert files == [] and not capped and passed == 0


def test_deadline_marks_the_result_partial(tree: Path, monkeypatch) -> None:  # finding 3
    monkeypatch.setattr(cb, "SEARCH_DEADLINE_SECONDS", -1.0)

    result = asyncio.run(_reader(tree).search("hostname", "text", "running", False, None, 50, _ID))

    assert result.partial and result.files_scanned == 0


def test_concurrent_searches_are_capped(tree: Path, monkeypatch) -> None:  # finding 3
    monkeypatch.setattr(cb, "_active_searches", cb.MAX_CONCURRENT_SEARCHES)

    with pytest.raises(cb.ConfigBackupError, match="running"):
        asyncio.run(_reader(tree).search("x", "text", "running", False, None, 5, _ID))


def test_counter_is_released_after_an_error(tree: Path) -> None:
    before = cb._active_searches
    with pytest.raises(cb.ConfigBackupError):
        asyncio.run(_reader(tree).search("(", "regex", "running", False, None, 5, _ID))

    assert cb._active_searches == before


def test_output_is_shrunk_to_valid_json_under_the_cap() -> None:  # finding 6
    hits = tuple(
        cb.ConfigSearchHit(f"R{i}", f"S/R{i}.running.cfg", ((1, "x" * 200),) * 3)
        for i in range(200)
    )
    big = cb.ConfigSearchResult("backups", "main", "running", hits, 200, 200, 200, 0, False, False)

    out = _call(_ctx(FakeReader(big)), query="x", limit=200)
    data = json.loads(out.content)  # valid JSON, not a cut string

    assert len(out.content) <= tools.SEARCH_OUTPUT_BUDGET
    assert data["output_cut"] is True and 0 < len(data["matches"]) <= 200


def test_invalid_regex_message_is_fixed_text(tree: Path) -> None:  # finding 7
    with pytest.raises(cb.ConfigBackupError) as caught:
        asyncio.run(_reader(tree).search("(", "regex", "running", False, None, 5, _ID))

    assert str(caught.value) == "The regular expression is not valid"


def test_blank_query_is_rejected() -> None:  # finding 7
    tool = next(t for t in tools.build_config_backup_tools() if t.name == "search_config_backups")
    with pytest.raises(ValueError):
        tool.input_model(query="   ")
