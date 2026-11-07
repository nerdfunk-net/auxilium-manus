"""A gateway subnet of a bridge domain or EPG read from the APIC (frozen, whitelisted)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class AciSubnet(BaseModel):
    model_config = ConfigDict(frozen=True)

    prefix: str  # the network, for example 10.1.1.0/24
    gateway: str  # the address the APIC holds, for example 10.1.1.1
    tenant: str
    bridge_domain: str | None = None
    vrf: str | None = None
    owner: Literal["bd", "epg"] = "bd"
    epg: str | None = None
    scope: tuple[str, ...] = ()
