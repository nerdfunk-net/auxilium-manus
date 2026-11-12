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

import ipaddress
import re

MAX_COMMAND_CHARS = 200
MAX_COMMANDS = 5
# A reviewed catalogue plan (feature learn, doc/AI_TOOL_CHAIN.md §49) may carry more commands than a
# free-form proposal. The proposal tool and the confirm step both pass this limit for a signed
# token; every command still passes ``check_command`` on its own.
MAX_SIGNED_COMMANDS = 16
MAX_FILTER_PATTERN_CHARS = 80

# Characters of a show command's arguments: names, addresses, interface ids, VRFs.
_ARGUMENT = re.compile(r"[A-Za-z0-9_./:*,@%+=()\[\]-]+")
# A filter pattern may also hold spaces and ``^``; never ``$``, quotes, backslashes or ``;``.
_PATTERN = re.compile(r"[A-Za-z0-9_ ./:^*+,()\[\]-]+")
_PATTERN_FILTERS = frozenset({"include", "exclude", "begin", "section", "match", "except", "find"})
_DISPLAY_KINDS = frozenset({"set", "json", "xml"})


# Ping and traceroute (doc/AI_TOOL_CHAIN.md §51). Never free text from the model: only a probe that
# ``probes.plan_probes`` built is signed, and ``check_probe_command`` accepts no more than the
# builder can write (one target, each setting at most once, bounded numbers), so the confirm step
# is a real backstop and not a wider door.
_PROBE_VERBS = frozenset({"ping", "traceroute"})
_PROBE_NAME = re.compile(r"[A-Za-z0-9_.-]{1,32}")
_PROBE_FLAGS = frozenset({"numeric", "no-resolve"})
# keyword -> (smallest, largest) value: every probe is bounded in packets and in time.
_PROBE_NUMBERS: dict[str, tuple[int, int]] = {
    "count": (1, 10),
    "repeat": (1, 10),
    "timeout": (1, 5),
    "wait": (1, 5),
    "probe": (1, 3),
    "maxttl": (1, 30),
}
_PROBE_TTL = (1, 30)
# Keywords that set the same thing share a group; a probe has at most one of each group.
_PROBE_GROUP = {
    "count": "packets",
    "repeat": "packets",
    "vrf": "vrf",
    "routing-instance": "vrf",
    "timeout": "timeout",
    "wait": "timeout",
    "ttl": "ttl",
    "maxttl": "ttl",
    "probe": "probe",
    "source": "source",
    "numeric": "numeric",
    "no-resolve": "numeric",
}
_PROBE_KEYWORDS = frozenset(_PROBE_GROUP)
# 0.0.0.0/8 ("this network") and the Alibaba Cloud metadata address, which is not link-local.
_THIS_NETWORK = ipaddress.IPv4Network("0.0.0.0/8")
_BLOCKED_PROBE_TARGETS = frozenset({ipaddress.IPv4Address("100.100.100.200")})


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


def check_probe_target(raw: str) -> str:
    """An IPv4 literal a probe may aim at, or ``CommandNotAllowedError``.

    A literal only: a name would be resolved by the device or leave in a DNS query. Loopback,
    multicast, ``0.0.0.0/8``, link-local (the usual cloud metadata address, 169.254.169.254),
    reserved addresses (which include the limited broadcast) and ``100.100.100.200`` (Alibaba Cloud
    metadata, not link-local) are refused; private ranges are allowed. A directed broadcast
    cannot be seen without the subnet and is not refused.
    """
    try:
        address = ipaddress.IPv4Address(raw)
    except ValueError:
        raise _refuse("the target must be an IPv4 address (no names, no IPv6)") from None
    if (
        address.is_loopback
        or address.is_multicast
        or address.is_unspecified
        or address.is_link_local
        or address.is_reserved
        or address in _THIS_NETWORK
        or address in _BLOCKED_PROBE_TARGETS
    ):
        raise _refuse("that target address is not allowed")
    return str(address)


def _int_in(raw: str, low: int, high: int) -> int:
    if not raw.isdecimal() or not low <= int(raw) <= high:
        raise _refuse(f"a probe number must be between {low} and {high}")
    return int(raw)


