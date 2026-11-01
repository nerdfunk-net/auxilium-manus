"""Read a device's backed-up configuration from a ``device_configs`` git repository.

Doc: doc/plans/AI_CONFIG_FROM_GIT.md. The model names a device and a kind (running / startup); the
path comes from the template stored on the repository row (``config_path_running`` /
``config_path_startup``), rendered in code with the ``read-config`` placeholder language. Nothing
here lets the model choose a path, a ref or a repository location.

The pure parts (``build_device_context``, ``render_path``, ``contain``, ``read_backup_text``) are
separate from ``DbConfigBackupReader`` so they can be tested with a temporary directory.
"""

from __future__ import annotations

import asyncio
import codecs
import logging
import os
import re
import stat
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

import service_factory
from core.database import SessionLocal
from dependencies import nautobot_credentials_from_source_id
from models.workflow_context import DeviceContext
from services.ai_assistant.device_access import DeviceAccessError, ResolvedDevice
from services.auth.login_rate_limiter import RateLimitExceededError
from services.auth.rbac_service import RBACService
from services.git.repository_service import GitRepositoryService
from services.git.sync import agit_checkout
from services.workflow_context.device_template import (
    TemplateRenderOptions,
    TemplateResolutionError,
    render_device_template,
)

logger = logging.getLogger(__name__)

ConfigKind = Literal["running", "startup"]
CATEGORY = "device_configs"
MAX_CONFIG_CHARS = 2_000_000
RATE_BUCKET = "ai-config-backup"
RATE_ATTEMPTS = 20
RATE_WINDOW_SECONDS = 60
_KEY_IN_MESSAGE = re.compile(r"\{([a-zA-Z0-9_.]+)\}")


class ConfigBackupError(Exception):
    """The message is fixed text, safe to show to the user and to the model."""


class ConfigBackupDeniedError(ConfigBackupError):
    def __init__(self) -> None:
        super().__init__("You are not allowed to read files from git repositories")


@dataclass(frozen=True)
class BackupRepository:
    name: str
    branch: str
    kinds: tuple[ConfigKind, ...]
    last_sync: str | None


@dataclass(frozen=True)
class ConfigBackup:
    text: str
    repository: str
    relative_path: str
    committed_at: str | None  # ISO 8601 UTC of the last commit that touched the file
    truncated: bool = False  # the file is longer than MAX_CONFIG_CHARS; ``text`` is a prefix


class BackupDeviceResolver(Protocol):
    """Finds a device by name; a missing management address is fine (nothing connects)."""

    async def resolve_without_address(self, name: str) -> ResolvedDevice: ...


class ConfigBackupReader(Protocol):
    async def list_repositories(self) -> list[BackupRepository]: ...

    async def read(
        self, device_name: str, kind: ConfigKind, repository: str | None
    ) -> ConfigBackup: ...


def build_device_context(device: ResolvedDevice, nautobot_bag: dict[str, Any]) -> DeviceContext:
    """The minimal context the placeholder renderer needs (``device.*`` and ``nautobot.*``)."""
    return DeviceContext(
        id=device.device_id,
        name=device.name,
        hostname=device.name,
        platform=device.platform,
        network_driver=device.network_driver,
        primary_ip4=device.host or None,
        source="nautobot",
        source_id=device.source_id,
        attribute_bags={"nautobot": dict(nautobot_bag)},
    )


def render_path(template: str, context: DeviceContext) -> str:
    """The relative path for this device; errors name the placeholder, never a value."""
    try:
        return render_device_template(
            template, context, options=TemplateRenderOptions(strict=True, run_id=None)
        )
    except TemplateResolutionError as exc:
        found = _KEY_IN_MESSAGE.search(str(exc))
        key = f"{{{found.group(1)}}}" if found else "a placeholder"
        raise ConfigBackupError(
            f"The config path template needs {key}, but it is empty for this device"
        ) from exc
    except ValueError as exc:
        raise ConfigBackupError("The config path template gives an unusable path") from exc


