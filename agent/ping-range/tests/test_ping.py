import ipaddress
import json
import unittest
from unittest.mock import AsyncMock, patch

from manus_agent.fping import FpingError, HostResult
from manus_agent.ping import (
    DEFAULT_ALLOWED_NETWORKS,
    PingSettings,
    ping_range,
    settings_from_env,
)

SETTINGS = PingSettings(max_hosts=64, allowed=())


def inputs(range_text: object = "10.0.0.1-3", path: str = "range") -> dict:
    return {"attributes": {path: range_text}, "content": {}}


def fping_result(*rows: tuple[str, float | None]) -> AsyncMock:
    return AsyncMock(
        return_value=[
            HostResult(ip, rtt is not None, rtt, 0 if rtt is not None else 100) for ip, rtt in rows
        ]
    )


class PingRangeTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_reachable_hosts_by_default_with_totals(self) -> None:
        run = fping_result(("10.0.0.1", 0.5), ("10.0.0.2", None), ("10.0.0.3", 1.25))
        with patch("manus_agent.ping.run_fping", run):
            answer = await ping_range({}, inputs(), SETTINGS)
        assert answer == {
            "hosts": [
                {
                    "ip": "10.0.0.1",
                    "reachable": True,
                    "rtt_ms": 0.5,
                    "loss_percent": 0,
                    "hostname": None,
                },
                {
                    "ip": "10.0.0.3",
                    "reachable": True,
                    "rtt_ms": 1.25,
                    "loss_percent": 0,
                    "hostname": None,
                },
            ],
            "total": 3,
            "reachable": 2,
            "truncated": False,
        }
        run.assert_awaited_once_with(["10.0.0.1", "10.0.0.2", "10.0.0.3"], count=1, timeout_ms=500)

    async def test_include_unreachable_lists_every_host_and_fills_gaps(self) -> None:
        run = fping_result(("10.0.0.1", 0.5))  # fping reported only one of three hosts
        with patch("manus_agent.ping.run_fping", run):
            answer = await ping_range({"include_unreachable": True}, inputs(), SETTINGS)
        assert [(h["ip"], h["reachable"]) for h in answer["hosts"]] == [
            ("10.0.0.1", True),
            ("10.0.0.2", False),
            ("10.0.0.3", False),
        ]
        assert answer["hosts"][1]["rtt_ms"] is None and answer["hosts"][1]["loss_percent"] == 100
        assert answer["reachable"] == 1

    async def test_dns_is_off_by_default(self) -> None:
        names = AsyncMock()
        with (
            patch("manus_agent.ping.run_fping", fping_result(("10.0.0.1", 1.0))),
            patch("manus_agent.ping.resolve_names", names),
        ):
            await ping_range({}, inputs("10.0.0.1"), SETTINGS)
        names.assert_not_awaited()

    async def test_resolve_dns_looks_up_only_reachable_hosts(self) -> None:
        names = AsyncMock(return_value={"10.0.0.1": "gw.example.net"})
        run = fping_result(("10.0.0.1", 1.0), ("10.0.0.2", None))
        with (
            patch("manus_agent.ping.run_fping", run),
            patch("manus_agent.ping.resolve_names", names),
        ):
            answer = await ping_range(
                {"resolve_dns": True, "include_unreachable": True, "dns_timeout_seconds": 3},
                inputs("10.0.0.1-2"),
                SETTINGS,
            )
        names.assert_awaited_once_with(["10.0.0.1"], timeout=3)
        assert answer["hosts"][0]["hostname"] == "gw.example.net"
        assert answer["hosts"][1]["hostname"] is None

    async def test_range_attribute_selects_the_input_path(self) -> None:
        with patch("manus_agent.ping.run_fping", fping_result(("10.9.9.9", 2.0))) as run:
            await ping_range(
                {"range_attribute": "run_input.scan"},
                inputs("10.9.9.9", path="run_input.scan"),
                SETTINGS,
            )
        assert run.await_args.args[0] == ["10.9.9.9"]

    async def test_count_and_timeout_are_passed_on(self) -> None:
        with patch("manus_agent.ping.run_fping", fping_result(("10.0.0.1", 1.0))) as run:
            await ping_range({"count": 3, "timeout_ms": 1200}, inputs("10.0.0.1"), SETTINGS)
        assert run.await_args.kwargs == {"count": 3, "timeout_ms": 1200}

    async def test_the_only_input_path_is_used_without_range_attribute(self) -> None:
        with patch("manus_agent.ping.run_fping", fping_result(("10.9.9.9", 2.0))) as run:
            await ping_range({}, inputs("10.9.9.9", path="custom.range"), SETTINGS)
        assert run.await_args.args[0] == ["10.9.9.9"]

    async def test_several_input_paths_need_a_name_unless_one_is_called_range(self) -> None:
        many = {"attributes": {"a": "10.0.0.1", "b": "10.0.0.2"}, "content": {}}
        with self.assertRaises(ValueError) as caught:
            await ping_range({}, many, SETTINGS)
        assert "range_attribute" in str(caught.exception)
        with patch("manus_agent.ping.run_fping", fping_result(("10.0.0.7", 1.0))) as run:
            both = {"attributes": {"a": "10.0.0.1", "range": "10.0.0.7"}, "content": {}}
            await ping_range({}, both, SETTINGS)
        assert run.await_args.args[0] == ["10.0.0.7"]

    async def test_a_named_path_that_was_not_sent_is_reported_with_its_name(self) -> None:
        with self.assertRaises(ValueError) as caught:
            await ping_range({"range_attribute": "x.y"}, inputs("10.0.0.1"), SETTINGS)
        assert "'x.y'" in str(caught.exception)

    async def test_attributes_that_are_not_an_object_are_a_clear_error(self) -> None:
        for attributes in (None, [], "x", 5):
            with self.subTest(attributes=attributes), self.assertRaises(ValueError) as caught:
                await ping_range({}, {"attributes": attributes}, SETTINGS)
            assert "attributes" in str(caught.exception)

    async def test_missing_range_is_a_clear_error(self) -> None:
        with self.assertRaises(ValueError) as caught:
            await ping_range({}, {"attributes": {}, "content": {}}, SETTINGS)
        assert "range" in str(caught.exception)

    async def test_bad_parameters_are_refused(self) -> None:
        bad = [
            {"count": 0},
            {"count": 6},
            {"count": True},
            {"count": "2"},
            {"timeout_ms": 10},
            {"timeout_ms": 9999},
            {"resolve_dns": "yes"},
            {"include_unreachable": 1},
            {"dns_timeout_seconds": 0},
            {"dns_timeout_seconds": 60},
            {"range_attribute": ""},
            {"range_attribute": 5},
            {"unknown": 1},
        ]
        for params in bad:
            with self.subTest(params=params), self.assertRaises(ValueError):
                await ping_range(params, inputs(), SETTINGS)

    async def test_range_errors_are_value_errors(self) -> None:
        with self.assertRaises(ValueError):
            await ping_range({}, inputs("10.0.0.0/8"), SETTINGS)

    async def test_allowed_networks_are_enforced(self) -> None:
        settings = PingSettings(max_hosts=64, allowed=(ipaddress.IPv4Network("10.0.0.0/24"),))
        with self.assertRaises(ValueError):
            await ping_range({}, inputs("192.168.0.1"), settings)

    async def test_nothing_answering_while_loopback_works_is_a_normal_empty_answer(self) -> None:
        run = AsyncMock(
            side_effect=[
                [HostResult("10.0.0.1", False, None, 100)],
                [HostResult("127.0.0.1", True, 0.02, 0)],
            ]
        )
        with patch("manus_agent.ping.run_fping", run):
            answer = await ping_range({}, inputs("10.0.0.1"), SETTINGS)
        assert answer["hosts"] == [] and answer["reachable"] == 0 and answer["total"] == 1
        assert run.await_args_list[1].args[0] == ["127.0.0.1"]

    async def test_nothing_answering_and_loopback_silent_means_fping_cannot_send(self) -> None:
        silent = [
            [HostResult("10.0.0.1", False, None, 100)],
            [HostResult("127.0.0.1", False, None, 100)],
        ]
        with (
            patch("manus_agent.ping.run_fping", AsyncMock(side_effect=silent)),
            self.assertRaises(FpingError) as caught,
        ):
            await ping_range({}, inputs("10.0.0.1"), SETTINGS)
        assert "NET_RAW" in str(caught.exception)

    async def test_fping_failure_is_reported_not_swallowed(self) -> None:
        with (
            patch("manus_agent.ping.run_fping", AsyncMock(side_effect=FpingError("no fping"))),
            self.assertRaises(FpingError),
        ):
            await ping_range({}, inputs(), SETTINGS)

    async def test_a_big_answer_is_truncated_to_fit_the_step_limit(self) -> None:
        settings = PingSettings(max_hosts=4096, allowed=())
        rows = [(f"10.0.{i // 250}.{i % 250 + 1}", 1.0) for i in range(1000)]
        names = AsyncMock(
            return_value={ip: f"a-rather-long-host-name-{ip}.corp.example.net" for ip, _ in rows}
        )
        with (
            patch("manus_agent.ping.run_fping", fping_result(*rows)),
            patch("manus_agent.ping.resolve_names", names),
        ):
            answer = await ping_range({"resolve_dns": True}, inputs("10.0.0.0/20"), settings)
        assert answer["truncated"] is True
        assert answer["reachable"] == 1000  # counts are for the whole scan
        assert len(json.dumps(answer["hosts"], separators=(",", ":"))) <= 60_000
        assert len(answer["hosts"]) < 1000
        ips = [int(ipaddress.IPv4Address(h["ip"])) for h in answer["hosts"]]
        assert ips == sorted(ips)


