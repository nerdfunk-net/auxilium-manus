"""Playbook files: parsing, validation and the built-in/local merge (doc/AI_TOOL_CHAIN.md §21, §25).

A playbook is a short markdown recipe the model fetches with ``get_playbook`` and follows. It is
text only: it names tools, contains no code and grants no rights (every tool still checks the
user's rights and opt-ins).

Two layers, merged on every call (reads are cached by mtime, ``knowledge_loader``):

* built-in: ``knowledge/playbooks/<name>.md`` in the image, reviewed in git;
* local: ``${DATA_DIRECTORY}/ai/playbooks/<name>.md``, written by the operator. A local file with
  the same name overrides the built-in one; ``disabled: true`` hides it. An invalid local file is
  reported (``PlaybookSet.invalid``, the log, ``scripts/check_playbooks.py``) and ignored, so it
  never replaces a working built-in playbook.

The model never supplies a path: ``get_playbook`` looks a name up in the merged set.
"""

from __future__ import annotations

import logging
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from services.ai_assistant import knowledge_loader

logger = logging.getLogger(__name__)

BUILTIN_PLAYBOOK_DIR = knowledge_loader.KNOWLEDGE_DIR / "playbooks"
MAX_PLAYBOOK_CHARS = 16_000
MAX_FRONT_MATTER_CHARS = 4_000
MAX_FILES_PER_DIR = 100
MAX_TOOLS = 20
MAX_TITLE_CHARS = 120
MAX_WHEN_CHARS = 400

Source = Literal["builtin", "local"]
DataClassLetter = Literal["A", "B"]

_ALLOWED_KEYS = frozenset({"name", "title", "when", "tools", "scope", "data_class", "disabled"})
_NAME = re.compile(r"[a-z][a-z0-9-]{0,63}")
_TOOL_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
_STEPS_HEADING = re.compile(r"^##[ \t]+Steps[ \t]*$", re.MULTILINE)
# A snake_case word whose first word is a verb is read as a tool name, in backticks or not, with or
# without call syntax. Parameter names ("only_problems") do not start with a verb, and a word
# followed by "=" is a parameter assignment; both are left alone. This is an author lint, not what
# keeps a playbook on its tools: the session only has the tools it was given.
_TOOL_TOKEN = re.compile(r"(?<![\w-])([a-z][a-z0-9]*(?:_[a-z0-9]+)+)(?![\w=-])")
_TOOL_VERBS = frozenset(
    {
        "get", "list", "query", "fetch", "analyze", "check", "diff", "compare", "differential",
        "propose", "run", "trigger", "execute", "start", "delete", "send", "apply", "update",
        "create", "set", "add", "remove", "write",
    }
)  # fmt: skip
# Device change commands a read-only playbook must never tell anyone to send. A command is
# recognised where it would be typed: inside backticks, or at the start of a line (after a list
# marker). Prose that merely mentions a word ("the device was reloaded", "commit to one cause") is
# not a command, so each pattern needs the command's own shape.
_LIST_MARKER = re.compile(r"^\s*(?:[-*+>]|\d+[.)])?\s*")
_CODE_SPAN = re.compile(r"`([^`\n]+)`")
_COMMAND = re.compile(
    r"conf(?:ig(?:ure)?)?\s+t(?:erm(?:inal)?)?\b"
    r"|reload(?:\s+(?:in|at|cancel)\b.*)?[\s.;,]*$"
    r"|wr(?:ite)?\s+(?:mem(?:ory)?|erase)\b"
    r"|wr[\s.;,]*$"
    r"|copy\s+(?:\S+\s+)?(?:running|startup)-config\b"
    r"|copy\s+run(?:ning)?\s+start(?:up)?\b"
    r"|erase\s+(?:startup-config|flash|nvram)\b"
    r"|commit(?:\s+(?:confirmed|replace|check)\b.*)?[\s.;,]*$"
    r"|request\s+system\s+(?:reboot|halt|power-off)\b"
    r"|clear\s+(?:ip\s+)?(?:bgp|ospf|route|arp)\b"
    r"|(?:no\s+)?shutdown[\s.;,]*$",
    re.IGNORECASE,
)


def _find_config_command(text: str) -> str | None:
    candidates = [m.group(1).strip() for m in _CODE_SPAN.finditer(text)]
    candidates.extend(_LIST_MARKER.sub("", line, count=1) for line in text.splitlines())
    for candidate in candidates:
        match = _COMMAND.match(candidate)
        if match is not None:
            return candidate[:60]
    return None