def contain(root: Path, relative: str) -> Path:
    """``root / relative``; refuses a path that leaves ``root``, enters ``.git`` or crosses a link.

    Every component below ``root`` is checked with ``lstat`` before anything is resolved, so a
    symlink (a file or a directory) is refused even when it points at another file in the same
    checkout: the bytes of one device must not be reported as another device's backup.
    """
    resolved_root = root.resolve()
    candidate = resolved_root / relative
    try:
        parts = candidate.relative_to(resolved_root).parts
    except ValueError as exc:
        raise ConfigBackupError("The config path leaves the repository") from exc
    if ".." in parts or ".git" in parts:
        raise ConfigBackupError("The config path leaves the repository")
    current = resolved_root
    for part in parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            break  # the rest does not exist; the read reports a missing file
        except OSError as exc:
            raise ConfigBackupError("The backup file cannot be read") from exc
        if stat.S_ISLNK(mode):
            raise ConfigBackupError("The backup path is a symbolic link")
    return candidate


_OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)


def _cut_on_line(text: str, limit: int) -> str:
    """At most ``limit`` characters, ending on a line boundary when one is near the end, so a
    one-line secret is never split before redaction."""
    head = text[:limit]
    newline = head.rfind("\n")
    return head[:newline] if newline > limit // 2 else head


def read_backup_text(target: Path) -> tuple[str, bool]:
    """``(text, truncated)``: a regular file only (no symlink), strict UTF-8, at most
    ``MAX_CONFIG_CHARS`` characters. Not cached: a backup can be large and is read rarely."""
    try:
        fd = os.open(target, _OPEN_FLAGS)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise ConfigBackupError("No backup file exists for this device") from exc
    except OSError as exc:  # includes a symlink, refused by O_NOFOLLOW
        raise ConfigBackupError("The backup file cannot be read") from exc
    try:
        info = os.fstat(fd)
        if stat.S_ISDIR(info.st_mode):
            raise ConfigBackupError("No backup file exists for this device")
        if not stat.S_ISREG(info.st_mode):
            raise ConfigBackupError("The backup path is not a regular file")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            # Four bytes per character is the UTF-8 maximum, so the cap never cuts a limit short.
            limit = MAX_CONFIG_CHARS * 4
            data = handle.read(limit + 1)
    except OSError as exc:
        raise ConfigBackupError("The backup file cannot be read") from exc
    finally:
        os.close(fd)
    cut_bytes = len(data) > limit
    try:
        # With ``final=False`` a character split by the byte cap is held back, not an error.
        text = codecs.getincrementaldecoder("utf-8")().decode(data[:limit], final=not cut_bytes)
    except UnicodeDecodeError as exc:
        raise ConfigBackupError("The backup file is not valid UTF-8 text") from exc
    if cut_bytes or len(text) > MAX_CONFIG_CHARS:
        return _cut_on_line(text, MAX_CONFIG_CHARS), True
    return text, False


def last_commit_time(root: Path, relative: str) -> str | None:
    """ISO UTC time of the newest commit touching ``relative``; ``None`` when unknown."""
    from git import Repo

    try:
        repo = Repo(root)
        commit = next(repo.iter_commits(paths=relative, max_count=1), None)
    except Exception:
        logger.info("AI assistant: commit time of a config backup is unavailable", exc_info=True)
        return None
    if commit is None:
        return None
    return datetime.fromtimestamp(commit.committed_date, UTC).isoformat()


def _template_for(repository: dict[str, Any], kind: ConfigKind) -> str | None:
    value = repository.get(f"config_path_{kind}")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _kinds(repository: dict[str, Any]) -> tuple[ConfigKind, ...]:
    kinds: list[ConfigKind] = []
    for kind in ("running", "startup"):
        if _template_for(repository, kind):
            kinds.append(kind)
    return tuple(kinds)


def select_repository(
    repositories: list[dict[str, Any]], kind: ConfigKind, name: str | None
) -> dict[str, Any]:
    """The one active repository with a template for ``kind`` (and ``name``, when given)."""
    usable = [r for r in repositories if _template_for(r, kind) and r.get("is_active", True)]
    if name is not None:
        usable = [r for r in usable if r.get("name") == name]
        if not usable:
            raise ConfigBackupError(f"No config backup repository named '{name}' has a {kind} path")
    if not usable:
        raise ConfigBackupError(f"No git repository has a {kind} config path configured")
    if len(usable) > 1:
        names = ", ".join(sorted(str(r["name"]) for r in usable))
        raise ConfigBackupError(
            f"More than one repository has a {kind} config path ({names}); "
            "ask the user which one, then pass it as 'repository'"
        )
    return usable[0]


