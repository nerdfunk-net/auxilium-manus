"""get_step_result(include=['discovery']): the crawl record of a Discover Network step."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from models.ai_assistant import RunViewerContext
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.surfaces import build_run_viewer_session

NODE = "disc-1"
RECORD: dict[str, Any] = {
    "visited": [
        {"name": "core1", "ip": "10.1.0.1", "depth": 0, "discovered_from": None, "seed": True,
         "cdp_status": "ok"},
        {"name": "sw2", "ip": "10.1.0.2", "depth": 1, "discovered_from": "core1", "seed": False,
         "cdp_status": "not_enabled"},
    ],
    "seen_not_visited": [
        {"name": "far", "ip": "172.16.0.9", "platform": "cisco WS-C3850",
         "reason": "out_of_scope", "seen_from": "core1", "depth": 1},
        {"name": "ap-1", "ip": None, "platform": "", "reason": "no_management_ip",
         "seen_from": "sw2", "depth": 2},
        {"name": "far2", "ip": "172.16.0.10", "platform": "", "reason": "out_of_scope",
         "seen_from": "core1", "depth": 1},
    ],
    "edges": [{"from": "core1", "local_port": "Gi1", "to": "sw2", "remote_port": "Gi2",
               "to_ip": "10.1.0.2"}],
    "limits_hit": ["max_depth"],
    "truncated": False,
}  # fmt: skip


def _run(record: Any = RECORD, key: str = f"{NODE}.discovery") -> dict[str, Any]:
    envelope = {
        "devices": {"d1": {"id": "d1", "name": "core1", "status": "ok"}},
        "metadata": {key: record, "other.total": 3},
    }
    step = {
        "step_node_id": NODE,
        "step_type": "discover-network",
        "step_name": "Discover Network",
        "status": "success",
        "output": {"outcomes": {"success": envelope, "failure": dict(envelope)}},
    }
    return {
        "id": 7, "workflow_id": 3, "status": "success", "trigger_type": "ai_assistant",
        "device_ids": ["d1"], "run_inputs": {}, "step_results": [step], "device_groups": [],
    }  # fmt: skip


class _Reader:
    def __init__(self, run: dict[str, Any]) -> None:
        self.run = run

    async def get_run(self, run_id):  # noqa: ANN001, ANN201
        return self.run

    async def list_events(self, run_id, limit, node_id):  # noqa: ANN001, ANN201
        return []

    async def get_artifact(self, run_id, artifact_id):  # noqa: ANN001, ANN201
        return None

    async def get_workflow(self, run_id):  # noqa: ANN001, ANN201
        return {"name": "Walk", "canvas_nodes": [], "canvas_edges": [], "static_attributes": []}

    async def list_runs(self, workflow_id, statuses, limit):  # noqa: ANN001, ANN201
        return []


def _call(run: dict[str, Any], *, inventory=True, addresses=True, content=True, **input_: Any):  # noqa: ANN001, ANN201
    session = build_run_viewer_session(
        user_id=1,
        context=RunViewerContext(surface="run_viewer", run_id=7),
        reader=_Reader(run),
        sharing=SharingPolicy(inventory=inventory, addresses=addresses, content=content),
    )
    return asyncio.run(session.toolbox.execute(ToolCall("1", "get_step_result", input_)))


def _discovery(out) -> dict[str, Any]:  # noqa: ANN001
    return json.loads(out.content)["discovery"]


def test_the_crawl_record_is_returned_when_asked_for() -> None:
    out = _call(_run(), node_id=NODE, include=["discovery"])
    view = _discovery(out)
    assert view["visited_total"] == 2
    assert [v["name"] for v in view["visited"]] == ["core1", "sw2"]
    assert view["visited"][1]["cdp_status"] == "not_enabled"
    assert view["seen_not_visited_total"] == 3
    assert view["seen_by_reason"] == {"out_of_scope": 2, "no_management_ip": 1}
    assert {s["name"] for s in view["seen_not_visited"]} == {"far", "ap-1", "far2"}
    assert view["links_total"] == 1
    assert view["limits_hit"] == ["max_depth"]
    assert view["truncated"] is False


def test_it_is_not_returned_unless_asked_for() -> None:
    assert "discovery" not in json.loads(_call(_run(), node_id=NODE).content)


def test_it_comes_before_the_per_device_lists_so_a_size_cut_never_drops_it() -> None:
    keys = list(json.loads(_call(_run(), node_id=NODE, include=["discovery"]).content))
    assert keys.index("discovery") < keys.index("outcomes")


def test_it_needs_names_addresses_and_content_to_be_shared() -> None:
    for kwargs, missing in (
        ({"inventory": False, "addresses": False, "content": True}, "inventory_data"),
        ({"inventory": True, "addresses": False, "content": True}, "device_addresses"),
        ({"inventory": True, "addresses": True, "content": False}, "content_data"),
    ):
        out = _call(_run(), node_id=NODE, include=["discovery"], **kwargs)
        view = _discovery(out)
        assert view["not_shared"] == missing
        assert "10.1.0.1" not in out.content and "core1" not in out.content.split("outcomes")[0]


def test_a_long_record_is_cut_and_says_so() -> None:
    big = {
        **RECORD,
        "visited": [
            {"name": f"n{i}", "ip": f"10.1.1.{i % 250}", "depth": 1, "discovered_from": "core1",
             "seed": False, "cdp_status": "ok"}
            for i in range(120)
        ],
        "seen_not_visited": [
            {"name": f"s{i}", "ip": None, "platform": "", "reason": "no_management_ip",
             "seen_from": "core1", "depth": 1}
            for i in range(90)
        ],
    }  # fmt: skip
    view = _discovery(_call(_run(big), node_id=NODE, include=["discovery"]))
    assert view["visited_total"] == 120 and len(view["visited"]) == 50
    assert view["seen_not_visited_total"] == 90 and len(view["seen_not_visited"]) == 50
    assert "cut" in view["note"]


def test_only_a_real_discovery_record_is_returned() -> None:
    for record in ("text", {"visited": "no"}, None):
        out = _call(_run(record), node_id=NODE, include=["discovery"])
        assert "discovery" not in json.loads(out.content)
    out = _call(_run(RECORD, key="x.log_attributes"), node_id=NODE, include=["discovery"])
    assert "discovery" not in json.loads(out.content)


def test_a_secret_in_a_reported_name_is_redacted() -> None:
    hostile = {
        **RECORD,
        "visited": [
            {
                "name": "enable secret 9 $9$abcdefghijklmnop",
                "ip": "10.1.0.9",
                "depth": 1,
                "discovered_from": "core1",
                "seed": False,
                "cdp_status": "ok",
            }
        ],
    }
    out = _call(_run(hostile), node_id=NODE, include=["discovery"])
    assert "$9$abcdefghijklmnop" not in out.content


def test_values_of_the_wrong_type_become_null_instead_of_leaking_through() -> None:
    odd = {
        **RECORD,
        "visited": [
            {
                "name": "sw9",
                "ip": 5,
                "depth": "x",
                "discovered_from": None,
                "seed": "yes",
                "cdp_status": ["a"],
            }
        ],
        "limits_hit": ["max_depth", 3, None],
    }
    view = _discovery(_call(_run(odd), node_id=NODE, include=["discovery"]))
    row = view["visited"][0]
    assert (row["ip"], row["depth"], row["cdp_status"], row["seed"]) == (None, None, None, False)
    assert view["limits_hit"] == ["max_depth"]


def test_include_accepts_three_values() -> None:
    out = _call(_run(), node_id=NODE, include=["attributes", "parsed", "discovery"])
    assert not out.is_error and "discovery" in json.loads(out.content)
