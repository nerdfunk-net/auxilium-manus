"""Compare a CSV file from a git repository with a Nautobot device field (doc/AI_TOOL_CHAIN.md §61).

The model names a repository, a file, a key column and a Nautobot field; everything else happens
here, as the calling user: the repository is checked out (lease held, strict pull), the file is
read without following a link, parsed with the shared ``services.csv_lookup`` core, the device
values come from the shared ``nautobot_read`` library and ``reconcile`` finds what is on only one
side. The values never go back to the model: the tool keeps them behind a result handle for the
user's card (``tools/file_compare_tools.py``).

Only repositories of category ``csv_imports`` / ``csv_exports`` are readable. ``git.files:read`` is
checked on every call (``sources.nautobot:read`` by the Nautobot reader), and a per-user rate limit
applies. Errors are fixed sentences: never a path outside the repository, file text or upstream
text.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from nautobot_read.errors import EXPECTED_ERRORS
from nautobot_read.queries import dcim

import service_factory
from core.database import SessionLocal
from services.ai_assistant.nautobot_query_reader import NautobotAccessError
from services.auth.login_rate_limiter import RateLimitExceededError
from services.auth.rbac_service import RBACService
from services.csv_lookup import (
    MAX_COMPARISONS,
    MAX_FILE_BYTES,
    CsvLookupError,
    KeyColumnNotFoundError,
    ReconcileTooLargeError,
    Reconciliation,
    ValueItem,
    normalize_ip_host,
    parse_csv_rows,
    parse_delimiter,
    reconcile,
)
from services.git import safe_read
from services.git.repository_service import GitRepositoryService
from services.git.sync import agit_checkout

logger = logging.getLogger(__name__)

CATEGORIES = ("csv_imports", "csv_exports")
FILE_SUFFIXES = (".csv", ".tsv", ".txt")
MAX_FILE_CHARS = MAX_FILE_BYTES
MAX_AMBIGUOUS_PATHS = 10
RATE_BUCKET = "ai-file-compare"
RATE_ATTEMPTS = 6
RATE_WINDOW_SECONDS = 60
# Normalisers applied to both sides before comparing, by Nautobot field.
_NORMALIZERS: dict[str, Callable[[str], str]] = {"primary_ip4": normalize_ip_host}
_FILTER_NAMES = ("location", "role", "status", "tag", "device_type", "platform")

_FILE_MESSAGES = {
    "outside": "The file path points outside the repository",
    "symlink": "The file path is a symbolic link, which is not read",
    "missing": "No such file in the repository",
    "unreadable": "The file cannot be read",
    "not_regular": "The path is not a regular file",
    "not_utf8": "The file is not valid UTF-8 text",
    "too_large": "The file is too large to compare (the limit is 10 MiB)",
    "too_many_files": "The repository has too many files to search by name; give the path",
}


class FileCompareError(Exception):
    """A fixed sentence for the model. ``columns`` holds the file's column names when the key
    column was not found: file content, shown only with the user's content opt-in."""

    def __init__(self, message: str, *, columns: tuple[str, ...] | None = None) -> None:
        super().__init__(message)
        self.columns = columns


class FileCompareDeniedError(FileCompareError):
    def __init__(self) -> None:
        super().__init__(
            "You cannot compare files with Nautobot here (missing permission or no usable "
            "Nautobot source)."
        )


@dataclass(frozen=True)
class CompareRepository:
    name: str
    branch: str
    category: str
    last_sync: str | None


@dataclass(frozen=True)
class CompareRequest:
    repository: str | None
    file: str
    key_column: str
    field: str
    match_mode: str
    case_insensitive: bool
    delimiter: str | None
    filters: Mapping[str, str | None]


@dataclass(frozen=True)
class CompareOutcome:
    repository: str
    file: str
    request: CompareRequest
    reconciliation: Reconciliation
    applied_filters: Mapping[str, Any]


class FileCompareReader(Protocol):
    async def list_repositories(self) -> list[CompareRepository]: ...

    async def compare(self, request: CompareRequest) -> CompareOutcome: ...


