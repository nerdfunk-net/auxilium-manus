"""Tests for the file/Nautobot comparison reader (doc/AI_TOOL_CHAIN.md §61)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from _git_helpers import acheckout_of
from nautobot_read.client import NautobotError

from services.ai_assistant import file_compare_reader as fc
from services.ai_assistant.nautobot_query_reader import NautobotAccessError

pytestmark = pytest.mark.asyncio

CSV = "serial;data\n1;a\n2;b\n3;c\n"
REPO = {"name": "Gitea CSV", "branch": "main", "category": "csv_imports", "last_sync": None}


def _items(*values: str | None) -> dict[str, Any]:
    return {
        "items": [
            {"id": f"id{i}", "name": f"dev{i}", "location": "Berlin", "value": value}
            for i, value in enumerate(values)
        ],
        "applied_filters": {},
    }


class _Calls:
    def __init__(self) -> None:
        self.checkouts = 0
        self.fetches: list[tuple[str, dict[str, Any]]] = []


def _reader(
    root: Path,
    *,
    values: dict[str, Any] | Exception | None = None,
    repositories: list[dict[str, Any]] | None = None,
    permission: Exception | None = None,
    rate: Exception | None = None,
    checkout_error: Exception | None = None,
) -> tuple[fc.DbFileCompareReader, _Calls]:
    calls = _Calls()

    def checkout(_repo: dict[str, Any]) -> Any:
        calls.checkouts += 1
        if checkout_error is not None:
            raise checkout_error
        return acheckout_of(root)

    async def fetch(field: str, filters: dict[str, Any]) -> dict[str, Any]:
        calls.fetches.append((field, filters))
        if isinstance(values, Exception):
            raise values
        return values if values is not None else _items("1", "2", "9")

    def check_permission() -> None:
        if permission is not None:
            raise permission

    def check_rate() -> None:
        if rate is not None:
            raise rate

    reader = fc.DbFileCompareReader(
        1,
        fetch_values=fetch,
        checkout=checkout,
        load_repositories=lambda: [REPO] if repositories is None else repositories,
        check_permission=check_permission,
        check_rate=check_rate,
    )
    return reader, calls


def _request(**overrides: Any) -> fc.CompareRequest:
    base: dict[str, Any] = {
        "repository": None,
        "file": "compare.csv",
        "key_column": "serial",
        "field": "serial",
        "match_mode": "match",
        "case_insensitive": False,
        "delimiter": None,
        "filters": {},
    }
    base.update(overrides)
    return fc.CompareRequest(**base)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "compare.csv").write_text(CSV, encoding="utf-8")
    return tmp_path


async def test_both_sides_are_compared(repo: Path) -> None:
    reader, calls = _reader(repo)
    outcome = await reader.compare(_request())
    result = outcome.reconciliation
    assert outcome.file == "data/compare.csv" and outcome.repository == "Gitea CSV"
    assert [r.key for r in result.only_in_file] == ["3"]
    assert [i.value for i in result.only_in_items] == ["9"]
    assert calls.fetches == [("serial", {})]


async def test_filters_are_passed_to_nautobot(repo: Path) -> None:
    reader, calls = _reader(repo)
    await reader.compare(_request(filters={"location": "Berlin", "role": None}))
    assert calls.fetches == [("serial", {"location": "Berlin"})]


async def test_a_path_with_a_directory_is_used_as_given(repo: Path) -> None:
    reader, _ = _reader(repo)
    outcome = await reader.compare(_request(file="data/compare.csv"))
    assert outcome.file == "data/compare.csv"


async def test_ambiguous_bare_name_lists_the_paths(repo: Path) -> None:
    (repo / "other").mkdir()
    (repo / "other" / "compare.csv").write_text(CSV)
    reader, _ = _reader(repo)
    with pytest.raises(fc.FileCompareError, match="data/compare.csv, other/compare.csv"):
        await reader.compare(_request())


async def test_missing_file_and_bad_extension_and_traversal(repo: Path) -> None:
    reader, _ = _reader(repo)
    with pytest.raises(fc.FileCompareError, match="No file named"):
        await reader.compare(_request(file="nope.csv"))
    with pytest.raises(fc.FileCompareError, match=r"\.csv, \.tsv or \.txt"):
        await reader.compare(_request(file="data/compare.cfg"))
    with pytest.raises(fc.FileCompareError, match="outside"):
        await reader.compare(_request(file="../x.csv"))
    with pytest.raises(fc.FileCompareError, match="outside"):
        await reader.compare(_request(file="/etc/passwd.csv"))
    with pytest.raises(fc.FileCompareError, match="forward slashes"):
        await reader.compare(_request(file="data\\compare.csv"))


async def test_a_symlinked_file_is_refused(repo: Path) -> None:
    os.symlink(repo / "data" / "compare.csv", repo / "data" / "link.csv")
    reader, _ = _reader(repo)
    with pytest.raises(fc.FileCompareError, match="symbolic link"):
        await reader.compare(_request(file="data/link.csv"))


async def test_repository_selection(repo: Path) -> None:
    other = {**REPO, "name": "Archive", "category": "csv_exports"}
    reader, _ = _reader(repo, repositories=[REPO, other])
    with pytest.raises(fc.FileCompareError, match="Gitea CSV, Archive"):
        await reader.compare(_request())  # several, none named
    outcome = await reader.compare(_request(repository="gitea csv"))  # case-insensitive
    assert outcome.repository == "Gitea CSV"
    with pytest.raises(fc.FileCompareError, match="No repository 'nope'"):
        await reader.compare(_request(repository="nope"))
    empty, _ = _reader(repo, repositories=[])
    with pytest.raises(fc.FileCompareError, match="csv_imports or csv_exports"):
        await empty.compare(_request())


async def test_no_permission_stops_before_anything_else(repo: Path) -> None:
    reader, calls = _reader(repo, permission=fc.FileCompareDeniedError())
    with pytest.raises(fc.FileCompareDeniedError):
        await reader.compare(_request())
    with pytest.raises(fc.FileCompareDeniedError):
        await reader.list_repositories()
    assert calls.checkouts == 0 and calls.fetches == []


async def test_the_rate_limit_stops_before_the_checkout(repo: Path) -> None:
    reader, calls = _reader(repo, rate=fc.FileCompareError("Too many comparisons"))
    with pytest.raises(fc.FileCompareError, match="Too many"):
        await reader.compare(_request())
    assert calls.checkouts == 0


async def test_missing_key_column_carries_the_names_separately(repo: Path) -> None:
    reader, _ = _reader(repo)
    with pytest.raises(fc.FileCompareError) as caught:
        await reader.compare(_request(key_column="nope"))
    assert "nope" not in str(caught.value) and "serial" not in str(caught.value)
    assert caught.value.columns == ("serial", "data")


async def test_other_csv_problems_are_reported(repo: Path) -> None:
    (repo / "data" / "dup.csv").write_text("serial;serial\n1;2\n")
    reader, _ = _reader(repo)
    with pytest.raises(fc.FileCompareError, match="duplicate"):
        await reader.compare(_request(file="dup.csv"))
    with pytest.raises(fc.FileCompareError, match="delimiter"):
        await reader.compare(_request(delimiter="ab"))


async def test_a_file_over_the_size_cap_is_refused_not_cut(repo: Path, monkeypatch) -> None:
    monkeypatch.setattr(fc, "MAX_FILE_CHARS", 10)
    reader, calls = _reader(repo)
    with pytest.raises(fc.FileCompareError, match="too large"):
        await reader.compare(_request())
    assert calls.fetches == []


async def test_nautobot_failures(repo: Path) -> None:
    denied, _ = _reader(repo, values=NautobotAccessError())
    with pytest.raises(fc.FileCompareDeniedError):
        await denied.compare(_request())
    expected, _ = _reader(repo, values=NautobotError("More than 5000 devices match; add a filter"))
    with pytest.raises(fc.FileCompareError, match="add a filter"):
        await expected.compare(_request())


async def test_contains_over_the_cap_is_refused(repo: Path, monkeypatch) -> None:
    monkeypatch.setattr(fc, "MAX_COMPARISONS", 1)
    reader, _ = _reader(repo)
    with pytest.raises(fc.FileCompareError, match="comparisons"):
        await reader.compare(_request(match_mode="contains"))


async def test_a_checkout_failure_is_a_generic_message(repo: Path) -> None:
    reader, _ = _reader(repo, checkout_error=RuntimeError("token ghp_SECRET leaked"))
    with pytest.raises(fc.FileCompareError) as caught:
        await reader.compare(_request())
    assert "ghp_SECRET" not in str(caught.value) and "repository" in str(caught.value)


async def test_an_ip_address_matches_with_or_without_a_mask(repo: Path) -> None:
    (repo / "data" / "ips.csv").write_text("ip\n10.0.0.1\n10.0.0.2/24\n")
    reader, _ = _reader(repo, values=_items("10.0.0.1/24", "10.0.0.2", "10.0.0.3/24"))
    outcome = await reader.compare(_request(file="ips.csv", key_column="ip", field="primary_ip4"))
    assert outcome.reconciliation.only_in_file == ()
    assert [i.value for i in outcome.reconciliation.only_in_items] == ["10.0.0.3/24"]


async def test_case_insensitive_and_contains(repo: Path) -> None:
    (repo / "data" / "names.csv").write_text("name\nLAB\n")
    reader, _ = _reader(repo, values=_items("foo-lab-01", "other"))
    outcome = await reader.compare(
        _request(
            file="names.csv",
            key_column="name",
            field="name",
            match_mode="contains",
            case_insensitive=True,
        )
    )
    assert outcome.reconciliation.only_in_file == ()
    assert [i.value for i in outcome.reconciliation.only_in_items] == ["other"]


async def test_list_repositories(repo: Path) -> None:
    reader, _ = _reader(repo, repositories=[{**REPO, "last_sync": "2026-11-19"}])
    listed = await reader.list_repositories()
    assert listed == [fc.CompareRepository("Gitea CSV", "main", "csv_imports", "2026-11-19")]


async def test_only_csv_repositories_are_loaded_and_only_active_ones(monkeypatch) -> None:
    asked: list[tuple[str | None, bool]] = []

    class FakeService:
        def __init__(self, _db: Any) -> None:
            pass

        def get_repositories(self, category: str | None = None, active_only: bool = False):
            asked.append((category, active_only))
            return [{**REPO, "name": f"repo-{category}", "category": category}]

    class FakeSession:
        def __enter__(self) -> FakeSession:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(fc, "GitRepositoryService", FakeService)
    monkeypatch.setattr(fc, "SessionLocal", FakeSession)

    loaded = fc.DbFileCompareReader._db_repositories()

    assert asked == [("csv_imports", True), ("csv_exports", True)]
    assert [r["name"] for r in loaded] == ["repo-csv_imports", "repo-csv_exports"]
    assert fc.CATEGORIES == ("csv_imports", "csv_exports")


async def test_the_byte_cap_refuses_a_file_whose_characters_would_fit(
    repo: Path, monkeypatch
) -> None:
    (repo / "data" / "wide.csv").write_text("serial\n" + "\U0001f600\n" * 40, encoding="utf-8")
    monkeypatch.setattr(fc, "MAX_FILE_BYTES", 100)
    reader, calls = _reader(repo)
    with pytest.raises(fc.FileCompareError, match="too large"):
        await reader.compare(_request(file="data/wide.csv"))
    assert calls.fetches == []


async def test_a_symlinked_directory_in_the_path_is_refused(repo: Path) -> None:
    os.symlink(repo / "data", repo / "alias")
    reader, _ = _reader(repo)
    with pytest.raises(fc.FileCompareError, match="symbolic link"):
        await reader.compare(_request(file="alias/compare.csv"))


@pytest.mark.parametrize("missing", ["git.files", "sources.nautobot"])
async def test_the_default_permission_check_needs_both_permissions(monkeypatch, missing) -> None:
    class FakeRbac:
        def __init__(self, _db: Any) -> None:
            pass

        def has_permission(self, _user: int, resource: str, action: str) -> bool:
            return (resource, action) != (missing, "read")

    class FakeSession:
        def __enter__(self) -> FakeSession:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(fc, "RBACService", FakeRbac)
    monkeypatch.setattr(fc, "SessionLocal", FakeSession)
    reader = fc.DbFileCompareReader(1, load_repositories=lambda: [REPO], check_rate=lambda: None)
    with pytest.raises(fc.FileCompareDeniedError):
        await reader.list_repositories()  # the list is gated like the comparison
    with pytest.raises(fc.FileCompareDeniedError):
        await reader.compare(_request())
    monkeypatch.setattr(FakeRbac, "has_permission", lambda *_a: True)
    assert [r.name for r in await reader.list_repositories()] == ["Gitea CSV"]


def test_the_categories_the_reader_loads_are_real_git_categories() -> None:
    from models.git_repositories import GitCategory, GitRepositoryRequest

    assert {c.value for c in GitCategory} >= set(fc.CATEGORIES)
    for category in fc.CATEGORIES:  # an administrator can set each one through the API
        request = GitRepositoryRequest(
            name="x", category=category, url="https://example.invalid/r.git"
        )
        assert request.category.value == category


def test_the_no_repository_message_says_where_to_set_the_category() -> None:
    with pytest.raises(fc.FileCompareError) as caught:
        fc.select_repository([], None)
    assert "csv_imports or csv_exports" in str(caught.value)
    assert "CSV files" in str(caught.value)
