"""Executor of the collect-client-data step, against a scripted Netmiko and in-memory SQLite."""

from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import Table, create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.models.base import Base
from core.models.client_data import (
    ClientDataCollection,
    ClientHostname,
    ClientIpAddress,
    ClientMacAddress,
    ClientPortNeighbor,
)
from models.failure import FailureInfo
from models.workflow_context import DeviceContext, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.network.netmiko.connection import CommandResult as NetmikoCommandResult
from workflow_steps.collect_client_data.collector import collect_from_device
from workflow_steps.collect_client_data.config import get_config
from workflow_steps.collect_client_data.executor import execute

MODULE = "workflow_steps.collect_client_data.executor"
REFUSAL = "                ^\n% Invalid input detected at '^' marker.\n"
TABLES = [
    ClientIpAddress.__table__,
    ClientMacAddress.__table__,
    ClientHostname.__table__,
    ClientPortNeighbor.__table__,
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
MANY_MACS = {
    "show ip arp": "Protocol  Address          Age (min)  Hardware Addr   Type   Interface\n",
    "show mac address-table": _json(
        *(
            {
                "destination_address": f"aabb.ccdd.{n:04x}",
                "vlan_id": "10",
                "destination_port": ["Gi1/0/5"],
                "type": "DYNAMIC",
            }
            for n in range(3)
        )
    ),
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


LLDP_ROWS = _json(
    {
        "local_interface": "Gi1/0/47",
        "neighbor_name": "core1",
        "neighbor_interface": "TenGigabitEthernet1/1/1",
        "capabilities": "B,R",
    },
    {"local_interface": "Gi1/0/7", "neighbor_name": "phone-7", "capabilities": "T"},
)
SW_NEIGHBORS = {
    **ACC1,
    "show lldp neighbors detail": LLDP_ROWS,
    "show cdp neighbors detail": "% CDP is not enabled\n",
    "show etherchannel summary": _json(
        {"group": "1", "bundle_name": "Po1", "member_interface": ["Gi1/0/47", "Gi1/0/48"]}
    ),
}
NEIGHBORS_ON = {"collect_neighbors": True, "collect_vrfs": False}


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

    async def test_each_vrf_is_recorded_with_its_own_status_and_row_count(self) -> None:
        script = {
            "show vrf": _json({"name": "A"}, {"name": "B"}, {"name": "C"}, {"name": "D"}),
            "show ip arp": _json(_arp("10.0.10.5", "aabb.ccdd.0001", "Vlan10")),
            "show ip arp vrf A": _json(_arp("10.0.20.7", "aabb.ccdd.0002", "Vlan20")),
            # B: header only (an empty VRF); C: refused (not scripted); D: banner text
            "show ip arp vrf B": "Protocol  Address  Age (min)  Hardware Addr   Type   Interface\n",
            "show ip arp vrf D": "Connection closed by remote host",
        }
        netmiko = _FakeNetmiko({"10.0.0.1": script})

        outcomes = await self._run({"d1": _device("d1", "core1", "10.0.0.1")}, netmiko)

        collection = self._all(ClientDataCollection)[0]
        self.assertEqual(
            collection.vrfs,
            [
                {"name": "A", "status": "ok", "rows": 1},
                {"name": "B", "status": "ok", "rows": 0},
                {"name": "C", "status": "not_supported", "rows": 0},
                {"name": "D", "status": "no_template", "rows": 0},
            ],
        )
        self.assertEqual(collection.vrf_count, 4)
        summary = self._by_name(outcomes, "success")["d1"].parsed["collect-1"]["client_data"]
        self.assertEqual(summary["vrf_results"], collection.vrfs)

    async def test_vrfs_are_unknown_when_discovery_did_not_run_or_found_none(self) -> None:
        outcomes = await self._run(
            {"d1": _device("d1", "core1", "10.0.0.1")},
            _FakeNetmiko({"10.0.0.1": CORE1}),
            config={"collect_vrfs": False},
        )
        summary = self._by_name(outcomes, "success")["d1"].parsed["collect-1"]["client_data"]
        self.assertIsNone(summary["vrf_results"])
        await self._run(
            {"d2": _device("d2", "acc1", "10.0.0.2")},
            _FakeNetmiko({"10.0.0.2": ACC1}),
            run_uuid="run-uuid-2",
        )

        by_run = {c.session_id: c.vrfs for c in self._all(ClientDataCollection)}
        self.assertIsNone(by_run["run-uuid-1"])  # not asked: unknown
        self.assertIsNone(by_run["run-uuid-2"])  # `show vrf` refused: unknown

    async def test_vrf_found_but_default_arp_unusable_is_recorded_as_skipped(self) -> None:
        script = {
            "show vrf": _json({"name": "CUST"}),
            "show ip arp": REFUSAL,
            "show mac address-table": ACC1["show mac address-table"],
        }
        await self._run(
            {"d1": _device("d1", "core1", "10.0.0.1")}, _FakeNetmiko({"10.0.0.1": script})
        )

        (collection,) = self._all(ClientDataCollection)
        self.assertEqual(collection.vrfs, [{"name": "CUST", "status": "skipped", "rows": 0}])

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
                "neighbor_status": "skipped",
                "neighbor_entries": 0,
                "arp_entries": 2,
                "mac_entries": 0,
                "hostnames": 0,
                "vrfs": ["CUST"],
                "vrf_results": [{"name": "CUST", "status": "ok", "rows": 1}],
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

    async def test_a_table_above_the_row_cap_fails_the_device_before_dns_and_stores_nothing(
        self,
    ) -> None:
        resolver = AsyncMock()
        with (
            patch.object(settings, "client_data_max_rows_per_table", 1),
            patch(f"{MODULE}._hostnames", resolver),
        ):
            outcomes = await self._run(
                {"d1": _device("d1", "core1", "10.0.0.1")},
                _FakeNetmiko({"10.0.0.1": CORE1}),
                config={"collect_hostname": True},
            )

        failed = self._by_name(outcomes, "failure")["d1"]
        error = failed.errors[-1]
        self.assertEqual(error.code, "too_many_rows")
        self.assertEqual(
            (error.failure.phase, error.failure.kind), ("command", "payload_too_large")
        )
        self.assertIn("CLIENT_DATA_MAX_ROWS_PER_TABLE", error.message)
        resolver.assert_not_awaited()
        self.assertEqual(self._all(ClientDataCollection), [])
        self.assertEqual(self._all(ClientIpAddress), [])

    async def test_a_table_exactly_at_the_row_cap_is_stored(self) -> None:
        with patch.object(settings, "client_data_max_rows_per_table", 2):  # CORE1 has 2 ARP rows
            outcomes = await self._run(
                {"d1": _device("d1", "core1", "10.0.0.1")}, _FakeNetmiko({"10.0.0.1": CORE1})
            )

        self.assertEqual(list(self._by_name(outcomes, "success")), ["d1"])
        self.assertEqual(len(self._all(ClientIpAddress)), 2)

    async def test_the_mac_table_has_its_own_row_cap(self) -> None:
        with patch.object(settings, "client_data_max_rows_per_table", 0 + 1):
            outcomes = await self._run(
                {"d2": _device("d2", "acc1", "10.0.0.2")}, _FakeNetmiko({"10.0.0.2": MANY_MACS})
            )

        error = self._by_name(outcomes, "failure")["d2"].errors[-1]
        self.assertEqual(error.code, "too_many_rows")
        self.assertIn("MAC", error.message)

    async def test_the_storage_layer_refuses_too_many_rows_even_if_the_collector_let_them_by(
        self,
    ) -> None:
        real = collect_from_device

        async def unbounded(**kwargs: Any):
            return await real(**{**kwargs, "max_rows": 10**9})

        with (
            patch.object(settings, "client_data_max_rows_per_table", 1),
            patch(f"{MODULE}.collect_from_device", unbounded),
        ):
            outcomes = await self._run(
                {"d1": _device("d1", "core1", "10.0.0.1")}, _FakeNetmiko({"10.0.0.1": CORE1})
            )

        self.assertEqual(self._by_name(outcomes, "failure")["d1"].errors[-1].code, "too_many_rows")
        self.assertEqual(self._all(ClientDataCollection), [])

    async def test_a_conflicting_write_of_the_same_device_name_fails_as_duplicate_key(self) -> None:
        from models.client_data import CollectionConflictError

        with patch(
            "repositories.client_data_repository.ClientDataRepository.replace_device_collection",
            side_effect=CollectionConflictError(),
        ):
            outcomes = await self._run(
                {"d1": _device("d1", "core1", "10.0.0.1")}, _FakeNetmiko({"10.0.0.1": CORE1})
            )

        error = self._by_name(outcomes, "failure")["d1"].errors[-1]
        self.assertEqual(error.code, "duplicate_key")
        self.assertIn("stored per device name", error.message)
        self.assertEqual((error.failure.phase, error.failure.kind), ("internal", "ambiguous_match"))

    async def test_neighbours_are_not_collected_unless_switched_on(self) -> None:
        netmiko = _FakeNetmiko({"10.0.0.2": SW_NEIGHBORS})

        await self._run({"d2": _device("d2", "acc1", "10.0.0.2")}, netmiko)

        self.assertEqual(self._all(ClientPortNeighbor), [])
        (collection,) = self._all(ClientDataCollection)
        self.assertEqual((collection.neighbor_status, collection.neighbor_rows), ("skipped", 0))
        self.assertTrue(
            all("lldp" not in c and "cdp" not in c for _, cs in netmiko.calls for c in cs)
        )

    async def test_lldp_neighbours_are_stored_with_their_port_channel(self) -> None:
        netmiko = _FakeNetmiko({"10.0.0.2": SW_NEIGHBORS})

        outcomes = await self._run(
            {"d2": _device("d2", "acc1", "10.0.0.2")}, netmiko, config=NEIGHBORS_ON
        )

        self.assertEqual(list(self._by_name(outcomes, "success")), ["d2"])
        rows = {r.port: r for r in self._all(ClientPortNeighbor)}
        self.assertEqual(set(rows), {"Gi1/0/47", "Gi1/0/7"})
        uplink = rows["Gi1/0/47"]
        self.assertEqual(
            (uplink.neighbor_name, uplink.channel, uplink.protocol, uplink.is_infrastructure),
            ("core1", "Po1", "lldp", True),
        )
        self.assertEqual(uplink.capabilities, "bridge,router")
        self.assertEqual(
            (rows["Gi1/0/7"].channel, rows["Gi1/0/7"].is_infrastructure), (None, False)
        )
        (collection,) = self._all(ClientDataCollection)
        self.assertEqual((collection.neighbor_status, collection.neighbor_rows), ("ok", 2))
        # One batch for the tables and the neighbour commands.
        self.assertEqual(
            netmiko.calls[0][1],
            [
                "show ip arp",
                "show mac address-table",
                "show lldp neighbors detail",
                "show cdp neighbors detail",
                "show etherchannel summary",
            ],
        )

    async def test_nxos_uses_its_own_port_channel_command(self) -> None:
        netmiko = _FakeNetmiko({"10.0.0.2": ACC1})

        await self._run(
            {"d2": _device("d2", "acc1", "10.0.0.2", driver="cisco_nxos")},
            netmiko,
            config=NEIGHBORS_ON,
        )

        self.assertIn("show port-channel summary", netmiko.calls[0][1])
        self.assertNotIn("show etherchannel summary", netmiko.calls[0][1])

    async def test_cdp_rows_are_used_when_lldp_is_off(self) -> None:
        script = {
            **SW_NEIGHBORS,
            "show lldp neighbors detail": "% LLDP is not enabled\n",
            "show cdp neighbors detail": _json(
                {
                    "local_interface": "GigabitEthernet1/0/48",
                    "neighbor_name": "core2",
                    "neighbor_interface": "Te1/1/2",
                    "capabilities": "Router Switch IGMP",
                }
            ),
        }

        await self._run(
            {"d2": _device("d2", "acc1", "10.0.0.2")},
            _FakeNetmiko({"10.0.0.2": script}),
            config=NEIGHBORS_ON,
        )

        (row,) = self._all(ClientPortNeighbor)
        self.assertEqual((row.port, row.channel, row.protocol), ("Gi1/0/48", "Po1", "cdp"))
        self.assertEqual(self._all(ClientDataCollection)[0].neighbor_status, "ok")

    async def test_both_protocols_off_is_not_supported_and_the_device_still_succeeds(self) -> None:
        script = {
            **ACC1,
            "show lldp neighbors detail": "% LLDP is not enabled\n",
            "show cdp neighbors detail": "% CDP is not enabled\n",
        }

        outcomes = await self._run(
            {"d2": _device("d2", "acc1", "10.0.0.2")},
            _FakeNetmiko({"10.0.0.2": script}),
            config=NEIGHBORS_ON,
        )

        self.assertEqual(list(self._by_name(outcomes, "success")), ["d2"])
        (collection,) = self._all(ClientDataCollection)
        self.assertEqual(
            (collection.neighbor_status, collection.neighbor_rows), ("not_supported", 0)
        )
        self.assertEqual(len(self._all(ClientMacAddress)), 1)  # the other tables are intact

    async def test_neighbour_output_that_is_not_a_table_never_fails_the_device_or_stores_rows(
        self,
    ) -> None:
        script = {**SW_NEIGHBORS, "show cdp neighbors detail": "Connection closed by remote host"}

        outcomes = await self._run(
            {"d2": _device("d2", "acc1", "10.0.0.2")},
            _FakeNetmiko({"10.0.0.2": script}),
            config=NEIGHBORS_ON,
        )

        self.assertEqual(list(self._by_name(outcomes, "success")), ["d2"])
        self.assertEqual(self._all(ClientPortNeighbor), [])  # an untrusted answer stores nothing
        (collection,) = self._all(ClientDataCollection)
        self.assertEqual((collection.neighbor_status, collection.neighbor_rows), ("no_template", 0))
        self.assertEqual(len(self._all(ClientMacAddress)), 1)

    async def test_a_missing_port_channel_table_only_loses_the_channel(self) -> None:
        script = {**SW_NEIGHBORS, "show etherchannel summary": REFUSAL}

        await self._run(
            {"d2": _device("d2", "acc1", "10.0.0.2")},
            _FakeNetmiko({"10.0.0.2": script}),
            config=NEIGHBORS_ON,
        )

        rows = {r.port: r.channel for r in self._all(ClientPortNeighbor)}
        self.assertEqual(rows, {"Gi1/0/47": None, "Gi1/0/7": None})
        self.assertEqual(self._all(ClientDataCollection)[0].neighbor_status, "ok")

    async def test_the_summary_and_the_dry_run_name_the_neighbour_commands(self) -> None:
        outcomes = await self._run(
            {"d2": _device("d2", "acc1", "10.0.0.2")},
            _FakeNetmiko({"10.0.0.2": SW_NEIGHBORS}),
            config=NEIGHBORS_ON,
        )
        summary = self._by_name(outcomes, "success")["d2"].parsed["collect-1"]["client_data"]
        self.assertEqual((summary["neighbor_status"], summary["neighbor_entries"]), ("ok", 2))

        preview = await self._run(
            {"d2": _device("d2", "acc1", "10.0.0.2")},
            _FakeNetmiko({}),
            config={**NEIGHBORS_ON, "dry_run": True},
            run_uuid="run-dry",
        )
        dry = self._by_name(preview, "success")["d2"].dry_run_results["collect-1"]
        self.assertIn("show lldp neighbors detail", dry["commands"])
        self.assertIn("show etherchannel summary", dry["commands"])

    async def test_the_row_cap_covers_the_neighbour_table(self) -> None:
        resolver = AsyncMock()
        with (
            patch.object(settings, "client_data_max_rows_per_table", 2),  # ARP/MAC fit: 1 each
            patch(f"{MODULE}._hostnames", resolver),
        ):
            outcomes = await self._run(
                {"d2": _device("d2", "acc1", "10.0.0.2")},
                _FakeNetmiko(
                    {
                        "10.0.0.2": {
                            **SW_NEIGHBORS,
                            "show lldp neighbors detail": _json(
                                *(
                                    {
                                        "local_interface": f"Gi1/0/{n}",
                                        "neighbor_name": f"n{n}",
                                        "capabilities": "B",
                                    }
                                    for n in range(1, 4)
                                )
                            ),
                        }
                    }
                ),
                config={**NEIGHBORS_ON, "collect_hostname": True},
            )

        error = self._by_name(outcomes, "failure")["d2"].errors[-1]
        self.assertEqual(error.code, "too_many_rows")
        self.assertIn("neighbour", error.message)
        resolver.assert_not_awaited()  # refused by the collector, before DNS and storage
        self.assertEqual(self._all(ClientPortNeighbor), [])

    async def test_neighbours_alone_are_enough_when_other_tables_are_off(self) -> None:
        netmiko = _FakeNetmiko({"10.0.0.2": SW_NEIGHBORS})

        outcomes = await self._run(
            {"d2": _device("d2", "acc1", "10.0.0.2")},
            netmiko,
            config={**NEIGHBORS_ON, "collect_ip_address": False, "collect_mac_address": False},
        )

        self.assertEqual(list(self._by_name(outcomes, "success")), ["d2"])
        self.assertEqual(len(self._all(ClientPortNeighbor)), 2)

    async def test_a_default_arp_table_over_the_cap_stops_before_any_vrf_is_read(self) -> None:
        script = {
            "show vrf": _json({"name": "A"}, {"name": "B"}),
            "show ip arp": _json(
                _arp("10.0.10.5", "aabb.ccdd.0001", "Vlan10"),
                _arp("10.0.10.6", "aabb.ccdd.0002", "Vlan10"),
            ),
        }
        netmiko = _FakeNetmiko({"10.0.0.1": script})

        with patch.object(settings, "client_data_max_rows_per_table", 1):
            outcomes = await self._run({"d1": _device("d1", "core1", "10.0.0.1")}, netmiko)

        self.assertEqual(self._by_name(outcomes, "failure")["d1"].errors[-1].code, "too_many_rows")
        self.assertEqual(len(netmiko.calls), 1)  # phase one only: no per-VRF round trip

    async def test_a_mac_table_over_the_cap_stops_before_any_vrf_is_read(self) -> None:
        script = {**MANY_MACS, "show vrf": _json({"name": "A"})}
        script["show ip arp"] = _json(_arp("10.0.10.5", "aabb.ccdd.0001", "Vlan10"))
        netmiko = _FakeNetmiko({"10.0.0.2": script})

        with patch.object(settings, "client_data_max_rows_per_table", 1):
            outcomes = await self._run({"d2": _device("d2", "acc1", "10.0.0.2")}, netmiko)

        self.assertEqual(self._by_name(outcomes, "failure")["d2"].errors[-1].code, "too_many_rows")
        self.assertEqual(len(netmiko.calls), 1)

    async def test_vrf_tables_are_read_one_at_a_time_and_reading_stops_at_the_cap(self) -> None:
        script = {
            "show vrf": _json({"name": "A"}, {"name": "B"}, {"name": "C"}),
            "show ip arp": _json(_arp("10.0.10.5", "aabb.ccdd.0001", "Vlan10")),
            "show ip arp vrf A": _json(_arp("10.0.20.7", "aabb.ccdd.0002", "Vlan20")),
            "show ip arp vrf B": _json(_arp("10.0.30.7", "aabb.ccdd.0003", "Vlan30")),
            "show ip arp vrf C": _json(_arp("10.0.40.7", "aabb.ccdd.0004", "Vlan40")),
        }
        netmiko = _FakeNetmiko({"10.0.0.1": script})

        with patch.object(settings, "client_data_max_rows_per_table", 2):
            outcomes = await self._run({"d1": _device("d1", "core1", "10.0.0.1")}, netmiko)

        # 1 default + 1 in A = 2 (at the cap); B pushes the total to 3, so C is never requested.
        self.assertEqual(self._by_name(outcomes, "failure")["d1"].errors[-1].code, "too_many_rows")
        self.assertEqual(
            [commands for _, commands in netmiko.calls[1:]],
            [["show ip arp vrf A"], ["show ip arp vrf B"]],
        )
        self.assertEqual(self._all(ClientDataCollection), [])

    async def test_a_raw_table_over_the_cap_is_refused_before_it_is_parsed(self) -> None:
        with (
            patch.object(settings, "client_data_max_rows_per_table", 1),
            patch(
                "workflow_steps.collect_client_data.collector.parse_arp",
                side_effect=AssertionError("parsed an oversized table"),
            ),
        ):
            outcomes = await self._run(
                {"d1": _device("d1", "core1", "10.0.0.1")},
                _FakeNetmiko(
                    {
                        "10.0.0.1": {
                            "show ip arp": _json(
                                _arp("10.0.10.5", "aabb.ccdd.0001", "Vlan10"),
                                _arp("10.0.10.6", "aabb.ccdd.0002", "Vlan10"),
                            )
                        }
                    }
                ),
                config={"collect_vrfs": False, "collect_mac_address": False},
            )

        self.assertEqual(self._by_name(outcomes, "failure")["d1"].errors[-1].code, "too_many_rows")

    async def test_a_later_execution_with_the_same_device_name_fails_and_keeps_the_first(
        self,
    ) -> None:
        first = await self._run(
            {"d1": _device("d1", "core1", "10.0.0.1")}, _FakeNetmiko({"10.0.0.1": CORE1})
        )
        second = await self._run(
            {"d9": _device("d9", "core1", "10.0.0.9")}, _FakeNetmiko({"10.0.0.9": CORE1})
        )

        self.assertEqual(list(self._by_name(first, "success")), ["d1"])
        error = self._by_name(second, "failure")["d9"].errors[-1]
        self.assertEqual(error.code, "duplicate_key")
        self.assertIn("this run", error.message)
        self.assertEqual({r.device_ip for r in self._all(ClientIpAddress)}, {"10.0.0.1"})
        (collection,) = self._all(ClientDataCollection)
        self.assertEqual(collection.target_host, "10.0.0.1")

    async def test_rerunning_the_same_device_in_the_same_run_still_replaces(self) -> None:
        for _ in range(2):
            outcomes = await self._run(
                {"d1": _device("d1", "core1", "10.0.0.1")}, _FakeNetmiko({"10.0.0.1": CORE1})
            )
            self.assertEqual(list(self._by_name(outcomes, "success")), ["d1"])

        self.assertEqual(len(self._all(ClientDataCollection)), 1)
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
