"""``list_config_backups`` / ``get_config_backup``: device configs from the git backup (plan
doc/plans/AI_CONFIG_FROM_GIT.md).

Pure reads. The model gives a device name and a kind; the path comes from the template on the
repository row, never from the model. The text is class C content: it is redacted with the user's
exact secret values before it is stored behind a handle, and the tools are only offered with the
content opt-in.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from services.ai_assistant.config_backup import (
    BackupRepository,
    ConfigBackup,
    ConfigBackupError,
    ConfigBackupReader,
)
from services.ai_assistant.data_sharing import DataClass, not_shared_marker
from services.ai_assistant.results.store import ResultStoreUnavailableError, StoredResult
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.tools.result_tools import RESULT_STORE_KEY

logger = logging.getLogger(__name__)

# Key of the ``ConfigBackupReader`` in ``ToolContext.extras``; the surface builder puts it there.
CONFIG_READER_KEY = "config_backup_reader"
HANDLE_KIND = "config_backup"
PREVIEW_CHARS = 3000
# Redaction budget for the stored copy (a config can be large); separate from the request's own.
STORED_REDACT_CHARS = 2_100_000

DeviceName = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9._-]{1,100}$")
]
RepositoryName = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9._ -]{1,255}$")
]


class ListConfigBackupsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetConfigBackupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device: DeviceName = Field(description="Device name exactly as in the inventory, e.g. 'LAB'")
    kind: Literal["running", "startup"] = Field(
        default="running", description="Which backed-up configuration to read"
    )
    repository: RepositoryName | None = Field(
        default=None,
        description="Repository name from list_config_backups; only needed when several match",
    )


def _reader(ctx: ToolContext) -> ConfigBackupReader:
    return ctx.extras[CONFIG_READER_KEY]


def _age(committed_at: str | None) -> str | None:
    if committed_at is None:
        return None
    seconds = (datetime.now(UTC) - datetime.fromisoformat(committed_at)).total_seconds()
    days, rest = divmod(max(int(seconds), 0), 86400)
    hours = rest // 3600
    if days:
        return f"{days} day(s) {hours} hour(s)"
    return f"{hours} hour(s)" if hours else f"{rest // 60} minute(s)"


def _repository_row(repo: BackupRepository) -> dict[str, object]:
    return {
        "name": repo.name,
        "branch": repo.branch,
        "kinds": list(repo.kinds),
        "last_sync": repo.last_sync,
    }


async def _list_config_backups(ctx: ToolContext, args: ListConfigBackupsInput) -> ToolOutput:
    if not ctx.sharing.allows(DataClass.INVENTORY):
        return ToolOutput(json.dumps(not_shared_marker(DataClass.INVENTORY)))
    try:
        repositories = await _reader(ctx).list_repositories()
    except ConfigBackupError as exc:
        return ToolOutput(str(exc), is_error=True)
    if not repositories:
        return ToolOutput(
            json.dumps(
                {
                    "repositories": [],
                    "note": "No git repository has a config path configured; use "
                    "propose_device_command for the live configuration.",
                }
            )
        )
    return ToolOutput(json.dumps({"repositories": [_repository_row(r) for r in repositories]}))


_TRUNCATED_MARKER = (
    "\n…[backup truncated: the file is longer than the limit; the rest is not shown]"
)


async def _store(ctx: ToolContext, text: str) -> str | None:
    """Store the already redacted ``text``; ``None`` when there is no store or it is too large."""
    store = ctx.extras.get(RESULT_STORE_KEY)
    if store is None:
        return None
    try:
        return await store.put(
            ctx.user_id, StoredResult(kind=HANDLE_KIND, data_class=DataClass.CONTENT, text=text)
        )
    except ResultStoreUnavailableError:
        logger.warning("Result store unavailable; config backup returned without a handle")
    except ValueError:
        logger.info("Config backup too large for one handle; returned without a handle")
    return None


def _answer(backup: ConfigBackup, preview: str, handle: str | None, cut: bool) -> dict[str, object]:
    answer: dict[str, object] = {
        "repository": backup.repository,
        "committed_at": backup.committed_at,
        "age": _age(backup.committed_at),
        "source": "git backup, not the live device",
        "preview": preview,
    }
    if handle is not None:
        answer["handle"] = handle
        answer["note"] = "Read the rest with fetch_slice(handle, offset)."
    elif cut:
        answer["note"] = (
            "The text was cut and no handle could be stored; say the answer is partial."
        )
    if backup.truncated:
        answer["truncated"] = "The file is longer than the size limit; only the start is available."
    return answer


async def _get_config_backup(ctx: ToolContext, args: GetConfigBackupInput) -> ToolOutput:
    if not ctx.sharing.allows(DataClass.CONTENT):
        return ToolOutput(json.dumps(not_shared_marker(DataClass.CONTENT)))
    try:
        backup = await _reader(ctx).read(args.device, args.kind, args.repository)
    except ConfigBackupError as exc:
        return ToolOutput(str(exc), is_error=True)
    ctx.audit_refs.add(f"config:{args.device}")
    # Redact the whole text first and cut second: a secret that straddles the preview cut (or the
    # file size cut, which the reader makes on a line boundary) is already gone. The copy has its
    # own character budget, separate from the request's.
    try:
        redacted = await asyncio.to_thread(
            ctx.redactor.fork(max_chars=STORED_REDACT_CHARS).redact, backup.text
        )
    except ValueError:  # redaction budget exceeded: show nothing rather than unredacted text
        return ToolOutput("The backup is too large to redact safely", is_error=True)
    if backup.truncated:
        redacted += _TRUNCATED_MARKER
    handle = await _store(ctx, redacted)
    preview = redacted[:PREVIEW_CHARS]
    cut = len(redacted) > PREVIEW_CHARS
    return ToolOutput(
        json.dumps(_answer(backup, preview, handle, cut)), truncated=cut and handle is None
    )


def build_config_backup_tools() -> list[Tool]:
    return [
        Tool(
            "list_config_backups",
            "List the git repositories that hold device configuration backups (name, branch, "
            "which of running/startup they have, last sync). No paths or URLs.",
            ListConfigBackupsInput,
            _list_config_backups,
        ),
        Tool(
            "get_config_backup",
            "Read a device's backed-up running or startup configuration from git (no SSH, "
            "instant). The answer says when the backup was committed; it may be older than the "
            "live device. For the current config use propose_device_command.",
            GetConfigBackupInput,
            _get_config_backup,
        ),
    ]