class NautobotContextReader(Protocol):
    async def context(self) -> Any: ...


Checkout = Callable[[dict[str, Any]], AbstractAsyncContextManager[Path]]
ValueFetcher = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


def select_repository(repositories: list[dict[str, Any]], name: str | None) -> dict[str, Any]:
    """The repository meant by ``name`` (exact, case-insensitive); one repository needs no name."""
    if not repositories:
        raise FileCompareError(
            "No repository of category csv_imports or csv_exports is configured. An "
            "administrator sets a repository's category to 'CSV files' in Settings -> Git "
            "Repositories."
        )
    names = ", ".join(str(r["name"]) for r in repositories)
    if name:
        for repository in repositories:
            if str(repository["name"]).casefold() == name.strip().casefold():
                return repository
        raise FileCompareError(f"No repository '{name}'. Available: {names}.")
    if len(repositories) == 1:
        return repositories[0]
    raise FileCompareError(f"Several repositories hold CSV files: {names}. Say which one.")


def resolve_file(root: Path, file: str, repository: str) -> str:
    """The relative path of ``file`` (a path, or a bare name searched in the checkout)."""
    text = file.strip()
    if "\\" in text:
        raise FileCompareError("Use forward slashes in the file path.")
    if not text.lower().endswith(FILE_SUFFIXES):
        raise FileCompareError("Only .csv, .tsv or .txt files can be compared.")
    if "/" in text:
        return text
    try:
        found = safe_read.find_files_named(root, text, suffixes=FILE_SUFFIXES)
    except safe_read.SafeReadError as exc:
        raise FileCompareError(_FILE_MESSAGES.get(exc.code, _FILE_MESSAGES["unreadable"])) from exc
    if not found:
        raise FileCompareError(f"No file named '{text}' in repository '{repository}'.")
    if len(found) > 1:
        shown = ", ".join(found[:MAX_AMBIGUOUS_PATHS])
        raise FileCompareError(f"Several files are called '{text}': {shown}. Give the path.")
    return found[0]


