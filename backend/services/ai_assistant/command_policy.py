"""Which device commands the assistant may propose (doc/AI_TOOL_CHAIN.md §13.2, layer 2).

Read-only only, by construction rather than by a list of bad words: a command is accepted when it
is the full word ``show`` plus arguments from a short whitelist of characters, optionally followed
by exactly one output filter (``| include X``, ``| count``, ...). Everything else is refused: other
verbs and abbreviations (``sh run``, ``conf t``, ``reload``, ``ping``), command chaining,
redirection, a second pipe, a pipe that writes (``redirect``, ``tee``, ``append``, ``save``),
control characters and any non-ASCII text (homoglyphs, zero-width characters).

The same function runs when the model proposes a command and again when the user confirms it, so
the execution endpoint never trusts what the proposal said. A reason never echoes the command.
"""

from __future__ import annotations

import re

MAX_COMMAND_CHARS = 200
MAX_COMMANDS = 5
MAX_FILTER_PATTERN_CHARS = 80

# Characters of a show command's arguments: names, addresses, interface ids, VRFs.
_ARGUMENT = re.compile(r"[A-Za-z0-9_./:*,@%+=()\[\]-]+")
# A filter pattern may also hold spaces and ``^``; never ``$``, quotes, backslashes or ``;``.
_PATTERN = re.compile(r"[A-Za-z0-9_ ./:^*+,()\[\]-]+")
_PATTERN_FILTERS = frozenset({"include", "exclude", "begin", "section", "match", "except", "find"})
_DISPLAY_KINDS = frozenset({"set", "json", "xml"})


class CommandNotAllowedError(ValueError):
    """The command is not an allowed read-only command; the message is safe to show."""


def _refuse(reason: str) -> CommandNotAllowedError:
    return CommandNotAllowedError(reason)


def _check_filter(segment: str) -> str:
    words = segment.split()
    if not words:
        raise _refuse("an output filter after '|' is missing")
    name = words[0].lower()
    rest = " ".join(words[1:])
    if name in _PATTERN_FILTERS:
        if not rest or len(rest) > MAX_FILTER_PATTERN_CHARS or not _PATTERN.fullmatch(rest):
            raise _refuse("the output filter pattern is missing or contains unsafe characters")
        return f"{name} {rest}"
    if name == "count" and not rest:
        return "count"
    if name == "no-more" and not rest:
        return "no-more"
    if name == "display" and rest.lower() in _DISPLAY_KINDS:
        return f"display {rest.lower()}"
    raise _refuse("only the output filters include, exclude, begin, section and count are allowed")


def check_command(raw: str) -> str:
    """The normalised command, or ``CommandNotAllowedError``."""
    if not isinstance(raw, str) or not raw.isascii():
        raise _refuse("commands must be plain ASCII text")
    # str.split() treats a newline as a space, so "show version\nreload" would otherwise look like
    # one command with an argument.
    if not all(ch.isprintable() or ch == "\t" for ch in raw):
        raise _refuse("commands must be a single line without control characters")
    segments = raw.split("|")
    if len(segments) > 2:
        raise _refuse("only one output filter is allowed")
    head = segments[0].split()
    if not head or head[0].lower() != "show":
        raise _refuse("only full 'show' commands are allowed")
    arguments = head[1:]
    if not arguments or not all(_ARGUMENT.fullmatch(a) for a in arguments):
        raise _refuse("the show command needs arguments made of plain names and addresses")
    parts = ["show", *arguments]
    command = " ".join(parts)
    if len(segments) == 2:
        command = f"{command} | {_check_filter(segments[1])}"
    if len(command) > MAX_COMMAND_CHARS:
        raise _refuse(f"a command may be at most {MAX_COMMAND_CHARS} characters")
    return command


def check_commands(raw_commands: list[str]) -> list[str]:
    """All commands normalised, repeated ones once; one bad command refuses the whole list."""
    if not raw_commands:
        raise _refuse("at least one command is required")
    if len(raw_commands) > MAX_COMMANDS:
        raise _refuse(f"at most {MAX_COMMANDS} commands per request")
    return list(dict.fromkeys(check_command(c) for c in raw_commands))
