"""An endpoint (IP or MAC address) located in the ACI fabric (``fvCEp``), frozen and whitelisted."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Endpoint(BaseModel):
    model_config = ConfigDict(frozen=True)


class AciEndpointAttachment(_Endpoint):
    """Where the endpoint is plugged in: a port of one switch, or a vPC across two."""

    pod_id: int
    node_ids: tuple[int, ...]
    interface: str


class AciEndpoint(_Endpoint):
    mac: str
    ips: tuple[str, ...] = ()
    tenant: str | None = None
    app_profile: str | None = None
    epg: str | None = None
    # ``<l3out>/<external epg>`` for an endpoint behind an L3Out.
    external_epg: str | None = None
    encap: str | None = None
    # ``tenant/vrf`` and ``tenant/bridge_domain`` from the endpoint's own ``vrfDn`` / ``bdDn``.
    vrf: str | None = None
    bridge_domain: str | None = None
    # ``tenant/application_profile/esg`` when the endpoint is classified into an endpoint security
    # group (``esgUsegDn``); the policy then is the ESG's, which the flow check does not evaluate.
    esg: str | None = None
    attachments: tuple[AciEndpointAttachment, ...] = ()


class AciEndpointIpRecord(_Endpoint):
    """One address of an endpoint and when the APIC learned and last changed it."""

    address: str
    learned_at: str | None = None
    last_changed: str | None = None


class AciLeafEndpointRecord(_Endpoint):
    """The endpoint's own record on one leaf (``epmMacEp``): when that leaf learned it."""

    pod_id: int
    node_id: int
    interface: str | None = None
    first_seen: str | None = None
    last_changed: str | None = None
    flags: str | None = None


class AciEndpointEvent(_Endpoint):
    """An APIC event or fault record that names the endpoint's MAC or one of its addresses."""

    kind: Literal["event", "fault"]
    time: str | None = None
    code: str | None = None
    severity: str | None = None
    description: str | None = None


class AciEndpointHistory(_Endpoint):
    """What the APIC itself knows about when an endpoint appeared and changed.

    The APIC keeps no move history: there are the timestamps of the current records and whatever
    the event and fault logs mention. ``events_unavailable`` / ``leaf_records_failed`` say a part
    could not be read (never an empty-looking answer).
    """

    mac: str
    tenant: str | None = None
    app_profile: str | None = None
    epg: str | None = None
    external_epg: str | None = None
    last_changed: str | None = None
    ips: tuple[AciEndpointIpRecord, ...] = ()
    leaf_records: tuple[AciLeafEndpointRecord, ...] = ()
    events: tuple[AciEndpointEvent, ...] = ()
    leaf_records_failed: int = 0
    events_unavailable: bool = False
