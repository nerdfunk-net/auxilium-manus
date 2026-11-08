"""POST /v1/learn-replay: mock data, validation, the endpoint and (with genie) a real replay."""

from __future__ import annotations

import asyncio
import glob
import json
import os
import tempfile

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import replay
from app.config import get_settings
from app.replay_mock import ReplayInputError, build_mock_data, validate
from tests import TEST_TOKEN

SUMMARY = "For address family: IPv4 Unicast\nBGP router identifier 192.168.178.240, local AS number 65000\nBGP table version is 3, main routing table version 3\n2 network entries using 496 bytes of memory\n2 path entries using 272 bytes of memory\n1/1 BGP path/bestpath attribute entries using 288 bytes of memory\n0 BGP route-map cache entries using 0 bytes of memory\n0 BGP filter-list cache entries using 0 bytes of memory\nBGP using 1056 total bytes of memory\nBGP activity 2/0 prefixes, 2/0 paths, scan interval 60 secs\n2 networks peaked at 10:00:00 Nov 8 2026 UTC (00:40:00.000 ago)\n\nNeighbor        V           AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd\n192.168.178.241 4        65000      50      52        3    0    0 00:40:11        1\n"
NEIGHBORS = "BGP neighbor is 192.168.178.241,  remote AS 65000, internal link\n  BGP version 4, remote router ID 192.168.178.241\n  BGP state = Established, up for 00:40:11\n  Last read 00:00:27, last write 00:00:21, hold time is 180, keepalive interval is 60 seconds\n  Neighbor sessions:\n    1 active, is not multisession capable (disabled)\n  Neighbor capabilities:\n    Route refresh: advertised and received(new)\n    Four-octets ASN Capability: advertised and received\n    Address family IPv4 Unicast: advertised and received\n    Enhanced Refresh Capability: advertised and received\n    Multisession Capability: \n    Stateful switchover support enabled: NO for session 1\n  Message statistics:\n    InQ depth is 0\n    OutQ depth is 0\n                         Sent       Rcvd\n    Opens:                  4          4\n    Notifications:          3          0\n    Updates:                5          4\n    Keepalives:            50         49\n    Route Refresh:          0          0\n    Total:                 62         57\n  Default minimum time between advertisement runs is 0 seconds\n\n For address family: IPv4 Unicast\n  Session: 192.168.178.241\n  BGP table version 3, neighbor version 3/0\n  Output queue size : 0\n  Index 1, Advertise bit 0\n  1 update-group member\n  Slow-peer detection is disabled\n  Slow-peer split-update-group dynamic is disabled\n                                 Sent       Rcvd\n  Prefix activity:               ----       ----\n    Prefixes Current:               1          1 (Consumes 80 bytes)\n    Prefixes Total:                 1          1\n    Implicit Withdraw:              0          0\n    Explicit Withdraw:              0          0\n    Used as bestpath:             n/a          1\n    Used as multipath:            n/a          0\n\n                                   Outbound    Inbound\n  Local Policy Denied Prefixes:    --------    -------\n    Total:                                0          0\n  Number of NLRIs in the update sent: max 1, min 0\n  Last detected as dynamic slow peer: never\n  Dynamic slow peer recovered: never\n  Refresh Epoch: 1\n  Last Sent Refresh Start-of-rib: never\n  Last Sent Refresh End-of-rib: never\n  Last Received Refresh Start-of-rib: never\n  Last Received Refresh End-of-rib: never\n\n  Address tracking is enabled, the RIB does have a route to 192.168.178.241\n  Connections established 4; dropped 3\n  Last reset 00:40:11, due to Router ID changed of session 1\n  Transport(tcp) path-mtu-discovery is enabled\n  Graceful-Restart is disabled\nConnection state is ESTAB, I/O status: 1, unread input bytes: 0\nConnection is ECN Disabled, Mininum incoming TTL 0, Outgoing TTL 255\nLocal host: 192.168.178.240, Local port: 179\nForeign host: 192.168.178.241, Foreign port: 52114\nConnection tableid (VRF): 0\nMaximum output segment queue size: 50\n"
COMMANDS = [
    {"command": "show bgp all summary", "output": SUMMARY},
    {"command": "show bgp all neighbors", "output": NEIGHBORS},
]


