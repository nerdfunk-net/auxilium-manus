"""Batfish coordinator connection settings. No credential -- the OSS coordinator has no auth."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BatfishConnection:
    host: str
    port: int = 9996