AttributeFetcher = Callable[[ResolvedDevice], Awaitable[dict[str, Any]]]
Checkout = Callable[[dict[str, Any]], AbstractAsyncContextManager[Path]]


class DbConfigBackupReader:
    """Reads backups as the calling user. Injectable parts keep the unit tests off the network."""

    def __init__(
        self,
        user_id: int,
        resolver: BackupDeviceResolver,
        *,
        fetch_attributes: AttributeFetcher | None = None,
        checkout: Checkout | None = None,
        load_repositories: Callable[[], list[dict[str, Any]]] | None = None,
        check_permission: Callable[[], None] | None = None,
        check_rate: Callable[[], None] | None = None,
    ) -> None:
        self._user_id = user_id
        self._resolver = resolver
        self._fetch_attributes = fetch_attributes or self._nautobot_attributes
        self._checkout = checkout or (lambda repo: agit_checkout(repo))
        self._load_repositories = load_repositories or self._db_repositories
        self._check_permission = check_permission or self._db_permission
        self._check_rate = check_rate or self._rate_limit

    def _db_permission(self) -> None:
        with SessionLocal() as db:
            if not RBACService(db).has_permission(self._user_id, "git.files", "read"):
                raise ConfigBackupDeniedError

    def _rate_limit(self) -> None:
        limiter = service_factory.build_user_rate_limiter(
            RATE_BUCKET, RATE_ATTEMPTS, RATE_WINDOW_SECONDS
        )
        try:
            limiter.check(f"{RATE_BUCKET}:{self._user_id}")
        except RateLimitExceededError as exc:
            raise ConfigBackupError("Too many config backup reads; try again shortly") from exc

    @staticmethod
    def _db_repositories() -> list[dict[str, Any]]:
        with SessionLocal() as db:
            return GitRepositoryService(db).get_repositories(category=CATEGORY, active_only=True)

    async def _nautobot_attributes(self, device: ResolvedDevice) -> dict[str, Any]:
        def credentials() -> Any:
            with SessionLocal() as db:
                return nautobot_credentials_from_source_id(device.source_id, db)

        try:
            creds = await asyncio.to_thread(credentials)
            service = service_factory.build_nautobot_source_service(creds)
            return await service.get_device_attributes(device.device_id, None)
        except Exception as exc:
            logger.info("AI assistant: Nautobot attributes unavailable for a config backup")
            raise ConfigBackupError("The device's inventory attributes could not be read") from exc

    async def list_repositories(self) -> list[BackupRepository]:
        await asyncio.to_thread(self._check_permission)
        repositories = await asyncio.to_thread(self._load_repositories)
        return [
            BackupRepository(
                name=str(r["name"]),
                branch=str(r.get("branch") or ""),
                kinds=_kinds(r),
                last_sync=r.get("last_sync"),
            )
            for r in repositories
            if _kinds(r)
        ]

    async def read(
        self, device_name: str, kind: ConfigKind, repository: str | None
    ) -> ConfigBackup:
        await asyncio.to_thread(self._check_permission)
        await asyncio.to_thread(self._check_rate)
        repositories = await asyncio.to_thread(self._load_repositories)
        chosen = select_repository(repositories, kind, repository)
        try:
            device = await self._resolver.resolve_without_address(device_name)
        except DeviceAccessError as exc:
            raise ConfigBackupError(str(exc)) from exc
        bag = await self._fetch_attributes(device)
        template = _template_for(chosen, kind)
        if template is None:  # select_repository only returns repositories with one
            raise ConfigBackupError(f"No {kind} config path is configured")
        relative = render_path(template, build_device_context(device, bag))
        try:
            async with self._checkout(chosen) as root:
                target = contain(root, relative)
                text, truncated = await asyncio.to_thread(read_backup_text, target)
                committed = await asyncio.to_thread(last_commit_time, root, relative)
        except ConfigBackupError:
            raise
        except Exception as exc:
            logger.exception("AI assistant: config backup checkout failed")
            raise ConfigBackupError(
                "The repository could not be updated or read; try again or ask an administrator"
            ) from exc
        return ConfigBackup(
            text=text,
            repository=str(chosen["name"]),
            relative_path=relative,
            committed_at=committed,
            truncated=truncated,
        )