class SettingsFromEnvTests(unittest.TestCase):
    def test_defaults_allow_private_networks_only(self) -> None:
        for env in ({}, {"MANUS_AGENT_PING_ALLOWED_NETWORKS": ""}):
            settings = settings_from_env(env)
            assert settings.max_hosts == 4096
            assert settings.allowed == DEFAULT_ALLOWED_NETWORKS
            assert {str(n) for n in settings.allowed} == {
                "10.0.0.0/8",
                "172.16.0.0/12",
                "192.168.0.0/16",
            }

    def test_everything_must_be_asked_for_explicitly(self) -> None:
        settings = settings_from_env({"MANUS_AGENT_PING_ALLOWED_NETWORKS": "0.0.0.0/0"})
        assert [str(n) for n in settings.allowed] == ["0.0.0.0/0"]

    def test_values(self) -> None:
        settings = settings_from_env(
            {
                "MANUS_AGENT_PING_MAX_HOSTS": "512",
                "MANUS_AGENT_PING_ALLOWED_NETWORKS": "10.0.0.0/8, 192.168.0.0/16",
            }
        )
        assert settings.max_hosts == 512
        assert len(settings.allowed) == 2

    def test_invalid_values_raise_a_readable_error(self) -> None:
        for env in (
            {"MANUS_AGENT_PING_MAX_HOSTS": "many"},
            {"MANUS_AGENT_PING_MAX_HOSTS": "0"},
            {"MANUS_AGENT_PING_MAX_HOSTS": "999999"},
            {"MANUS_AGENT_PING_ALLOWED_NETWORKS": "nonsense"},
        ):
            with self.subTest(env=env), self.assertRaises(ValueError) as caught:
                settings_from_env(env)
            assert "MANUS_AGENT_PING" in str(caught.exception)
