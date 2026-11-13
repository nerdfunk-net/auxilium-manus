"""Executor of the discover-network step, against a scripted Netmiko (no SSH, no database)."""

from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from nautobot_read.client import NautobotError, Page

from models.failure import FailureInfo
from models.workflow_context import DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.network.netmiko.connection import CommandResult
from workflow_steps.discover_network.config import get_config
from workflow_steps.discover_network.crawler import Target, VisitError
from workflow_steps.discover_network.executor import _make_visit, execute
from workflow_steps.discover_network.nautobot_lookup import ManagementIpLookup
from workflow_steps.discover_network.options import parse_options

MODULE = "workflow_steps.discover_network.executor"
CDP = "show cdp neighbors detail"


def _row(
    name: str, ip: str, *, caps: str = "Router Switch IGMP", platform: str = "cisco WS-C3850"
) -> dict[str, str]:
    return {
        "neighbor_name": name, "mgmt_address": ip, "platform": platform,
        "local_interface": "Gi1/0/1", "neighbor_interface": "Gi1/0/2", "capabilities": caps,
    }  # fmt: skip


class _FakeNetmiko:
    """host -> CDP output (a str) or a CommandResult / exception to return."""

    def __init__(self, outputs: dict[str, Any]) -> None:
        self.outputs = outputs
        self.hosts: list[str] = []

    async def send_commands(
        self, *, host: str, commands: list[str], **kwargs: Any
    ) -> CommandResult:
        self.hosts.append(host)
        assert commands == [CDP]
        value = self.outputs.get(host, "% CDP is not enabled\n")
        if isinstance(value, Exception):
            raise value
        if isinstance(value, CommandResult):
            return value
        return CommandResult(success=True, output="", command_outputs={CDP: value})


def _cdp(*rows: dict[str, str]) -> str:
    return json.dumps(list(rows))


def _device(device_id: str, name: str, ip: str) -> DeviceContext:
    return DeviceContext(
        id=device_id, name=name, hostname=name, primary_ip4=f"{ip}/24", network_driver="cisco_ios"
    )


class _FakeNautobot:
    """``list_page`` answers keyed by (root, filter name, value); ``fail`` simulates an outage."""

    def __init__(self, tables: dict[tuple[str, str, str], list[dict[str, Any]]]) -> None:
        self.tables = tables
        self.fail = False

    async def list_page(
        self, root: str, selection: str, filters: dict[str, list[str]], *, limit: int, offset: int
    ) -> Page:
        del selection, limit, offset
        if self.fail:
            raise NautobotError("Could not reach Nautobot.")
        (name, values), = ((k, v) for k, v in filters.items() if v)
        return Page(items=tuple(self.tables.get((root, name, values[0]), [])), has_more=False)


def _nb_device(name: str, primary: str) -> dict[str, Any]:
    return {"id": name, "name": name, "primary_ip4": {"address": primary}}


class DiscoverNetworkExecutorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.pool = AsyncMock()
        for target, value in (
            (f"{MODULE}.object_session", {"return_value": MagicMock()}),
            (f"{MODULE}.resolve_ssh_credential", {"return_value": ("admin", "secret")}),
            (
                f"{MODULE}.settings",
                {"discover_network_follow_enabled": True},
            ),
        ):
            patcher = (
                patch(target, **value)
                if "settings" not in target
                else patch(target, MagicMock(**value))
            )
            patcher.start()
            self.addCleanup(patcher.stop)

    async def _run(
        self,
        devices: dict[str, DeviceContext],
        netmiko: _FakeNetmiko,
        config: dict[str, Any] | None = None,
        run_inputs: dict[str, Any] | None = None,
    ) -> list[Any]:
        run = MagicMock()
        run.id = 1
        run.run_inputs = run_inputs or {}
        run.triggered_by_id = 1
        merged = {**get_config(), "credential_reference": "lab-ssh", **(config or {})}
        with patch(f"{MODULE}.NetmikoService", return_value=netmiko):
            return await execute(
                config=merged,
                context=WorkflowContext(run_id="r", workflow_id="w", devices=devices),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="disc-1",
                device_sessions=self.pool,
            )

    @staticmethod
    def _devices(outcomes: list[Any], name: str) -> dict[str, DeviceContext]:
        for outcome in outcomes:
            if outcome.name == name:
                return outcome.context.devices
        return {}

    async def test_follows_neighbours_inside_the_prefixes_and_lists_the_rest(self) -> None:
        netmiko = _FakeNetmiko(
            {
                "10.1.0.1": _cdp(_row("B.lab", "10.1.0.2"), _row("far", "172.16.0.9")),
                "10.1.0.2": _cdp(_row("A", "10.1.0.1")),
            }
        )
        outcomes = await self._run(
            {"d1": _device("d1", "A", "10.1.0.1")},
            netmiko,
            {"follow_neighbors": True, "permitted_prefixes": ["10.1.0.0/16"]},
        )

        self.assertEqual(netmiko.hosts, ["10.1.0.1", "10.1.0.2"])
        ok = self._devices(outcomes, "success")
        self.assertEqual(sorted(d.name for d in ok.values()), ["A", "B.lab"])
        discovered = next(d for d in ok.values() if d.name == "B.lab")
        self.assertEqual(discovered.primary_ip4, "10.1.0.2")
        self.assertEqual(discovered.source, "discover-network")
        record = discovered.parsed["disc-1"]["discovery"]
        self.assertEqual((record["depth"], record["discovered_from"]), (1, "A"))
        summary = outcomes[0].context.metadata["disc-1.discovery"]
        self.assertEqual([v["name"] for v in summary["visited"]], ["A", "B.lab"])
        self.assertEqual(
            [(s["name"], s["reason"]) for s in summary["seen_not_visited"]],
            [("far", "out_of_scope")],
        )
        self.assertEqual(self._devices(outcomes, "failure"), {})

    async def test_a_virtual_switch_reporting_linux_is_followed_as_ios_xe(self) -> None:
        vm = _row("vsw", "10.1.0.7", platform="Linux Unix")
        vm["neighbor_description"] = "Cisco IOS Software [IOSXE], Linux Software (X86_64BI_LINUX)"
        netmiko = _FakeNetmiko({"10.1.0.1": _cdp(vm), "10.1.0.7": _cdp()})
        outcomes = await self._run(
            {"d1": _device("d1", "A", "10.1.0.1")},
            netmiko,
            {"follow_neighbors": True, "permitted_prefixes": ["10.1.0.0/16"]},
        )
        self.assertEqual(netmiko.hosts, ["10.1.0.1", "10.1.0.7"])
        vsw = next(d for d in self._devices(outcomes, "success").values() if d.name == "vsw")
        self.assertEqual(vsw.network_driver, "cisco_xe")

    async def test_each_device_is_logged_out_after_its_visit(self) -> None:
        netmiko = _FakeNetmiko({"10.1.0.1": _cdp(_row("B", "10.1.0.2")), "10.1.0.2": _cdp()})
        await self._run(
            {"d1": _device("d1", "A", "10.1.0.1")},
            netmiko,
            {"follow_neighbors": True, "permitted_prefixes": ["10.1.0.0/16"]},
        )
        self.assertEqual(
            [c.args[0] for c in self.pool.close_host.await_args_list], ["10.1.0.1", "10.1.0.2"]
        )

    async def test_the_management_ip_from_nautobot_is_the_host_that_is_logged_into(self) -> None:
        lookup = ManagementIpLookup(
            _FakeNautobot({("devices", "name", "B"): [_nb_device("B", "10.1.0.22/32")]})
        )
        netmiko = _FakeNetmiko(
            {"10.1.0.1": _cdp(_row("B", "192.168.9.2")), "10.1.0.22": _cdp()}
        )
        with patch(f"{MODULE}.build_management_ip_lookup", return_value=lookup) as build:
            outcomes = await self._run(
                {"d1": _device("d1", "A", "10.1.0.1")},
                netmiko,
                {
                    "follow_neighbors": True,
                    "permitted_prefixes": ["10.1.0.0/16"],
                    "nautobot_source_id": "nb-1",
                },
            )
        self.assertEqual(build.call_args.args[1], "nb-1")
        self.assertEqual(netmiko.hosts, ["10.1.0.1", "10.1.0.22"])
        found = next(d for d in self._devices(outcomes, "success").values() if d.name == "B")
        self.assertEqual(found.primary_ip4, "10.1.0.22")
        summary = outcomes[0].context.metadata["disc-1.discovery"]
        self.assertEqual(summary["management_ip_lookup"], "on")
        self.assertEqual(summary["edges"][0]["reported_ip"], "192.168.9.2")
        self.assertEqual(summary["edges"][0]["ip_source"], "nautobot_name")

    async def test_the_lookup_without_a_nautobot_source_falls_back_to_the_cdp_address(self) -> None:
        netmiko = _FakeNetmiko({"10.1.0.1": _cdp(_row("B", "10.1.0.2")), "10.1.0.2": _cdp()})
        with patch(f"{MODULE}.build_management_ip_lookup") as build:
            outcomes = await self._run(
                {"d1": _device("d1", "A", "10.1.0.1")},
                netmiko,
                {"follow_neighbors": True, "permitted_prefixes": ["10.1.0.0/16"]},
            )
        build.assert_not_called()
        self.assertEqual(netmiko.hosts, ["10.1.0.1", "10.1.0.2"])
        self.assertEqual(
            outcomes[0].context.metadata["disc-1.discovery"]["management_ip_lookup"], "no_source"
        )

    async def test_the_lookup_can_be_switched_off(self) -> None:
        netmiko = _FakeNetmiko({"10.1.0.1": _cdp(_row("B", "10.1.0.2")), "10.1.0.2": _cdp()})
        with patch(f"{MODULE}.build_management_ip_lookup") as build:
            outcomes = await self._run(
                {"d1": _device("d1", "A", "10.1.0.1")},
                netmiko,
                {
                    "follow_neighbors": True,
                    "permitted_prefixes": ["10.1.0.0/16"],
                    "nautobot_source_id": "nb-1",
                    "resolve_management_ip": False,
                },
            )
        build.assert_not_called()
        self.assertEqual(
            outcomes[0].context.metadata["disc-1.discovery"]["management_ip_lookup"], "off"
        )

    async def test_a_nautobot_outage_falls_back_to_the_cdp_address_and_is_reported(self) -> None:
        client = _FakeNautobot({})
        client.fail = True
        netmiko = _FakeNetmiko({"10.1.0.1": _cdp(_row("B", "10.1.0.2")), "10.1.0.2": _cdp()})
        with patch(
            f"{MODULE}.build_management_ip_lookup", return_value=ManagementIpLookup(client)
        ):
            outcomes = await self._run(
                {"d1": _device("d1", "A", "10.1.0.1")},
                netmiko,
                {
                    "follow_neighbors": True,
                    "permitted_prefixes": ["10.1.0.0/16"],
                    "nautobot_source_id": "nb-1",
                },
            )
        self.assertEqual(netmiko.hosts, ["10.1.0.1", "10.1.0.2"])
        self.assertEqual(
            outcomes[0].context.metadata["disc-1.discovery"]["management_ip_lookup"], "unavailable"
        )

    async def test_without_follow_only_the_seed_is_visited(self) -> None:
        netmiko = _FakeNetmiko({"10.1.0.1": _cdp(_row("B", "10.1.0.2"))})
        outcomes = await self._run({"d1": _device("d1", "A", "10.1.0.1")}, netmiko)
        self.assertEqual(netmiko.hosts, ["10.1.0.1"])
        seen = outcomes[0].context.metadata["disc-1.discovery"]["seen_not_visited"]
        self.assertEqual(seen[0]["reason"], "follow_disabled")

    async def test_unreachable_seed_fails_and_a_good_seed_still_succeeds(self) -> None:
        netmiko = _FakeNetmiko(
            {
                "10.1.0.1": CommandResult(
                    success=False, error="x", failure=FailureInfo(phase="connect", kind="timeout")
                ),
                "10.1.0.9": _cdp(),
            }
        )
        outcomes = await self._run(
            {"d1": _device("d1", "A", "10.1.0.1"), "d2": _device("d2", "S2", "10.1.0.9")}, netmiko
        )
        self.assertEqual(list(self._devices(outcomes, "success")), ["d2"])
        failed = self._devices(outcomes, "failure")["d1"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertEqual(failed.errors[0].code, "unreachable")

    async def test_rejected_login_is_reported_as_login_failed(self) -> None:
        bad = CommandResult(
            success=False, error="x", failure=FailureInfo(phase="connect", kind="auth_failed")
        )
        outcomes = await self._run(
            {"d1": _device("d1", "A", "10.1.0.1")}, _FakeNetmiko({"10.1.0.1": bad})
        )
        self.assertEqual(self._devices(outcomes, "failure")["d1"].errors[0].code, "login_failed")

    async def test_a_followed_device_with_cdp_off_is_still_discovered(self) -> None:
        netmiko = _FakeNetmiko(
            {"10.1.0.1": _cdp(_row("B", "10.1.0.2")), "10.1.0.2": "% CDP is not enabled\n"}
        )
        outcomes = await self._run(
            {"d1": _device("d1", "A", "10.1.0.1")},
            netmiko,
            {"follow_neighbors": True, "permitted_prefixes": ["10.1.0.0/16"]},
        )
        b = next(d for d in self._devices(outcomes, "success").values() if d.name == "B")
        self.assertEqual(b.parsed["disc-1"]["discovery"]["cdp_status"], "not_enabled")

    async def test_an_unsupported_seed_platform_fails_without_a_login(self) -> None:
        device = DeviceContext(
            id="d1",
            name="J",
            hostname="J",
            primary_ip4="10.1.0.1/24",
            network_driver="juniper_junos",
        )
        netmiko = _FakeNetmiko({})
        outcomes = await self._run({"d1": device}, netmiko)
        self.assertEqual(netmiko.hosts, [])
        self.assertEqual(
            self._devices(outcomes, "failure")["d1"].errors[0].code, "unsupported_platform"
        )

    async def test_a_duplicate_seed_passes_through_and_is_visited_once(self) -> None:
        netmiko = _FakeNetmiko({"10.1.0.1": _cdp()})
        outcomes = await self._run(
            {"d1": _device("d1", "A", "10.1.0.1"), "d2": _device("d2", "A2", "10.1.0.1")}, netmiko
        )
        self.assertEqual(netmiko.hosts, ["10.1.0.1"])
        self.assertEqual(sorted(self._devices(outcomes, "success")), ["d1", "d2"])

    async def test_dry_run_never_connects(self) -> None:
        netmiko = _FakeNetmiko({})
        outcomes = await self._run(
            {"d1": _device("d1", "A", "10.1.0.1")}, netmiko, {"dry_run": True}
        )
        self.assertEqual(netmiko.hosts, [])
        device = self._devices(outcomes, "success")["d1"]
        self.assertTrue(device.dry_run_results["disc-1"]["would_visit_seeds"])

    async def test_no_devices_passes_the_context_through(self) -> None:
        outcomes = await self._run({}, _FakeNetmiko({}))
        self.assertEqual([o.name for o in outcomes], ["success"])

    async def test_bad_configuration_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            await self._run(
                {"d1": _device("d1", "A", "10.1.0.1")}, _FakeNetmiko({}), {"follow_neighbors": True}
            )

    async def test_following_needs_the_operator_switch(self) -> None:
        with patch(f"{MODULE}.settings", MagicMock(discover_network_follow_enabled=False)):
            with self.assertRaisesRegex(ValueError, "DISCOVER_NETWORK_FOLLOW_ENABLED"):
                await self._run(
                    {"d1": _device("d1", "A", "10.1.0.1")},
                    _FakeNetmiko({}),
                    {"follow_neighbors": True, "permitted_prefixes": ["10.1.0.0/16"]},
                )

    async def test_seeds_are_still_visited_when_following_is_not_allowed(self) -> None:
        netmiko = _FakeNetmiko({"10.1.0.1": _cdp(_row("B", "10.1.0.2"))})
        with patch(f"{MODULE}.settings", MagicMock(discover_network_follow_enabled=False)):
            outcomes = await self._run({"d1": _device("d1", "A", "10.1.0.1")}, netmiko)
        self.assertEqual(list(self._devices(outcomes, "success")), ["d1"])

    async def test_a_followed_host_is_checked_again_right_before_the_login(self) -> None:
        # Defence in depth: the credential must never reach a host that fails the policy,
        # whatever the crawler decided.
        netmiko = _FakeNetmiko({})
        visit = _make_visit(
            netmiko=netmiko,
            pool=self.pool,
            credentials=("admin", "secret", "lab-ssh"),
            options=parse_options(
                {**get_config(), "follow_neighbors": True, "permitted_prefixes": ["10.1.0.0/16"]}
            ),
        )
        for host in ("172.16.0.9", "127.0.0.1", "169.254.169.254"):
            target = Target(
                name="x", host=host, device_type="cisco_ios", depth=1, discovered_from="A"
            )
            with self.assertRaises(VisitError) as ctx:
                await visit(target)
            self.assertEqual(ctx.exception.code, "out_of_scope")
        self.assertEqual(netmiko.hosts, [])
        self.pool.close_host.assert_not_awaited()

    async def test_a_seed_is_not_held_to_the_prefixes(self) -> None:
        netmiko = _FakeNetmiko({"192.168.99.1": _cdp()})
        outcomes = await self._run(
            {"d1": _device("d1", "A", "192.168.99.1")},
            netmiko,
            {"follow_neighbors": True, "permitted_prefixes": ["10.1.0.0/16"]},
        )
        self.assertEqual(list(self._devices(outcomes, "success")), ["d1"])

    @staticmethod
    def _failed_seed_code(outcomes: list[Any]) -> str:
        return (
            next(iter(DiscoverNetworkExecutorTests._devices(outcomes, "failure").values()))
            .errors[0]
            .code
        )

    async def test_seed_cdp_problems_keep_their_own_code_and_status(self) -> None:
        cases = {
            "% CDP is not enabled\n": ("cdp_not_enabled", "not_enabled"),
            "% Invalid input detected at '^' marker.\n": ("cdp_not_supported", "not_supported"),
            "": ("cdp_no_output", "unparseable"),
        }
        for raw, (code, status) in cases.items():
            with self.subTest(status=status):
                outcomes = await self._run(
                    {"d1": _device("d1", "A", "10.1.0.1")}, _FakeNetmiko({"10.1.0.1": raw})
                )
                device = self._devices(outcomes, "failure")["d1"]
                self.assertEqual(device.errors[0].code, code)
                self.assertEqual(device.status, DeviceStatus.FAILED)
                self.assertEqual(device.parsed["disc-1"]["discovery"]["cdp_status"], status)

    async def test_the_failure_outcome_carries_the_crawl_record_too(self) -> None:
        netmiko = _FakeNetmiko({"10.1.0.1": "% CDP is not enabled\n", "10.1.0.9": _cdp()})
        outcomes = await self._run(
            {"d1": _device("d1", "A", "10.1.0.1"), "d2": _device("d2", "S2", "10.1.0.9")}, netmiko
        )
        failure = next(o for o in outcomes if o.name == "failure")
        success = next(o for o in outcomes if o.name == "success")
        self.assertIn("disc-1.discovery", failure.context.metadata)
        self.assertEqual(
            failure.context.metadata["disc-1.discovery"],
            success.context.metadata["disc-1.discovery"],
        )

    async def test_credential_comes_from_a_run_parameter(self) -> None:
        netmiko = _FakeNetmiko({"10.1.0.1": _cdp()})
        with patch(f"{MODULE}.resolve_ssh_credential", return_value=("u", "p")) as resolve:
            await self._run(
                {"d1": _device("d1", "A", "10.1.0.1")},
                netmiko,
                {"credential_source": "run_param", "credential_param": "cred"},
                run_inputs={"cred": "param-ssh"},
            )
        self.assertEqual(resolve.call_args.args[1], "param-ssh")


if __name__ == "__main__":
    unittest.main()
