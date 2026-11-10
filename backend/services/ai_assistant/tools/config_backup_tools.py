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
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from services.ai_assistant.config_backup import (
    BackupRepository,
    ConfigBackup,
    ConfigBackupError,
    ConfigBackupReader,
    ConfigKind,
    ConfigSearchResult,
)
from services.ai_assistant.config_sections import (
    MAX_PATTERN_CHARS,
    Section,
    TopicName,
    outline,
    select_by_prefix,
    select_by_regex,
    select_by_topic,
    split_sections,
)
from services.ai_assistant.data_sharing import DataClass, not_shared_marker
from services.ai_assistant.results.store import (
    MAX_STORED_BYTES,
    ResultStoreUnavailableError,
    StoredResult,
)
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.tools.result_tools import RESULT_STORE_KEY

logger = logging.getLogger(__name__)

# Key of the ``ConfigBackupReader`` in ``ToolContext.extras``; the surface builder puts it there.
CONFIG_READER_KEY = "config_backup_reader"
HANDLE_KIND = "config_backup"
PREVIEW_CHARS = 3000
# A config above this many characters (about 400 lines) is "large": the model shows the preview and
# asks whether the user wants a download, instead of paging the whole file into the chat.
LARGE_CONFIG_CHARS = 15_000
CONFIG_DOWNLOAD_KIND = "config_download"
# What the stored text may take in the store: the JSON envelope and ``meta`` need some room.
_STORE_TEXT_BUDGET_BYTES = MAX_STORED_BYTES - 16_384
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


class SearchConfigBackupsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        min_length=1,
        max_length=200,
        description="Text to look for (e.g. 'logging host 1.2.3.4'), or a regular expression "
        "when mode is 'regex'",
    )
    mode: Literal["text", "regex"] = Field(
        default="text",
        description="'text' is a plain substring match (use it for words and IP addresses); "
        "'regex' is a Python regular expression applied per line (escape dots)",
    )
    case_sensitive: bool = Field(default=False)
    kind: Literal["running", "startup"] = Field(
        default="running", description="Which backed-up configuration to search"
    )
    repository: RepositoryName | None = Field(
        default=None,
        description="Repository name from list_config_backups; only needed when several match",
    )
    limit: int = Field(default=50, ge=1, le=200, description="Most files to list")

    @field_validator("query")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must contain more than spaces")
        return value


class GetConfigSectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device: DeviceName = Field(description="Device name exactly as in the inventory, e.g. 'LAB'")
    kind: Literal["running", "startup"] = Field(default="running")
    repository: RepositoryName | None = Field(
        default=None,
        description="Repository name from list_config_backups; only needed when several match",
    )
    topic: TopicName | None = Field(
        default=None,
        description="A named group of sections: routing (all routing protocols, static routes, "
        "route policy, VRFs), ospf, bgp, eigrp, isis, rip, static_routes, route_policy, vrf, "
        "interfaces, access_lists (ACLs, object-groups), vty_lines (line vty/console/aux), "
        "authentication (aaa, tacacs, radius, usernames, enable, ssh login settings)",
    )
    starts_with: str | None = Field(
        default=None,
        max_length=200,
        description="Sections whose first line begins with this text, e.g. 'router ospf 100' or "
        "'interface GigabitEthernet0/0'. Case-insensitive; whole words first, else any prefix.",
    )
    header_regex: str | None = Field(
        default=None,
        max_length=MAX_PATTERN_CHARS,
        description="Sections whose first line matches this regular expression (escape dots)",
    )

    @model_validator(mode="after")
    def _at_most_one_selector(self) -> Self:
        chosen = [x for x in (self.topic, self.starts_with, self.header_regex) if x]
        if len(chosen) > 1:
            raise ValueError("give only one of topic, starts_with and header_regex")
        return self


class OfferConfigDownloadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handle: Annotated[str, StringConstraints(pattern=r"^res_[0-9a-f]{12}$")] = Field(
        description="The handle returned by get_config_backup"
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


STORE_CUT_MARKER = "\n…[backup cut to fit the download store: the rest of the file is not included]"

_TRUNCATED_MARKER = (
    "\n…[backup truncated: the file is longer than the limit; the rest is not shown]"
)


def _json_bytes(text: str) -> int:
    """Size of ``text`` as the store writes it (UTF-8, every newline escaped to two bytes)."""
    return len(json.dumps(text, ensure_ascii=False).encode("utf-8"))


def fit_to_store(text: str) -> tuple[str, bool]:
    """``text`` cut on a line boundary so the stored document stays under the store's cap.

    The reader's character cap is not enough: JSON turns each newline into two bytes, so a file
    just under the cap would be refused and the user would get no download at all. Returns the
    text (with a marker when it was cut) and whether it was cut.
    """
    size = _json_bytes(text)
    if size <= _STORE_TEXT_BUDGET_BYTES:
        return text, False
    budget = _STORE_TEXT_BUDGET_BYTES - _json_bytes(STORE_CUT_MARKER)
    end = len(text)
    # The size is nearly linear in the length, so a few proportional cuts converge.
    for _ in range(8):
        end = int(end * budget / size * 0.99)
        newline = text.rfind("\n", 0, end)
        end = newline + 1 if newline > 0 else end
        size = _json_bytes(text[:end])
        if size <= budget:
            break
    return text[:end] + STORE_CUT_MARKER, True


async def _store(
    ctx: ToolContext, text: str, meta: dict[str, object], *, partial: bool = False
) -> str | None:
    """Store the already redacted ``text``; ``None`` when there is no store or it is too large.

    ``meta`` says where the text came from, so the download card can name the file.
    """
    store = ctx.extras.get(RESULT_STORE_KEY)
    if store is None:
        return None
    try:
        return await store.put(
            ctx.user_id,
            StoredResult(
                kind=HANDLE_KIND,
                data_class=DataClass.CONTENT,
                text=text,
                partial=partial,
                meta=meta,
            ),
        )
    except ResultStoreUnavailableError:
        logger.warning("Result store unavailable; config backup returned without a handle")
    except ValueError:
        logger.info("Config backup too large for one handle; returned without a handle")
    return None


_LARGE_NOTE = (
    "This configuration is large. Show the preview and the size, do not page through the whole "
    "file with fetch_slice, and ask whether the user wants a download. If they say yes (or asked "
    "for a download), call offer_config_download with the handle."
)


def _answer(
    backup: ConfigBackup, redacted: str, handle: str | None, cut: bool, *, store_cut: bool = False
) -> dict[str, object]:
    large = len(redacted) > LARGE_CONFIG_CHARS
    answer: dict[str, object] = {
        "repository": backup.repository,
        "committed_at": backup.committed_at,
        "age": _age(backup.committed_at),
        "source": "git backup, not the live device",
        "preview": redacted[:PREVIEW_CHARS],
        "size_chars": len(redacted),
        "line_count": len(redacted.splitlines()),
        "large": large,
    }
    if handle is not None:
        answer["handle"] = handle
        answer["note"] = _LARGE_NOTE if large else "Read the rest with fetch_slice(handle, offset)."
    elif cut:
        answer["note"] = (
            "The text was cut and no handle could be stored; say the answer is partial."
        )
    if backup.truncated or store_cut:
        answer["truncated"] = "The file is longer than the size limit; only the start is available."
    return answer


async def _read_redacted(
    ctx: ToolContext, device: str, kind: ConfigKind, repository: str | None
) -> tuple[ConfigBackup, str, bool] | ToolOutput:
    """Read a backup and return ``(backup, redacted text, cut to fit the store)``.

    Redact the whole text first and cut second: a secret that straddles the preview cut (or the
    file size cut, which the reader makes on a line boundary) is already gone. The copy has its
    own character budget, separate from the request's.
    """
    try:
        backup = await _reader(ctx).read(device, kind, repository)
    except ConfigBackupError as exc:
        return ToolOutput(str(exc), is_error=True)
    ctx.audit_refs.add(f"config:{device}")
    try:
        redacted = await asyncio.to_thread(
            ctx.redactor.fork(max_chars=STORED_REDACT_CHARS).redact, backup.text
        )
    except ValueError:  # redaction budget exceeded: show nothing rather than unredacted text
        return ToolOutput("The backup is too large to redact safely", is_error=True)
    if backup.truncated:
        redacted += _TRUNCATED_MARKER
    # The text the store keeps and the text the answer describes are the same one.
    redacted, store_cut = fit_to_store(redacted)
    return backup, redacted, store_cut


async def _get_config_backup(ctx: ToolContext, args: GetConfigBackupInput) -> ToolOutput:
    if not ctx.sharing.allows(DataClass.CONTENT):
        return ToolOutput(json.dumps(not_shared_marker(DataClass.CONTENT)))
    read = await _read_redacted(ctx, args.device, args.kind, args.repository)
    if isinstance(read, ToolOutput):
        return read
    backup, redacted, store_cut = read
    meta = {
        "device": args.device,
        "kind": args.kind,
        "repository": backup.repository,
        "committed_at": backup.committed_at,
        # fetch_slice refuses a large config: it is for the download, not for the chat.
        "no_paging": len(redacted) > LARGE_CONFIG_CHARS,
    }
    handle = await _store(ctx, redacted, meta, partial=backup.truncated or store_cut)
    cut = len(redacted) > PREVIEW_CHARS
    return ToolOutput(
        json.dumps(_answer(backup, redacted, handle, cut, store_cut=store_cut)),
        truncated=cut and handle is None,
    )


# What one answer may carry of the section text (the tool output cap is 20,000 characters).
SECTION_TEXT_BUDGET = 14_000
OUTLINE_MAX_ENTRIES = 150


def _select(sections: list[Section], args: GetConfigSectionInput) -> list[Section] | None:
    """The sections the arguments ask for; ``None`` when no selector was given."""
    if args.topic:
        return select_by_topic(sections, args.topic)
    if args.starts_with and args.starts_with.strip():
        return select_by_prefix(sections, args.starts_with.strip())
    if args.header_regex:
        return select_by_regex(sections, args.header_regex)
    return None


def _section_answer(
    backup: ConfigBackup, selected: list[Section], handle: str | None, shown: list[Section]
) -> dict[str, object]:
    answer: dict[str, object] = {
        "repository": backup.repository,
        "committed_at": backup.committed_at,
        "age": _age(backup.committed_at),
        "source": "git backup, not the live device",
        "sections_found": len(selected),
        "sections": [
            {"header": s.header[:200], "lines": f"{s.start_line}-{s.end_line}", "text": s.text}
            for s in shown
        ],
    }
    if len(shown) < len(selected):
        answer["truncated"] = True
        omitted = [outline([s])[0] for s in selected[len(shown) :][:OUTLINE_MAX_ENTRIES]]
        answer["not_shown"] = omitted
        answer["note"] = (
            f"{len(selected) - len(shown)} more section(s) did not fit; they are listed in "
            "not_shown. Ask for one of them with starts_with, or offer a download of the part."
        )
    if handle is not None:
        answer["handle"] = handle
    return answer


async def _get_config_section(ctx: ToolContext, args: GetConfigSectionInput) -> ToolOutput:
    if not ctx.sharing.allows(DataClass.CONTENT):
        return ToolOutput(json.dumps(not_shared_marker(DataClass.CONTENT)))
    read = await _read_redacted(ctx, args.device, args.kind, args.repository)
    if isinstance(read, ToolOutput):
        return read
    backup, redacted, _store_cut = read
    sections = split_sections(redacted)
    try:
        selected = await asyncio.to_thread(_select, sections, args)
    except ValueError as exc:
        return ToolOutput(str(exc), is_error=True)
    if selected is None:
        # No selector: the outline of the whole config, so the model can pick a header.
        entries = outline(sections)
        return ToolOutput(
            json.dumps(
                {
                    "repository": backup.repository,
                    "age": _age(backup.committed_at),
                    "source": "git backup, not the live device",
                    "section_count": len(sections),
                    "outline": entries[:OUTLINE_MAX_ENTRIES],
                    "outline_cut": len(entries) > OUTLINE_MAX_ENTRIES,
                    "note": "Call again with topic, starts_with or header_regex to read sections.",
                }
            )
        )
    if not selected:
        return ToolOutput(
            json.dumps(
                {
                    "sections_found": 0,
                    "source": "git backup, not the live device",
                    "note": "No section matches. Call without a selector to see the outline.",
                }
            )
        )
    shown: list[Section] = []
    used = 0
    for section in selected:
        if shown and used + len(section.text) > SECTION_TEXT_BUDGET:
            break
        if not shown and len(section.text) > SECTION_TEXT_BUDGET:
            # One section alone is larger than an answer: cut it on a line and say so.
            cut = section.text[:SECTION_TEXT_BUDGET].rsplit("\n", 1)[0]
            section = Section(
                section.header, section.start_line, section.end_line, cut + "\n…[cut]"
            )
        shown.append(section)
        used += len(section.text)
    handle = None
    if len(shown) < len(selected) or any(s.text.endswith("…[cut]") for s in shown):
        # The part the user asked for is bigger than the chat answer: keep it for a download.
        part, part_cut = fit_to_store("\n!\n".join(s.text for s in selected))
        meta = {
            "device": args.device,
            "kind": args.kind,
            "repository": backup.repository,
            "committed_at": backup.committed_at,
            "no_paging": True,
            "part": args.topic or args.starts_with or args.header_regex,
        }
        handle = await _store(ctx, part, meta, partial=part_cut)
    return ToolOutput(json.dumps(_section_answer(backup, selected, handle, shown)))


async def _offer_config_download(ctx: ToolContext, args: OfferConfigDownloadInput) -> ToolOutput:
    """A download card for a config the user already fetched; nothing is read or sent to the model.

    The card only carries the handle. The download route re-checks owner, kind and the content
    opt-in, so a forged proposal gives the client nothing.
    """
    if not ctx.sharing.allows(DataClass.CONTENT):
        return ToolOutput(json.dumps(not_shared_marker(DataClass.CONTENT)))
    store = ctx.extras.get(RESULT_STORE_KEY)
    if store is None:
        return ToolOutput("Downloads are not available: no result store.", is_error=True)
    try:
        stored = await store.get(ctx.user_id, args.handle)
    except ResultStoreUnavailableError:
        return ToolOutput("Stored results are unavailable right now.", is_error=True)
    if stored is None or stored.kind != HANDLE_KIND or stored.text is None:
        return ToolOutput(
            "Unknown or expired handle. Call get_config_backup again and use its handle.",
            is_error=True,
        )
    meta = stored.meta or {}
    proposal = {
        "kind": CONFIG_DOWNLOAD_KIND,
        "handle": args.handle,
        "device": str(meta.get("device", "")),
        "config_kind": str(meta.get("kind", "")),
        "repository": str(meta.get("repository", "")),
        "committed_at": meta.get("committed_at"),
        "size_chars": len(stored.text),
        "line_count": len(stored.text.splitlines()),
        "partial": stored.partial,
    }
    return ToolOutput(
        "A download button for the configuration was shown to the user. Do not paste the "
        "configuration into the chat; say briefly that it is ready to download and that the "
        "download stays available for a few hours.",
        proposal=proposal,
    )


# The tool output cap is 20,000 characters (tools/base.py); a cut in the middle of the JSON would
# hand the model invalid JSON, so the answer is shrunk to fit before it is serialised.
SEARCH_OUTPUT_BUDGET = 15_000


def _search_answer(result: ConfigSearchResult) -> dict[str, object]:
    answer: dict[str, object] = {
        "repository": result.repository,
        "branch": result.branch,
        "kind": result.kind,
        "source": "git backup, not the live devices",
        "total_files": result.total_files,
        "total_devices": result.total_devices,
        "files_scanned": result.files_scanned,
        "matches": [
            {
                "device": hit.device,
                "path": hit.path,
                "lines": [{"line": number, "text": text} for number, text in hit.lines],
            }
            for hit in result.hits
        ],
    }
    notes: list[str] = []
    if result.partial:
        answer["partial"] = True
        notes.append(
            f"The result may be incomplete: {result.skipped} file(s) were not searched (too "
            "large, not text, a link or stopped), or a file or time limit was reached. Say so."
        )
    if result.truncated:
        answer["truncated"] = True
        notes.append("More files match than are listed; narrow the query or raise limit.")
    if notes:
        answer["note"] = " ".join(notes)
    return answer


def _fit(answer: dict[str, object]) -> dict[str, object]:
    """Fewer lines per file first (all files stay listed), then fewer files; say what was cut."""
    matches = list(answer["matches"])  # type: ignore[arg-type]

    def build(keep: int, count: int) -> dict[str, object]:
        return {
            **answer,
            "matches": [{**m, "lines": m["lines"][:keep]} for m in matches[:count]],
        }

    def fits(candidate: dict[str, object]) -> bool:
        return len(json.dumps(candidate)) <= SEARCH_OUTPUT_BUDGET

    for keep in (3, 1, 0):
        if fits(candidate := build(keep, len(matches))):
            if keep < 3 and any(len(m["lines"]) > keep for m in matches):
                candidate["output_cut"] = True
                candidate["note"] = (
                    f"{answer.get('note', '')} Only the first {keep} matching line(s) per file "
                    "are shown.".strip()
                )
            return candidate
    count = len(matches)
    while count > 0 and not fits(build(0, count)):
        count -= 1
    candidate = build(0, count)
    candidate["output_cut"] = True
    candidate["note"] = (
        f"{answer.get('note', '')} Only {count} of {len(matches)} files fit in this answer and "
        "without their lines; narrow the query to see the rest."
    ).strip()
    return candidate


async def _search_config_backups(ctx: ToolContext, args: SearchConfigBackupsInput) -> ToolOutput:
    if not ctx.sharing.allows(DataClass.CONTENT):
        return ToolOutput(json.dumps(not_shared_marker(DataClass.CONTENT)))

    def redact(text: str) -> str:
        # A fork per file: the redaction budget is per text, not for the whole search.
        return ctx.redactor.fork(max_chars=STORED_REDACT_CHARS).redact(text)

    try:
        result = await _reader(ctx).search(
            args.query,
            args.mode,
            args.kind,
            args.case_sensitive,
            args.repository,
            args.limit,
            redact,
        )
    except ConfigBackupError as exc:
        return ToolOutput(str(exc), is_error=True)
    ctx.audit_refs.add(f"config-search:{result.repository}")
    return ToolOutput(json.dumps(_fit(_search_answer(result))))


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
        Tool(
            "get_config_section",
            "Read parts of a backed-up device configuration (git backup, no SSH): a topic such as "
            "routing, ospf or bgp, the sections that start with a line like 'router ospf 100', or "
            "sections whose first line matches a regex. Without a selector it returns the outline "
            "(all top-level headers). Use it instead of get_config_backup when the user wants a "
            "section, not the whole file, especially for a large config.",
            GetConfigSectionInput,
            _get_config_section,
        ),
        Tool(
            "offer_config_download",
            "Show the user a download button for a backed-up configuration that "
            "get_config_backup already fetched (pass its handle). Use it when the user asks to "
            "download or save a config, or agrees after a large config was offered. It sends "
            "nothing to you and runs nothing.",
            OfferConfigDownloadInput,
            _offer_config_download,
        ),
        Tool(
            "search_config_backups",
            "Find which devices have a text or regular expression in their backed-up running or "
            "startup configuration (git backup, no SSH). Use it for 'which devices have X "
            "configured'; never loop get_config_backup over devices. Returns device names with "
            "the first matching lines; says when the result is partial.",
            SearchConfigBackupsInput,
            _search_config_backups,
        ),
    ]