class PlaybookError(ValueError):
    """A playbook file breaks the format; the message is safe to show to the operator."""


@dataclass(frozen=True)
class Playbook:
    name: str
    title: str
    when: str
    tools: tuple[str, ...]
    data_class: DataClassLetter
    source: Source
    body: str
    overrides_builtin: bool = False


def shared_with_everyone(playbook: Playbook) -> bool:
    """A local playbook that opted out of the inventory gate: every user gets its text."""
    return playbook.source == "local" and playbook.data_class == "A"


@dataclass(frozen=True)
class Disabled:
    """A local file whose only job is to hide the built-in playbook of this name."""

    name: str


@dataclass(frozen=True)
class InvalidPlaybook:
    source: Source
    file: str
    reason: str


@dataclass(frozen=True)
class PlaybookSet:
    playbooks: tuple[Playbook, ...]
    invalid: tuple[InvalidPlaybook, ...]

    def get(self, name: str) -> Playbook | None:
        return next((p for p in self.playbooks if p.name == name), None)


def _split_front_matter(text: str) -> tuple[str, str]:
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        raise PlaybookError("the file must start with a front matter block (--- ... ---)")
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1 :]).strip()
    raise PlaybookError("the front matter block is not closed with ---")


def _load_front_matter(raw: str) -> dict[str, Any]:
    if len(raw) > MAX_FRONT_MATTER_CHARS:
        raise PlaybookError(f"the front matter is longer than {MAX_FRONT_MATTER_CHARS} characters")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise PlaybookError("the front matter is not valid YAML") from exc
    if not isinstance(data, dict):
        raise PlaybookError("the front matter must be a mapping of fields")
    return data


def _text_field(front: dict[str, Any], key: str, limit: int) -> str:
    value = front.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PlaybookError(f"front matter field '{key}' is required and must be text")
    if len(value) > limit:
        raise PlaybookError(f"front matter field '{key}' is longer than {limit} characters")
    return value.strip()


def _tool_list(front: dict[str, Any], known_tools: frozenset[str]) -> tuple[str, ...]:
    value = front.get("tools")
    if not isinstance(value, list) or not all(isinstance(t, str) for t in value):
        raise PlaybookError("front matter field 'tools' must be a list of tool names")
    if len(value) > MAX_TOOLS:
        raise PlaybookError(f"front matter field 'tools' names more than {MAX_TOOLS} tools")
    for tool in value:
        if not _TOOL_NAME.fullmatch(tool) or tool not in known_tools:
            raise PlaybookError(f"unknown tool '{tool[:64]}' in front matter field 'tools'")
    return tuple(dict.fromkeys(value))


def _check_name(front: dict[str, Any], file_stem: str) -> str:
    name = front.get("name")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise PlaybookError(
            "front matter field 'name' is required: lowercase letters, digits and '-', "
            "starting with a letter, up to 64 characters"
        )
    if name != file_stem:
        raise PlaybookError("name must equal the file name (without .md)")
    return name


def _refuse_config_command(text: str, where: str) -> None:
    command = _find_config_command(text)
    if command is not None:
        raise PlaybookError(
            f"{where} contains a configuration command ('{command}'); playbooks are read-only"
        )


def _check_body(body: str, tools: tuple[str, ...], known_tools: frozenset[str]) -> None:
    if not _STEPS_HEADING.search(body):
        raise PlaybookError("the text needs a '## Steps' section")
    _refuse_config_command(body, "the text")
    for token in dict.fromkeys(_TOOL_TOKEN.findall(body)):
        if token.split("_", 1)[0] not in _TOOL_VERBS:
            continue
        if token not in known_tools:
            raise PlaybookError(f"the text names the tool '{token}', which does not exist")
        if token not in tools:
            raise PlaybookError(f"the text names the tool '{token}', which 'tools' does not list")


