"""services/parsing/neighbors.py: one reading of a CDP / LLDP output for both steps (W3b-08)."""

from __future__ import annotations

import json

import pytest

from models.client_data import CollectionStatus
from services.parsing.neighbors import (
    SUPPORTED_CISCO_DEVICE_TYPES,
    TableKind,
    classify_neighbor_table,
    decode_textfsm_output,
)
from workflow_steps.collect_client_data.commands import CMD_CDP, CMD_LLDP
from workflow_steps.collect_client_data.parsing import classify_output
from workflow_steps.discover_network.parsing import CdpStatus, classify_cdp_output

ROWS = json.dumps([{"neighbor_name": "B", "local_interface": "Gi1/0/1"}])


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        ("", TableKind.UNPARSEABLE),
        ("   \n", TableKind.UNPARSEABLE),
        ("[]", TableKind.ROWS),
        (ROWS, TableKind.ROWS),
        ('{"a": 1}', TableKind.UNPARSEABLE),
        ("[1, 2]", TableKind.UNPARSEABLE),
        ("[{}, 3]", TableKind.UNPARSEABLE),
        ("% Invalid input detected at '^' marker.", TableKind.REFUSED),
        ("% CDP is not enabled", TableKind.PROTOCOL_OFF),
        ("LLDP is not running on this switch", TableKind.PROTOCOL_OFF),
        ("Total cdp entries displayed : 0", TableKind.EMPTY),
        ("Total entries displayed: 0", TableKind.EMPTY),
        ("Total cdp entries displayed : 3", TableKind.UNPARSEABLE),
        ("garbage", TableKind.UNPARSEABLE),
    ],
)
def test_classify_neighbor_table(raw: str, kind: TableKind) -> None:
    assert classify_neighbor_table(raw).kind is kind


def test_rows_are_returned_only_for_a_table() -> None:
    assert classify_neighbor_table(ROWS).rows == json.loads(ROWS)
    assert classify_neighbor_table("garbage").rows == []


def test_decode_textfsm_output() -> None:
    assert decode_textfsm_output(ROWS) == json.loads(ROWS)
    assert decode_textfsm_output("[]") == []
    assert decode_textfsm_output("raw text") is None
    assert decode_textfsm_output('{"a": 1}') is None
    assert decode_textfsm_output("[1]") is None


def test_the_supported_device_types_are_the_cisco_family() -> None:
    assert SUPPORTED_CISCO_DEVICE_TYPES == {"cisco_ios", "cisco_xe", "cisco_nxos"}


# The two steps keep their own vocabulary; the "protocol off" mapping differs on purpose:
# discover walks CDP, so a switched-off CDP fails the seed; collect treats it as "not supported".
@pytest.mark.parametrize(
    ("raw", "cdp", "collect"),
    [
        ("% CDP is not enabled", CdpStatus.NOT_ENABLED, "not_supported"),
        ("% Invalid input detected", CdpStatus.NOT_SUPPORTED, "not_supported"),
        ("Total cdp entries displayed : 0", CdpStatus.OK, "ok"),
        ("garbage", CdpStatus.UNPARSEABLE, "no_template"),
        ("", CdpStatus.UNPARSEABLE, "no_template"),
        (ROWS, CdpStatus.OK, "ok"),
    ],
)
def test_both_steps_map_the_same_table_kind_with_their_own_vocabulary(
    raw: str, cdp: CdpStatus, collect: CollectionStatus
) -> None:
    assert classify_cdp_output(raw).status is cdp
    for command in (CMD_CDP, CMD_LLDP):
        assert classify_output(raw, platform="cisco_ios", command=command).status == collect