def _read_probe_keyword(word: str, words: list[str], i: int, out: list[str]) -> int:
    """Append the keyword and its value to ``out``; the index of the next word."""
    if word in _PROBE_FLAGS:
        out.append(word)
        return i + 1
    if word == "ttl":
        values = words[i + 1 : i + 3]
        if len(values) != 2:
            raise _refuse("'ttl' needs a first and a last number")
        low, high = (_int_in(v, *_PROBE_TTL) for v in values)
        if low > high:
            raise _refuse("'ttl' needs the smaller number first")
        out += [word, str(low), str(high)]
        return i + 3
    values = words[i + 1 : i + 2]
    if not values:
        raise _refuse(f"'{word}' needs a value")
    value = values[0]
    if word == "vrf" or word == "routing-instance":
        if not _PROBE_NAME.fullmatch(value) or value.lower() in _PROBE_KEYWORDS | _PROBE_VERBS:
            raise _refuse("the VRF name contains unsafe characters or is a probe keyword")
        out += [word, value]
    elif word == "source":
        out += [word, check_probe_target(value)]
    else:
        out += [word, str(_int_in(value, *_PROBE_NUMBERS[word]))]
    return i + 2


def check_probe_command(raw: str) -> str:
    """The normalised ``ping`` / ``traceroute`` command, or ``CommandNotAllowedError``.

    Grammar: the verb, then keywords with typed values (``vrf`` / ``routing-instance`` NAME,
    ``count`` / ``repeat`` / ``timeout`` / ``wait`` / ``probe`` / ``maxttl`` N within a small cap,
    ``ttl`` two ascending numbers, ``source`` IPv4), the flags ``numeric`` and ``no-resolve``, and
    exactly one bare token: the target. Each setting at most once (``count`` and ``repeat`` are one
    setting, so are ``vrf`` and ``routing-instance``). No pipe, no second command, no name.
    """
    if not isinstance(raw, str) or not raw.isascii():
        raise _refuse("commands must be plain ASCII text")
    if not all(ch.isprintable() or ch == "\t" for ch in raw):
        raise _refuse("commands must be a single line without control characters")
    words = raw.split()
    if not words or words[0].lower() not in _PROBE_VERBS:
        raise _refuse("only ping and traceroute probes are allowed here")
    out = [words[0].lower()]
    target: str | None = None
    seen: set[str] = set()
    i = 1
    while i < len(words):
        word = words[i].lower()
        if word in _PROBE_KEYWORDS:
            group = _PROBE_GROUP[word]
            if group in seen:
                raise _refuse(f"'{word}' may be given once, and not together with its alternative")
            seen.add(group)
            i = _read_probe_keyword(word, words, i, out)
        else:
            if target is not None:
                raise _refuse("a probe has exactly one target")
            target = check_probe_target(words[i])
            out.append(target)
            i += 1
    if target is None:
        raise _refuse("the probe needs a target address")
    command = " ".join(out)
    if len(command) > MAX_COMMAND_CHARS:
        raise _refuse(f"a command may be at most {MAX_COMMAND_CHARS} characters")
    return command


def is_probe_run(commands: list[str]) -> bool:
    """True when every command is a ping or traceroute (already checked)."""
    return bool(commands) and all(c.split(None, 1)[0].lower() in _PROBE_VERBS for c in commands)


def check_commands(
    raw_commands: list[str], *, limit: int = MAX_COMMANDS, allow_probes: bool = False
) -> list[str]:
    """All commands normalised, repeated ones once; one bad command refuses the whole list.

    ``allow_probes`` is for a signed token only (the confirm step): the model's own free-form
    proposal never passes it, so ``ping`` and ``traceroute`` stay refused there.
    """
    if not raw_commands:
        raise _refuse("at least one command is required")
    if len(raw_commands) > limit:
        raise _refuse(f"at most {limit} commands per request")

    def one(command: str) -> str:
        first = command.split(None, 1)[0].lower() if command.split() else ""
        if allow_probes and first in _PROBE_VERBS:
            return check_probe_command(command)
        return check_command(command)

    return list(dict.fromkeys(one(c) for c in raw_commands))
