"""The in-memory index: device name -> its interfaces, built once at startup.

Lines with the same device name are merged (the app's "multiple lines per device" layout, which
this agent needs by definition). Names are compared exactly, as the app and Nautobot do; a lookup
that differs only in case still finds a device when that is unambiguous. Immutable after
``build_index``; the handler only reads it.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from manus_agent.csv_reader import read_csv_rows
from manus_agent.device_mapping import (
    DeviceProblem,
    MappingRule,
    device_name,
    flag_problem,
    map_interface,
    read_primary_flag,
    resolve_primary_ip,
)

logger = logging.getLogger("manus_agent.ip_index")

# Everything is held in memory for the life of the process: bound what startup will read.
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_TOTAL_ROWS = 1_000_000


class IndexLimitError(ValueError):
    """The files are larger than the agent is willing to hold (the text names no content)."""


@dataclass(frozen=True)
class DeviceEntry:
    name: str
    interfaces: tuple[dict[str, Any], ...]
    primary_ip4: dict[str, Any] | None
    problems: tuple[DeviceProblem, ...]


@dataclass(frozen=True)
class IpIndex:
    devices: Mapping[str, DeviceEntry]
    files_read: int
    rows: int
    warnings: tuple[str, ...]
    # casefolded name -> the exact names that fold to it
    folded: Mapping[str, tuple[str, ...]]

    def lookup(self, name: str) -> DeviceEntry | None:
        wanted = name.strip()
        exact = self.devices.get(wanted)
        if exact is not None:
            return exact
        candidates = self.folded.get(wanted.casefold(), ())
        return self.devices[candidates[0]] if len(candidates) == 1 else None


def _check_total_size(files: Sequence[Path]) -> None:
    total = sum(path.stat().st_size for path in files)
    if total > MAX_TOTAL_BYTES:
        raise IndexLimitError(
            f"the files add up to {total // (1024 * 1024)} MiB, above the limit of "
            f"{MAX_TOTAL_BYTES // (1024 * 1024)} MiB"
        )


def build_index(files: Sequence[Path], delimiter: str, rules: Sequence[MappingRule]) -> IpIndex:
    _check_total_size(files)
    interfaces: dict[str, list[dict[str, Any]]] = {}
    flagged: dict[str, list[dict[str, Any]]] = {}
    problems: dict[str, list[DeviceProblem]] = {}
    warnings: list[str] = []
    rows = 0
    nameless = 0

    for path in files:
        entries, file_problems = read_csv_rows(path, delimiter)
        warnings.extend(file_problems)
        rows += len(entries)
        if rows > MAX_TOTAL_ROWS:
            raise IndexLimitError(f"the files have more than {MAX_TOTAL_ROWS} lines")
        for entry in entries:
            name = device_name(entry, rules)
            if name is None:
                nameless += 1
                continue
            if name not in interfaces:
                interfaces[name] = []
                flagged[name] = []
                problems[name] = []
            interface = map_interface(entry, rules)
            if interface:
                interfaces[name].append(interface)
            flag = read_primary_flag(entry, rules)
            if flag is None:
                problems[name].append(flag_problem(rules))
            elif flag:
                flagged[name].append(interface or {})
    if nameless:
        warnings.append(f"{nameless} line(s) skipped: no value in the column mapped to 'name'")

    devices: dict[str, DeviceEntry] = {}
    folded: dict[str, list[str]] = {}
    for name in interfaces:
        resolution = resolve_primary_ip(flagged[name])
        # A device with any problem gets no primary IP: it would be a guess.
        primary = None if problems[name] else resolution.primary_ip4
        devices[name] = DeviceEntry(
            name=name,
            interfaces=tuple(interfaces[name]),
            primary_ip4=primary,
            problems=(*problems[name], *resolution.problems),
        )
        folded.setdefault(name.casefold(), []).append(name)
    # Only the device name and the problem code: the details (addresses, interface names) are
    # file content and go to the caller in the handler's ``problems``, not into the log.
    for entry in devices.values():
        warnings.extend(f"{entry.name}: {problem.code}" for problem in entry.problems)
    for names in folded.values():
        if len(names) > 1:
            warnings.append(
                f"{len(names)} device names differ only in case ({', '.join(names[:3])}); "
                "a lookup must match one of them exactly"
            )
    return IpIndex(
        devices, len(files), rows, tuple(warnings), {k: tuple(v) for k, v in folded.items()}
    )


# The handler is a plain function, so the index reaches it through this holder (set once at start).
_current: IpIndex | None = None


def set_index(index: IpIndex | None) -> None:
    global _current
    _current = index


def get_index() -> IpIndex:
    if _current is None:
        raise RuntimeError("the IP index is not loaded")
    return _current


def entry_to_answer(entry: DeviceEntry) -> dict[str, Any]:
    """A JSON-ready copy of a device entry (the cache itself is never handed out)."""
    answer: dict[str, Any] = {
        "found": True,
        "device": entry.name,
        "interfaces": copy.deepcopy(list(entry.interfaces)),
        "problems": [problem.message for problem in entry.problems],
    }
    if entry.primary_ip4 is not None:
        answer["primary_ip4"] = copy.deepcopy(entry.primary_ip4)
    return answer
