"""Executor of the collect-client-data step, against a scripted Netmiko and in-memory SQLite."""

from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from sqlalchemy import Table, create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.models.base import Base
from core.models.client_data import (
    ClientDataCollection,
    ClientHostname,
    ClientIpAddress,
    ClientMacAddress,
)
from models.failure import FailureInfo
from models.workflow_context import DeviceContext, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.network.netmiko.connection import CommandResult as NetmikoCommandResult
from workflow_steps.collect_client_data.config import get_config
from workflow_steps.collect_client_data.executor import execute

MODULE = "workflow_steps.collect_client_data.executor"
REFUSAL = "                ^\n% Invalid input detected at '^' marker.\n"
TABLES = [
    ClientIpAddress.__table__,
    ClientMacAddress.__table__,
    ClientHostname.__table__,
    ClientDataCollection.__table__,
]


def _json(*rows: dict[str, Any]) -> str:
    return json.dumps(list(rows))


def _arp(ip: str, mac: str, interface: str) -> dict[str, str]:
    return {"ip_address": ip, "mac_address": mac, "interface": interface}


# Scripted device output. A command that is not scripted is refused, like a real CLI would.
CORE1 = {
    "show vrf": _json({"name": "default"}, {"name": "CUST"}),
    "show ip arp": _json(_arp("10.0.10.5", "aabb.ccdd.0001", "Vlan10")),
    "show ip arp vrf CUST": _json(_arp("10.0.20.7", "AABB.CCDD.0002", "Vlan20")),
}
ACC1 = {
    "show ip arp": "Protocol  Address          Age (min)  Hardware Addr   Type   Interface\n",
    "show mac address-table": _json(
        {
            "destination_address": "aabb.ccdd.0001",
            "vlan_id": "10",
            "destination_port": ["Gi1/0/5"],
            "type": "DYNAMIC",
        }
    ),
}


class _FakeNetmiko:
    def __init__(self, scripts: dict[str, dict[str, str]], failing: dict[str, Any] | None = None):
        self.scripts = scripts
        self.failing = failing or {}
        self.calls: list[tuple[str, list[str]]] = []

    async def send_commands(self, *, host: str, commands: list[str], **kwargs: Any):
        self.calls.append((host, list(commands)))
        failing = self.failing.get(host)
        if failing is not None and (failing["when"] is None or failing["when"] in commands):
            return failing["result"]
        outputs = {c: self.scripts.get(host, {}).get(c, REFUSAL) for c in commands}
        return NetmikoCommandResult(success=True, output="", command_outputs=outputs)


def _device(device_id: str, name: str, ip: str, driver: str = "cisco_ios") -> DeviceContext:
    return DeviceContext(
        id=device_id, name=name, hostname=name, primary_ip4=f"{ip}/24", network_driver=driver
    )


class CollectClientDataExecutorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine, tables=[t for t in TABLES if isinstance(t, Table)])
        self.addCleanup(engine.dispose)
        self.Session = sessionmaker(bind=engine)
        for target, value in (
            (f"{MODULE}.get_db_session", {"side_effect": lambda: self.Session()}),
            (f"{MODULE}.object_session", {"return_value": MagicMock()}),
            (
                f"{MODULE}.resolve_ssh_credential",
                {"return_value": ("admin", "secret")},
            ),
        ):
            patcher = patch(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def _run(
        self,
        devices: dict[str, DeviceContext],
        netmiko: _FakeNetmiko,
        *,
        config: dict[str, Any] | None = None,
        run_uuid: str = "run-uuid-1",
    ):
        run = MagicMock()
        run.uuid = run_uuid
        run.id = 1
        run.run_inputs = {}
        run.triggered_by_id = 1
        merged = {**get_config(), "credential_reference": "lab-ssh", **(config or {})}
        with patch(f"{MODULE}.NetmikoService", return_value=netmiko):
            return await execute(
                config=merged,
                context=WorkflowContext(run_id="wf-run-1", workflow_id="wf-1", devices=devices),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="collect-1",
                device_sessions=MagicMock(),
            )

    def _all(self, model: type) -> list[Any]:
        with self.Session() as db:
            return list(db.scalars(select(model)))

    @staticmethod
    def _by_name(outcomes: list[Any], name: str) -> dict[str, DeviceContext]:
        for outcome in outcomes:
            if outcome.name == name:
                return outcome.context.devices
        return {}

    async def test_l3_device_with_vrf_stores_arp_per_vrf_and_marks_mac_unsupported(self) -> None:
        netmiko = _FakeNetmiko({"10.0.0.1": CORE1})

        outcomes = await self._run({"d1": _device("d1", "core1", "10.0.0.1")}, netmiko)

        self.assertEqual(list(self._by_name(outcomes, "success")), ["d1"])
        self.assertEqual(self._by_name(outcomes, "failure"), {})
        rows = {(r.ip_address, r.vrf, r.vlan, r.interface) for r in self._all(ClientIpAddress)}
        self.assertEqual(
            rows,
            {
                ("10.0.10.5", None, "10", "Vlan10"),
                ("10.0.20.7", "CUST", "20", "Vlan20"),
            },
        )
        macs = {r.mac_address for r in self._all(ClientIpAddress)}
        self.assertEqual(macs, {"aabb.ccdd.0001", "aabb.ccdd.0002"})  # normalised
        collection = self._all(ClientDataCollection)[0]
        self.assertEqual(
            (collection.arp_status, collection.mac_status, collection.vrf_status),
            ("ok", "not_supported", "ok"),
        )
        self.assertEqual((collection.vrf_count, collection.arp_rows), (1, 2))
        self.assertEqual(collection.session_id, "run-uuid-1")
        # Phase 1 sends all three commands, phase 2 only the per-VRF ARP.
        self.assertEqual(
            netmiko.calls,
            [
                ("10.0.0.1", ["show vrf", "show ip arp", "show mac address-table"]),
                ("10.0.0.1", ["show ip arp vrf CUST"]),
            ],
        )

    async def test_l2_device_without_vrf_support_stores_mac_table(self) -> None:
        netmiko = _FakeNetmiko({"10.0.0.2": ACC1})

        outcomes = await self._run({"d2": _device("d2", "acc1", "10.0.0.2")}, netmiko)

        self.assertEqual(list(self._by_name(outcomes, "success")), ["d2"])
        (mac,) = self._all(ClientMacAddress)
        self.assertEqual((mac.mac_address, mac.vlan, mac.port), ("aabb.ccdd.0001", "10", "Gi1/0/5"))
        collection = self._all(ClientDataCollection)[0]
        self.assertEqual(
            (collection.arp_status, collection.mac_status, collection.vrf_status),
            ("ok", "ok", "not_supported"),
        )
        self.assertEqual(len(netmiko.calls), 1)  # no VRFs found -> no second round trip

    async def test_summary_is_written_to_the_device_parsed_data(self) -> None:
        outcomes = await self._run(
            {"d1": _device("d1", "core1", "10.0.0.1")}, _FakeNetmiko({"10.0.0.1": CORE1})
        )

        summary = self._by_name(outcomes, "success")["d1"].parsed["collect-1"]["client_data"]
        self.assertEqual(
            summary,
            {
                "arp_status": "ok",
                "mac_status": "not_supported",
                "vrf_status": "ok",
                "arp_entries": 2,
                "mac_entries": 0,
                "hostnames": 0,
                "vrfs": ["CUST"],
            },
        )

    async def test_success_devices_satisfy_the_runner_produces_guard(self) -> None:
        from models.workflow_context import Capability
        from services.workflow_context.guards import StepCapabilitySpec, post_step_guard

        for dry_run in (False, True):
            devices = {"d1": _device("d1", "core1", "10.0.0.1")}
            outcomes = await self._run(
                devices, _FakeNetmiko({"10.0.0.1": CORE1}), config={"dry_run": dry_run}
            )
            device = self._by_name(outcomes, "success")["d1"]
            self.assertIn(Capability.PARSED, device.capabilities)
            post_step_guard(
                spec=StepCapabilitySpec(
                    step_id="collect-client-data", produces=frozenset({Capability.PARSED})
                ),
                input_context=WorkflowContext(run_id="r", workflow_id="w", devices=devices),
                outcomes=outcomes,
            )

    async def test_connection_failure_fails_the_device_and_stores_nothing(self) -> None:
        failure = FailureInfo(phase="connect", kind="timeout", retryable=True)
        netmiko = _FakeNetmiko(
            {},
            failing={
                "10.0.0.3": {
                    "when": None,
                    "result": NetmikoCommandResult(
                        success=False, error="timed out", failure=failure
                    ),
                }
            },
        )

        outcomes = await self._run({"d3": _device("d3", "down1", "10.0.0.3")}, netmiko)

        failed = self._by_name(outcomes, "failure")["d3"]
        self.assertEqual(failed.errors[-1].failure, failure)
        self.assertEqual(self._all(ClientDataCollection), [])

    async def test_failure_while_collecting_a_vrf_fails_the_device(self) -> None:
        netmiko = _FakeNetmiko(
            {"10.0.0.1": CORE1},
            failing={
                "10.0.0.1": {
                    "when": "show ip arp vrf CUST",
                    "result": NetmikoCommandResult(success=False, error="session lost"),
                }
            },
        )

        outcomes = await self._run({"d1": _device("d1", "core1", "10.0.0.1")}, netmiko)

        self.assertEqual(list(self._by_name(outcomes, "failure")), ["d1"])
        self.assertEqual(self._all(ClientIpAddress), [])

    async def test_a_device_where_every_command_is_refused_fails(self) -> None:
        outcomes = await self._run(
            {"d4": _device("d4", "odd1", "10.0.0.4")}, _FakeNetmiko({"10.0.0.4": {}})
        )

        failed = self._by_name(outcomes, "failure")["d4"]
        self.assertEqual(failed.errors[-1].code, "nothing_collected")
        self.assertEqual(self._all(ClientDataCollection), [])

    async def test_unrecognised_output_fails_and_keeps_the_older_data(self) -> None:
        devices = {"d1": _device("d1", "core1", "10.0.0.1")}
        await self._run(devices, _FakeNetmiko({"10.0.0.1": CORE1}), run_uuid="run-a")
        garbled = {**CORE1, "show ip arp": "Connection closed by foreign host\n"}

        outcomes = await self._run(devices, _FakeNetmiko({"10.0.0.1": garbled}), run_uuid="run-b")

        failed = self._by_name(outcomes, "failure")["d1"]
        self.assertEqual(failed.errors[-1].code, "unparsable_output")
        self.assertEqual({c.session_id for c in self._all(ClientDataCollection)}, {"run-a"})
        self.assertEqual(len(self._all(ClientIpAddress)), 2)

    async def test_unsupported_platform_fails_without_connecting(self) -> None:
        netmiko = _FakeNetmiko({})

        outcomes = await self._run(
            {"d5": _device("d5", "eos1", "10.0.0.5", driver="arista_eos")}, netmiko
        )

        failed = self._by_name(outcomes, "failure")["d5"]
        self.assertEqual(failed.errors[-1].code, "unsupported_platform")
        self.assertEqual(netmiko.calls, [])

    async def test_device_without_a_host_fails(self) -> None:
        device = DeviceContext(id="d6", name="nohost", hostname="", network_driver="cisco_ios")

        outcomes = await self._run({"d6": device}, _FakeNetmiko({}))

        self.assertEqual(self._by_name(outcomes, "failure")["d6"].errors[-1].code, "missing_host")

    async def test_a_long_hostname_target_does_not_break_the_save(self) -> None:
        host = "core-switch-01." + "building-a." * 5 + "example.net"  # longer than varchar(45)
        device = DeviceContext(
            id="d8", name="core8", hostname=host, network_driver="cisco_ios", primary_ip4=None
        )

        outcomes = await self._run({"d8": device}, _FakeNetmiko({host: CORE1}))

        self.assertEqual(list(self._by_name(outcomes, "success")), ["d8"])
        self.assertTrue(all(c.device_ip is None for c in self._all(ClientIpAddress)))

    async def test_an_ip_target_is_kept_as_device_ip(self) -> None:
        await self._run(
            {"d1": _device("d1", "core1", "10.0.0.1")}, _FakeNetmiko({"10.0.0.1": CORE1})
        )

        self.assertEqual({c.device_ip for c in self._all(ClientIpAddress)}, {"10.0.0.1"})

    async def test_second_device_with_the_same_name_fails(self) -> None:
        netmiko = _FakeNetmiko({"10.0.0.1": CORE1, "10.0.0.9": CORE1})

        outcomes = await self._run(
            {
                "d1": _device("d1", "core1", "10.0.0.1"),
                "d9": _device("d9", "core1", "10.0.0.9"),
            },
            netmiko,
        )

        self.assertEqual(list(self._by_name(outcomes, "success")), ["d1"])
        self.assertEqual(self._by_name(outcomes, "failure")["d9"].errors[-1].code, "duplicate_key")

    async def test_dry_run_neither_connects_nor_stores(self) -> None:
        netmiko = _FakeNetmiko({"10.0.0.1": CORE1})

        outcomes = await self._run(
            {"d1": _device("d1", "core1", "10.0.0.1")}, netmiko, config={"dry_run": True}
        )

        device = self._by_name(outcomes, "success")["d1"]
        self.assertIn("collect-1", device.dry_run_results)
        self.assertEqual(netmiko.calls, [])
        self.assertEqual(self._all(ClientDataCollection), [])

    async def test_running_the_step_again_in_the_same_run_replaces_the_rows(self) -> None:
        devices = {"d1": _device("d1", "core1", "10.0.0.1")}
        for _ in range(2):
            await self._run(devices, _FakeNetmiko({"10.0.0.1": CORE1}))

        self.assertEqual(len(self._all(ClientIpAddress)), 2)
        self.assertEqual(len(self._all(ClientDataCollection)), 1)

    async def test_a_new_run_adds_a_collection_per_device(self) -> None:
        devices = {"d1": _device("d1", "core1", "10.0.0.1")}
        await self._run(devices, _FakeNetmiko({"10.0.0.1": CORE1}), run_uuid="run-a")
        await self._run(devices, _FakeNetmiko({"10.0.0.1": CORE1}), run_uuid="run-b")

        sessions = {c.session_id for c in self._all(ClientDataCollection)}
        self.assertEqual(sessions, {"run-a", "run-b"})

    async def test_hostnames_are_resolved_once_per_ip_when_enabled(self) -> None:
        lookups: list[str] = []

        def reverse(ip: str) -> str | None:
            lookups.append(ip)
            return "pc1.example.net" if ip == "10.0.10.5" else None

        two_devices = {
            "d1": _device("d1", "core1", "10.0.0.1"),
            "d7": _device("d7", "core2", "10.0.0.7"),
        }
        netmiko = _FakeNetmiko({"10.0.0.1": CORE1, "10.0.0.7": CORE1})
        with patch(f"{MODULE}.reverse_lookup", reverse):
            await self._run(two_devices, netmiko, config={"collect_hostname": True})

        self.assertEqual(sorted(lookups), ["10.0.10.5", "10.0.20.7"])
        hostnames = self._all(ClientHostname)
        self.assertEqual(
            {(h.device_name, h.ip_address, h.hostname) for h in hostnames},
            {
                ("core1", "10.0.10.5", "pc1.example.net"),
                ("core2", "10.0.10.5", "pc1.example.net"),
            },
        )

    async def test_hostnames_are_not_resolved_by_default(self) -> None:
        with patch(f"{MODULE}.reverse_lookup", side_effect=AssertionError("no DNS")):
            await self._run(
                {"d1": _device("d1", "core1", "10.0.0.1")}, _FakeNetmiko({"10.0.0.1": CORE1})
            )

        self.assertEqual(self._all(ClientHostname), [])

    async def test_mac_and_vrf_collection_can_be_switched_off(self) -> None:
        netmiko = _FakeNetmiko({"10.0.0.1": CORE1})

        await self._run(
            {"d1": _device("d1", "core1", "10.0.0.1")},
            netmiko,
            config={"collect_mac_address": False, "collect_vrfs": False},
        )

        self.assertEqual(netmiko.calls, [("10.0.0.1", ["show ip arp"])])
        collection = self._all(ClientDataCollection)[0]
        self.assertEqual(
            (collection.mac_status, collection.vrf_status, collection.vrf_count),
            ("skipped", "skipped", 0),
        )

    async def test_no_devices_is_a_plain_success(self) -> None:
        outcomes = await self._run({}, _FakeNetmiko({}))

        self.assertEqual([o.name for o in outcomes], ["success"])


if __name__ == "__main__":
    unittest.main()
