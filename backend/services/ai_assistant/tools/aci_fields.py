"""What each field of the ACI models needs before Ask the Net may send it.

One table for every ACI model, by field name (the fields are named consistently). A field that
no rule names is never sent (fail closed), and the raw distinguished names in ``EXCLUDED`` never
are. ``tests/unit/test_ai_aci_device_tools.py`` pins every model field to a rule or to the
exclusions. ``project`` keeps what the user's data switches allow and records, in ``withheld``,
what a switch would release.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from models.aci_facts import AciEpg
from services.aci.policy_search import readable_epg
from services.ai_assistant.data_sharing import DataClass, SharingPolicy, not_shared_marker

Rule = DataClass
_INV, _ADDR, _CONTENT = DataClass.INVENTORY, DataClass.ADDRESSES, DataClass.CONTENT

# One table for every fact model, by field name (the fields are named consistently). A field that
# is not listed is never sent; ``test_ai_aci_tools`` pins every model field to a rule or to the
# deliberate exclusions below.
RULES: Mapping[str, Rule] = {
    **dict.fromkeys(
        (
            "node_id",
            "pod_id",
            "name",
            "role",
            "model",
            "vendor",
            "fabric_state",
            "system_state",
            "system_uptime",
            "system_uptime_seconds",
            "last_reboot_time",
            "last_reset_reason",
            "current_time",
            "fabric_id",
            "fabric_domain",
            "control_plane_mtu",
            "software_version",
            "image_type",
            "system_version",
            "kind",
            "slot",
            "index",
            "revision",
            "state",
            "layer",
            "mode",
            "mtu",
            "speed",
            "oper_speed",
            "duplex",
            "admin_status",
            "oper_status",
            "oper_status_reason",
            "port_type",
            "usage",
            "access_vlan",
            "native_vlan",
            "allowed_vlans",
            "vlan_id",
            "last_link_change",
            "port_channel",
            "members",
            "type",
            "protocol",
            "local_port",
            "remote_name",
            "remote_port",
            "remote_port_id",
            "remote_model",
            "remote_software",
            "capabilities",
            "ttl",
            "encap",
            "encap_vlan",
            "fabric_encap",
            "epg",
            "bridge_domain",
            "vrf",
            "score",
            "previous_score",
            "change",
            "max_severity",
            "chassis_score",
            "chassis_previous_score",
            "code",
            "severity",
            "cause",
            "created",
            "lifecycle",
            "subject",
            "domain",
            "acknowledged",
            "total",
            "by_severity",
            "items",
            "truncated",
            "preference",
            "metric",
            "next_hops",
            "interface",
            "bgp_peers",
            "adjacencies",
            "asn",
            "admin_state",
            "oper_state",
            "flags",
            "pc_tag",
            "id",
            "local_state",
            "remote_state",
            "domain_id",
            "peer_state",
            "peer_state_reason",
            "keepalive_state",
            "interfaces",
            "tenant",
            "app_profile",
            "source_pc_tag",
            "destination_pc_tag",
            "source_epg",
            "destination_epg",
            "filter_id",
            "action",
            "direction",
            "priority",
            "scope",
            "ether_type",
            "source_port_from",
            "source_port_to",
            "destination_port_from",
            "destination_port_to",
            "stateful",
            "apply_to_fragments",
            "tcp_flags",
            "entries",
            "provider_epgs",
            "consumer_epgs",
            "subjects",
            "provided",
            "consumed",
            "protocols",
            "nodes",
            "external_epgs",
            "subnets",
            "aggregate",
            "external_epg",
            "esg",
            "leaves",
            "rule",
            "outcome",
            "note",
            "programmed",
            "programmed_summary",
            "programmed_note",
            "programmed_leaves_skipped",
            "contracts",
            "enforced",
            "preferred_group",
            "any_provided",
            "any_consumed",
            "isolated",
            "taboo",
            "last_changed",
            "learned_at",
            "first_seen",
            "time",
            "leaf_records",
            "leaf_records_failed",
            "events",
            "events_unavailable",
            "source",
            "destination",
            "verdict",
            "reason",
            "explanation",
            "notes",
            "how",
            "epg_path",
            "port",
            "matching_entries",
            "attachments",
            "node_ids",
            "owner",
            "rules",
            "filters",
        ),
        _INV,
    ),
    **dict.fromkeys(
        (
            "serial_number",
            "router_id",
            "ip",
            "mac",
            "ips",
            "gateway",
            "tep_address",
            "tep_pool",
            "fabric_mac",
            "management_ip",
            "oob_ip",
            "inb_ip",
            "mac_address",
            "ipv4_addresses",
            "address",
            "remote_mgmt_ip",
            "remote_chassis_id",
            "prefix",
            "peer_ip",
            "virtual_ip",
            "system_mac",
            "attributes",
        ),
        _ADDR,
    ),
    # Free text someone typed (it can hold a password or an instruction).
    **dict.fromkeys(("description",), _CONTENT),
}
# Never sent: raw APIC distinguished names of objects the tool does not name.
EXCLUDED = frozenset({"dn", "epg_dn", "raw"})


def project(policy: SharingPolicy, value: Any, withheld: dict[str, str]) -> Any:
    """Keep what the opt-ins allow; record what a switch would release."""
    if isinstance(value, BaseModel):
        kept: dict[str, Any] = {}
        for key in type(value).model_fields:
            item = getattr(value, key)
            rule = RULES.get(key)
            if rule is None:
                continue  # fail closed: a field no rule names is never sent
            if not policy.allows(rule):
                if item not in (None, "", (), {}):
                    withheld[key] = not_shared_marker(rule)["not_shared"]
                continue
            if item is not None:
                kept[key] = project(policy, item, withheld)
        # The raw DN is never sent, but an EPG must keep its identity: an external EPG has no
        # application profile or EPG name in the model, so give the readable path.
        if isinstance(value, AciEpg) and value.epg_dn and policy.allows(DataClass.INVENTORY):
            kept["epg_path"] = readable_epg(value.epg_dn)
        return kept
    if isinstance(value, (list, tuple)):
        return [project(policy, v, withheld) for v in value]
    return value
