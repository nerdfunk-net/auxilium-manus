"""Run ``fping`` for a list of IPv4 addresses and parse what it reports.

The hosts go to fping's standard input (``-f -``): no shell, nothing from the request in the
argument list, no argument-length limit. With ``-q -c N`` fping prints one summary line per host
on standard error, reachable or not::

    10.0.0.1 : xmt/rcv/%loss = 3/3/0%, min/avg/max = 0.40/0.50/0.61
    10.0.0.3 : xmt/rcv/%loss = 3/0/100%
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

FPING = "fping"
# Milliseconds between packets to different hosts; fping's own default, spelled out so the
# runtime estimate in the README (hosts x 10 ms) stays true.
INTERVAL_MS = 10
# fping refuses a shorter period.
MIN_PERIOD_MS = 10
# Exit 0: all hosts answered. 1: some did not (normal for a scan). 2+: fping itself failed.
_OK_EXIT_CODES = (0, 1)

_LINE = re.compile(
    r"^(?P<ip>\d{1,3}(?:\.\d{1,3}){3})\s*: xmt/rcv/%loss = (?P<xmt>\d+)/(?P<rcv>\d+)/"
    r"(?P<loss>\d+(?:\.\d+)?)%(?:, min/avg/max = (?P<min>[\d.]+)/(?P<avg>[\d.]+)/(?P<max>[\d.]+))?"
)


class FpingError(RuntimeError):
    """fping could not run or failed; the message is fixed text (never fping's own output)."""


@dataclass(frozen=True)
class HostResult:
    ip: str
    reachable: bool
    rtt_ms: float | None
    loss_percent: int


def parse_summary(text: str) -> list[HostResult]:
    results: list[HostResult] = []
    for line in text.splitlines():
        match = _LINE.match(line.strip())
        if match is None:
            continue
        received = int(match["rcv"]) > 0
        average = match["avg"]
        results.append(
            HostResult(
                ip=match["ip"],
                reachable=received,
                rtt_ms=round(float(average), 3) if received and average else None,
                loss_percent=int(float(match["loss"])),
            )
        )
    return results


async def run_fping(
    hosts: list[str], *, count: int, timeout_ms: int, binary: str = FPING
) -> list[HostResult]:
    """Ping *hosts* and return one result per host fping reported, in its order."""
    try:
        process = await asyncio.create_subprocess_exec(
            binary,
            "-4",
            "-q",
            "-c",
            str(count),
            "-t",
            str(timeout_ms),
            "-i",
            str(INTERVAL_MS),
            # Period between probes of one host. fping's default (1000 ms) would stretch a short
            # list with count > 1 to count seconds; waiting the packet timeout is enough.
            "-p",
            str(max(timeout_ms, MIN_PERIOD_MS)),
            "-f",
            "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise FpingError("fping cannot be started (is it installed in this image?)") from exc

    try:
        _, stderr = await process.communicate("\n".join(hosts).encode("ascii") + b"\n")
    finally:
        # Reached on cancellation (the core's timeout) as well: never leave a scan running.
        if process.returncode is None:
            process.kill()
            await process.wait()

    if process.returncode not in _OK_EXIT_CODES:
        detail = stderr.decode("utf-8", errors="replace")[:300]
        logger.warning("fping exit %s: %s", process.returncode, detail)
        raise FpingError(f"fping failed (exit code {process.returncode}); check the agent log")
    return parse_summary(stderr.decode("utf-8", errors="replace"))
