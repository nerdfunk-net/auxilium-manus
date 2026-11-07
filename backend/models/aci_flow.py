"""Result of a "can A reach B on this port" assessment from the fabric's contract policy.

This is a reading of the policy (intent), not a packet trace: ``verdict`` is ``permitted``,
``not_permitted`` or ``unknown`` (the APIC data does not decide it, ``reason`` says why).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Flow(BaseModel):
    model_config = ConfigDict(frozen=True)


class AciFlowParty(_Flow):
    """One side of the flow, as the fabric sees it."""

    address: str
    # ``endpoint`` (learned host), ``external_subnet`` (matched an L3Out external EPG subnet) or
    # ``unknown`` (neither: the fabric has not learned it and no external subnet covers it).
    how: Literal["endpoint", "external_subnet", "unknown"] = "unknown"
    epg_dn: str | None = None
    epg_path: str | None = None
    vrf: str | None = None
    esg: str | None = None


class AciFlowContract(_Flow):
    tenant: str
    name: str
    scope: str | None = None
    # Filter entries that cover the asked protocol and port (empty when none does).
    matching_entries: tuple[str, ...] = ()
    # Every protocol / port the contract has, so a wrong-port answer shows what is allowed.
    entries: tuple[str, ...] = ()


class AciFlowVerdict(_Flow):
    source: AciFlowParty
    destination: AciFlowParty
    protocol: str
    port: int | None = None
    verdict: Literal["permitted", "not_permitted", "unknown"]
    reason: str
    explanation: str
    contracts: tuple[AciFlowContract, ...] = ()
    notes: tuple[str, ...] = ()