class DbFileCompareReader:
    """Reads and compares as the calling user. Injectable parts keep the unit tests off the net."""

    def __init__(
        self,
        user_id: int,
        nautobot_reader: NautobotContextReader | None = None,
        *,
        fetch_values: ValueFetcher | None = None,
        checkout: Checkout | None = None,
        load_repositories: Callable[[], list[dict[str, Any]]] | None = None,
        check_permission: Callable[[], None] | None = None,
        check_rate: Callable[[], None] | None = None,
    ) -> None:
        self._user_id = user_id
        self._nautobot_reader = nautobot_reader
        self._fetch_values = fetch_values or self._nautobot_values
        self._checkout = checkout or (lambda repo: agit_checkout(repo))
        self._load_repositories = load_repositories or self._db_repositories
        self._check_permission = check_permission or self._db_permission
        self._check_rate = check_rate or self._rate_limit

    def _db_permission(self) -> None:
        with SessionLocal() as db:
            rbac = RBACService(db)
            # Both permissions the comparison needs, so the repository list is gated like it.
            if not (
                rbac.has_permission(self._user_id, "git.files", "read")
                and rbac.has_permission(self._user_id, "sources.nautobot", "read")
            ):
                raise FileCompareDeniedError

    def _rate_limit(self) -> None:
        limiter = service_factory.build_user_rate_limiter(
            RATE_BUCKET, RATE_ATTEMPTS, RATE_WINDOW_SECONDS
        )
        try:
            limiter.check(f"{RATE_BUCKET}:{self._user_id}")
        except RateLimitExceededError as exc:
            raise FileCompareError("Too many file comparisons; try again shortly") from exc

    @staticmethod
    def _db_repositories() -> list[dict[str, Any]]:
        with SessionLocal() as db:
            service = GitRepositoryService(db)
            return [
                repository
                for category in CATEGORIES
                for repository in service.get_repositories(category=category, active_only=True)
            ]

    async def _nautobot_values(self, field: str, filters: dict[str, Any]) -> dict[str, Any]:
        if self._nautobot_reader is None:
            raise FileCompareDeniedError
        context = await self._nautobot_reader.context()
        return await dcim.list_device_values(context, field=field, **filters)

    async def list_repositories(self) -> list[CompareRepository]:
        await asyncio.to_thread(self._check_permission)
        repositories = await asyncio.to_thread(self._load_repositories)
        return [
            CompareRepository(
                name=str(r["name"]),
                branch=str(r.get("branch") or ""),
                category=str(r.get("category") or ""),
                last_sync=r.get("last_sync"),
            )
            for r in repositories
        ]

    async def _read_file(self, repository: dict[str, Any], file: str) -> tuple[str, str]:
        """``(relative path, text)`` read inside the checkout (lease held only while reading)."""
        name = str(repository["name"])
        try:
            async with self._checkout(repository) as root:
                relative = await asyncio.to_thread(resolve_file, root, file, name)
                # Opened component by component without following a link; a file above the byte
                # cap is refused, never read in part.
                text, truncated = await asyncio.to_thread(
                    safe_read.read_text_under,
                    root,
                    relative,
                    max_chars=MAX_FILE_CHARS,
                    max_bytes=MAX_FILE_BYTES,
                )
        except FileCompareError:
            raise
        except safe_read.SafeReadError as exc:
            raise FileCompareError(
                _FILE_MESSAGES.get(exc.code, _FILE_MESSAGES["unreadable"])
            ) from exc
        except Exception as exc:
            logger.exception("AI assistant: file compare checkout failed")
            raise FileCompareError(
                "The repository could not be updated or read; try again or ask an administrator"
            ) from exc
        if truncated:
            raise FileCompareError(_FILE_MESSAGES["too_large"])
        return relative, text

    async def compare(self, request: CompareRequest) -> CompareOutcome:
        await asyncio.to_thread(self._check_permission)
        await asyncio.to_thread(self._check_rate)
        try:
            delimiter = parse_delimiter(request.delimiter)
        except CsvLookupError as exc:
            raise FileCompareError(str(exc)) from exc
        repositories = await asyncio.to_thread(self._load_repositories)
        chosen = select_repository(repositories, request.repository)
        relative, text = await self._read_file(chosen, request.file)
        try:
            rows = await asyncio.to_thread(
                parse_csv_rows,
                text,
                key_column=request.key_column,
                delimiter=delimiter,
                label="the file",
            )
        except KeyColumnNotFoundError as exc:
            raise FileCompareError(
                "The key column was not found in the file", columns=exc.columns
            ) from exc
        except CsvLookupError as exc:
            raise FileCompareError(str(exc)) from exc
        filters = {k: v for k, v in request.filters.items() if k in _FILTER_NAMES and v}
        try:
            fetched = await self._fetch_values(request.field, filters)
        except NautobotAccessError as exc:
            raise FileCompareDeniedError from exc
        except EXPECTED_ERRORS as exc:  # written for the model: closest names, "add a filter"
            raise FileCompareError(str(exc)) from exc
        items = [
            ValueItem(
                id=str(row["id"]),
                value=row.get("value"),
                info={
                    "name": str(row.get("name") or ""),
                    "location": str(row.get("location") or ""),
                },
            )
            for row in fetched["items"]
        ]
        try:
            result = await asyncio.to_thread(
                reconcile,
                rows,
                items,
                contains=request.match_mode == "contains",
                case_insensitive=request.case_insensitive,
                normalizer=_NORMALIZERS.get(request.field),
                max_comparisons=MAX_COMPARISONS,
            )
        except ReconcileTooLargeError as exc:
            raise FileCompareError(str(exc)) from exc
        return CompareOutcome(
            repository=str(chosen["name"]),
            file=relative,
            request=request,
            reconciliation=result,
            applied_filters=fetched.get("applied_filters") or {},
        )