@pytest.fixture(autouse=True)
def _shim_token(monkeypatch):
    monkeypatch.setenv("PYATS_SHIM_TOKEN", TEST_TOKEN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(replay.router)
    return TestClient(app)


def _headers():
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


def _body(**overrides):
    return {"os": "iosxe", "feature": "bgp", "commands": COMMANDS, **overrides}


def test_mock_data_answers_each_command_and_the_connect_commands():
    data = yaml.safe_load(build_mock_data(COMMANDS))

    answers = data["execute"]["commands"]
    assert answers["show bgp all summary"]["response"] == [SUMMARY]
    assert "show version | include operating mode" in answers
    assert data["connect"]["commands"][""]["new_state"] == "execute"


def test_carriage_returns_are_normalised_in_the_replayed_text():
    data = yaml.safe_load(
        build_mock_data([{"command": "show x", "output": "a\r\nb\rc"}])
    )

    assert data["execute"]["commands"]["show x"]["response"] == ["a\nb\nc"]


@pytest.mark.parametrize(
    ("os_name", "feature", "commands"),
    [
        ("junos", "bgp", COMMANDS),
        ("iosxe", "all", COMMANDS),
        ("iosxe", "bgp", []),
        ("iosxe", "bgp", COMMANDS + COMMANDS[:1]),
        ("iosxe", "bgp", [{"command": "show a\nreload", "output": ""}]),
        ("iosxe", "bgp", [{"command": " ", "output": ""}]),
        ("iosxe", "bgp", [{"command": f"show {i}", "output": ""} for i in range(33)]),
    ],
)
def test_validate_refuses_what_cannot_be_replayed(os_name, feature, commands):
    with pytest.raises(ReplayInputError):
        validate(os_name, feature, commands)


def test_the_endpoint_needs_the_token(client):
    assert client.post("/v1/learn-replay", json=_body()).status_code in (401, 403)


def test_the_endpoint_refuses_bad_input_with_400(client):
    response = client.post(
        "/v1/learn-replay", json=_body(os="junos"), headers=_headers()
    )

    assert response.status_code == 400


def test_the_endpoint_returns_the_workers_payload(client, monkeypatch):
    async def fake(request):
        assert request["feature"] == "bgp" and len(request["commands"]) == 2
        return replay.ReplayResponse(payload={"info": {"a": 1}, "_exclude": []})

    monkeypatch.setattr(replay, "_run_worker", fake)

    response = client.post("/v1/learn-replay", json=_body(), headers=_headers())

    assert response.status_code == 200
    assert response.json() == {
        "payload": {"info": {"a": 1}, "_exclude": []},
        "error": None,
    }


def test_last_json_line_ignores_genie_log_lines():
    text = 'INFO connecting\n{"ok": false}\n{broken\n{"ok": true, "payload": {}}\n'

    assert replay._last_json_line(text) == {"ok": True, "payload": {}}
    assert replay._last_json_line("no json here") is None


async def test_a_worker_that_prints_nothing_gives_the_fixed_error(monkeypatch):
    class Dead:
        returncode = 1

        async def communicate(self, _data):
            return b"", b""

    async def spawn(*_args, **_kwargs):
        return Dead()

    monkeypatch.setattr(replay.asyncio, "create_subprocess_exec", spawn)

    result = await replay._run_worker({"os": "iosxe", "feature": "bgp", "commands": []})

    assert result.error == replay.REPLAY_FAILED and result.payload is None


def test_a_real_replay_learns_the_session_with_genie():
    pytest.importorskip("genie")
    from app.replay_worker import learn

    payload = learn("iosxe", "bgp", COMMANDS)

    peer = payload["info"]["instance"]["default"]["vrf"]["default"]["neighbor"][
        "192.168.178.241"
    ]
    assert peer["session_state"] == "Established"
    assert peer["bgp_session_transport"]["connection"]["reset_reason"].startswith(
        "Router ID"
    )
    assert "msg_rcvd" in payload["_exclude"]


def test_a_later_line_that_only_looks_like_json_does_not_hide_the_result():
    text = '{"ok": true, "payload": {"info": {}}}\n{not json}\n{"also": bad}\n'

    assert replay._last_json_line(text) == {"ok": True, "payload": {"info": {}}}
    assert replay._last_json_line("{not json}\n[1, 2]\n") is None


def test_non_finite_numbers_are_made_safe_for_the_json_line():
    from app.replay_worker import _json_safe

    safe = _json_safe({"a": float("nan"), "b": float("inf"), "c": 1.5})

    assert json.loads(json.dumps(safe)) == {"a": "nan", "b": "inf", "c": 1.5}


def test_the_body_is_refused_while_it_is_read_not_after_it_is_parsed(
    client, monkeypatch
):
    monkeypatch.setattr(replay, "MAX_BODY_BYTES", 2_000)

    declared = client.post("/v1/learn-replay", json=_body(), headers=_headers())
    assert declared.status_code == 413

    def chunks():  # no declared length: the limit still applies to what arrives
        yield b'{"os": "iosxe", "feature": "bgp", "commands": ['
        yield b"x" * 5_000

    streamed = client.post("/v1/learn-replay", content=chunks(), headers=_headers())
    assert streamed.status_code == 413


def test_an_invalid_body_gets_a_fixed_422_that_does_not_echo_the_output(client):
    body = _body(commands=[{"command": "show x", "output": "SECRET-TEXT", "extra": 1}])
    body["commands"][0]["output"] = "y" * (replay.MAX_OUTPUT_CHARS + 1)
    too_long = client.post("/v1/learn-replay", json=body, headers=_headers())
    missing = client.post("/v1/learn-replay", json={"os": "iosxe"}, headers=_headers())

    for response in (too_long, missing):
        assert response.status_code == 422
        assert response.json() == {"detail": "The request body is not valid"}


class _Hung:
    """A worker that never answers."""

    def __init__(self):
        self.pid = 424242
        self.returncode = None
        self.killed = False

    async def communicate(self, _data):
        await asyncio.sleep(60)

    def kill(self):
        self.killed = True
        self.returncode = -9

    async def wait(self):
        return self.returncode


@pytest.fixture
def hung(monkeypatch):
    process = _Hung()
    groups = []

    async def spawn(*_args, **kwargs):
        assert kwargs.get("start_new_session") is True  # the worker leads its own group
        return process

    monkeypatch.setattr(replay.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(replay.os, "killpg", lambda pid, sig: groups.append((pid, sig)))
    process.groups = groups
    return process


def _leftover_dirs():
    return glob.glob(os.path.join(tempfile.gettempdir(), "replay-*"))


async def test_a_timed_out_replay_kills_the_group_and_removes_its_directory(
    hung, monkeypatch
):
    monkeypatch.setattr(replay, "REPLAY_TIMEOUT_SECONDS", 0.05)
    before = set(_leftover_dirs())

    result = await replay._run_worker({"os": "iosxe", "feature": "bgp", "commands": []})

    assert result.error == replay.REPLAY_TIMED_OUT
    assert hung.groups and hung.groups[0][0] == hung.pid
    assert set(_leftover_dirs()) == before


async def test_a_cancelled_request_still_kills_the_worker_and_cleans_up(hung):
    before = set(_leftover_dirs())
    task = asyncio.create_task(
        replay._run_worker({"os": "iosxe", "feature": "bgp", "commands": []})
    )
    await asyncio.sleep(0.05)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert hung.groups and hung.killed
    assert set(_leftover_dirs()) == before


async def test_killing_a_worker_that_already_exited_is_not_an_error(hung, monkeypatch):
    def gone(_pid, _sig):
        raise ProcessLookupError

    monkeypatch.setattr(replay.os, "killpg", gone)
    monkeypatch.setattr(replay, "REPLAY_TIMEOUT_SECONDS", 0.05)

    result = await replay._run_worker({"os": "iosxe", "feature": "bgp", "commands": []})

    assert result.error == replay.REPLAY_TIMED_OUT