def parse_playbook(
    text: str, *, file_stem: str, source: Source, known_tools: frozenset[str]
) -> Playbook | Disabled:
    """Validate one file. Raises ``PlaybookError`` with an operator-readable reason."""
    if len(text) > MAX_PLAYBOOK_CHARS:
        raise PlaybookError(f"the file is too large (limit {MAX_PLAYBOOK_CHARS} characters)")
    raw_front, body = _split_front_matter(text)
    front = _load_front_matter(raw_front)
    unknown = sorted(str(k) for k in front if k not in _ALLOWED_KEYS)
    if unknown:
        raise PlaybookError(f"unknown front matter field '{unknown[0][:64]}'")
    name = _check_name(front, file_stem)
    disabled = front.get("disabled", False)
    if not isinstance(disabled, bool):
        raise PlaybookError("front matter field 'disabled' must be true or false")
    if disabled:
        if source != "local":
            raise PlaybookError("'disabled' is only allowed in a local file")
        return Disabled(name=name)
    title = _text_field(front, "title", MAX_TITLE_CHARS)
    when = _text_field(front, "when", MAX_WHEN_CHARS)
    _refuse_config_command(title, "the title")
    _refuse_config_command(when, "the 'when' field")
    if front.get("scope") != "read-only":
        raise PlaybookError("front matter field 'scope' must be 'read-only'")
    tools = _tool_list(front, known_tools)
    data_class = front.get("data_class", "A" if source == "builtin" else "B")
    if data_class not in ("A", "B"):
        raise PlaybookError("front matter field 'data_class' must be 'A' or 'B'")
    _check_body(body, tools, known_tools)
    return Playbook(
        name=name,
        title=title,
        when=when,
        tools=tools,
        data_class=data_class,
        source=source,
        body=body,
    )


def _read_directory(
    directory: Path, source: Source, known_tools: frozenset[str]
) -> tuple[list[Playbook | Disabled], list[InvalidPlaybook]]:
    found: list[Playbook | Disabled] = []
    invalid: list[InvalidPlaybook] = []
    try:
        files = sorted(p for p in directory.glob("*.md") if not p.name.startswith("_"))
    except OSError:
        logger.warning("AI playbook directory (%s) could not be listed", source)
        return found, invalid
    if len(files) > MAX_FILES_PER_DIR:
        invalid.append(
            InvalidPlaybook(
                source, "*", f"more than {MAX_FILES_PER_DIR} files: the limit was reached"
            )
        )
        files = files[:MAX_FILES_PER_DIR]
    for path in files:
        try:
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode):
                invalid.append(
                    InvalidPlaybook(source, path.name, "must be a regular file (no symlinks)")
                )
                continue
            # A longer file comes back cut with a marker, so parse_playbook sees it as too large.
            text = knowledge_loader.read_cached(path, MAX_PLAYBOOK_CHARS)
            found.append(
                parse_playbook(text, file_stem=path.stem, source=source, known_tools=known_tools)
            )
        except PlaybookError as exc:
            invalid.append(InvalidPlaybook(source, path.name, str(exc)))
        except UnicodeDecodeError:
            invalid.append(InvalidPlaybook(source, path.name, "the file is not valid UTF-8 text"))
        except OSError:
            invalid.append(InvalidPlaybook(source, path.name, "the file could not be read"))
    return found, invalid


def load_playbooks(
    *,
    known_tools: frozenset[str],
    builtin_dir: Path | None = None,
    local_dir: Path | None = None,
) -> PlaybookSet:
    """The merged, validated set. Local overrides built-in; local ``disabled`` hides a name."""
    builtin_found, builtin_invalid = _read_directory(
        BUILTIN_PLAYBOOK_DIR if builtin_dir is None else builtin_dir, "builtin", known_tools
    )
    local_found, local_invalid = _read_directory(
        knowledge_loader.local_playbook_dir() if local_dir is None else local_dir,
        "local",
        known_tools,
    )
    merged = {p.name: p for p in builtin_found if isinstance(p, Playbook)}
    for item in local_found:
        if isinstance(item, Disabled):
            merged.pop(item.name, None)
            continue
        replaced = item.name in merged
        merged[item.name] = Playbook(
            name=item.name,
            title=item.title,
            when=item.when,
            tools=item.tools,
            data_class=item.data_class,
            source=item.source,
            body=item.body,
            overrides_builtin=replaced,
        )
    invalid = (*builtin_invalid, *local_invalid)
    for entry in invalid:
        log = logger.error if entry.source == "builtin" else logger.warning
        log("AI playbook %s (%s) is invalid: %s", entry.file, entry.source, entry.reason)
    return PlaybookSet(
        playbooks=tuple(sorted(merged.values(), key=lambda p: p.name)), invalid=invalid
    )
