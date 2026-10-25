"""Tests for the get-git-devices executor (mocked git layer)."""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from _git_helpers import checkout_of

from models.workflow_context import WorkflowContext
from workflow_steps.get_git_devices.config import get_config
from workflow_steps.get_git_devices.executor import execute

_MODULE = "workflow_steps.get_git_devices.executor"


async def _run(config: dict[str, Any], repo_dir: Path):
    run = MagicMock()
    run.id = 1
    with (
        patch(f"{_MODULE}.load_git_repository", return_value={"name": "r"}),
        patch("services.git.device_service.git_checkout", return_value=checkout_of(repo_dir)),
    ):
        return await execute(
            config={**get_config(), "git_repository_id": 3, **config},
            context=WorkflowContext(run_id="r", workflow_id="w"),
            run=run,
            artifact_service=MagicMock(),
            node_id="n1",
            device_sessions=MagicMock(),
        )


class GetGitDevicesExecutorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        (self.repo / "d.yaml").write_text(
            "devices:\n  - device_name: r1\n    mgmt: 10.0.0.1\n"
            "    site: City A\n    state: Active\n"
        )

    async def test_mapped_devices_land_in_context(self) -> None:
        mapping = [
            {"source": "device_name", "target": "name"},
            {"source": "mgmt", "target": "primary_ip4.address"},
            {"source": "site", "target": "location.name"},
            {"source": "state", "target": "status.name"},
        ]
        outcomes = await _run({"device_mapping": mapping}, self.repo)
        device = next(iter(outcomes[0].context.devices.values()))
        self.assertEqual(device.name, "r1")
        self.assertEqual(device.primary_ip4, "10.0.0.1")
        self.assertEqual(device.attribute_bags["nautobot"]["location"], {"name": "City A"})
        self.assertEqual(device.attribute_bags["nautobot"]["status"], {"name": "Active"})
        self.assertEqual(device.attribute_bags["git"]["site"], "City A")

    async def test_invalid_mapping_fails_step_with_clear_message(self) -> None:
        with self.assertRaisesRegex(ValueError, "get-git-devices: .*unknown target"):
            await _run(
                {
                    "device_mapping": [
                        {"source": "a", "target": "name"},
                        {"source": "b", "target": "x"},
                    ]
                },
                self.repo,
            )

    async def test_zero_devices_fails_with_reason(self) -> None:
        (self.repo / "d.yaml").write_text("devices:\n  - hostname: r1\n")
        with self.assertRaisesRegex(RuntimeError, "no devices found.*skipped"):
            await _run({}, self.repo)

    async def test_root_list_file_is_read(self) -> None:
        (self.repo / "d.yaml").write_text(
            "---\n- name: LAB\n  ip_address: 10.0.0.1/24\n  network_driver: cisco_ios\n"
        )
        mapping = [
            {"source": "name", "target": "name"},
            {"source": "ip_address", "target": "primary_ip4.address"},
            {"source": "network_driver", "target": "platform.network_driver"},
        ]
        outcomes = await _run({"device_mapping": mapping}, self.repo)
        device = next(iter(outcomes[0].context.devices.values()))
        self.assertEqual((device.name, device.primary_ip4), ("LAB", "10.0.0.1/24"))

    async def test_csv_multiline_with_interfaces_and_custom_fields(self) -> None:
        (self.repo / "d.yaml").unlink()
        (self.repo / "d.csv").write_text(
            "name;role;interface_name;interface_ip_address;cf_snmp_credentials\n"
            "LAB;Network;;;secret\n"
            "LAB;;Ethernet0/0;10.0.0.1/24;\n"
            "LAB;;Ethernet0/1;10.0.1.1/24;\n"
        )
        mapping = [
            {"source": "name", "target": "name"},
            {"source": "role", "target": "role.name"},
            {"source": "interface_name", "target": "interfaces.name"},
            {"source": "interface_ip_address", "target": "interfaces.ip_addresses.address"},
        ]
        outcomes = await _run(
            {
                "device_mapping": mapping,
                "file_format": "csv",
                "csv_multiline": True,
                "filename_pattern": "*.csv",
            },
            self.repo,
        )
        devices = list(outcomes[0].context.devices.values())
        self.assertEqual(len(devices), 1)
        bag = devices[0].attribute_bags["nautobot"]
        self.assertEqual(bag["role"], {"name": "Network"})
        self.assertEqual([i["name"] for i in bag["interfaces"]], ["Ethernet0/0", "Ethernet0/1"])
        self.assertEqual(bag["custom_fields"], {"snmp_credentials": "secret"})

    async def test_invalid_file_format_fails_step(self) -> None:
        with self.assertRaisesRegex(ValueError, "get-git-devices: .*file_format"):
            await _run({"file_format": "xml"}, self.repo)

    async def test_default_mapping_when_unset(self) -> None:
        (self.repo / "d.yaml").write_text("devices:\n  - name: r2\n    network_driver: ios\n")
        outcomes = await _run({}, self.repo)
        device = next(iter(outcomes[0].context.devices.values()))
        self.assertEqual((device.name, device.network_driver), ("r2", "ios"))

    async def _run_primary_csv(self, text: str, **extra):
        (self.repo / "d.yaml").unlink()
        (self.repo / "d.csv").write_text(text)
        mapping = [
            {"source": "name", "target": "name"},
            {"source": "interface_name", "target": "interfaces.name"},
            {"source": "interface_address", "target": "interfaces.ip_addresses.address"},
            {"source": "namespace", "target": "interfaces.ip_addresses.parent.namespace.name"},
            {"source": "is_primary", "target": "_is_primary"},
        ]
        return await _run(
            {
                "device_mapping": mapping,
                "file_format": "csv",
                "csv_multiline": True,
                "filename_pattern": "*.csv",
                **extra,
            },
            self.repo,
        )

    async def test_is_primary_selects_primary_ip_per_device(self) -> None:
        outcomes = await self._run_primary_csv(
            "name;interface_name;interface_address;is_primary;namespace\n"
            "device-1;eth0;10.0.0.2/24;true;black\n"
            "device-1;eth1;192.168.181.10/24;false;Global\n"
            "device-2;eth0;10.1.0.2/24;false;black\n"
            "device-2;eth1;10.1.1.2/24;true;black\n"
        )
        self.assertEqual([o.name for o in outcomes], ["success"])
        by_name = {d.name: d for d in outcomes[0].context.devices.values()}
        self.assertEqual(by_name["device-1"].primary_ip4, "10.0.0.2/24")
        self.assertEqual(by_name["device-1"].hostname, "10.0.0.2")
        self.assertEqual(by_name["device-2"].primary_ip4, "10.1.1.2/24")
        nautobot = by_name["device-1"].attribute_bags["nautobot"]
        self.assertEqual(
            nautobot["primary_ip4"],
            {"address": "10.0.0.2/24", "parent": {"namespace": {"name": "black"}}},
        )

    async def test_multiple_primaries_route_device_to_failure(self) -> None:
        outcomes = await self._run_primary_csv(
            "name;interface_name;interface_address;is_primary;namespace\n"
            "bad;eth0;10.0.0.2/24;true;black\n"
            "bad;eth1;192.168.181.10/24;true;Global\n"
            "good;eth0;10.1.0.2/24;true;black\n"
        )
        by_outcome = {o.name: o for o in outcomes}
        self.assertEqual(set(by_outcome), {"success", "failure"})
        ok = [d.name for d in by_outcome["success"].context.devices.values()]
        failed = list(by_outcome["failure"].context.devices.values())
        self.assertEqual(ok, ["good"])
        self.assertEqual([d.name for d in failed], ["bad"])
        self.assertEqual(failed[0].status.value, "failed")
        self.assertEqual(failed[0].errors[0].code, "multiple_primary_ip")
        self.assertEqual(failed[0].errors[0].step_id, "get-git-devices")
        self.assertIsNone(failed[0].primary_ip4)

    async def test_no_failure_outcome_when_all_devices_are_fine(self) -> None:
        outcomes = await self._run_primary_csv(
            "name;interface_name;interface_address;is_primary;namespace\n"
            "a;eth0;10.0.0.2/24;false;black\n"
        )
        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertIsNone(next(iter(outcomes[0].context.devices.values())).primary_ip4)

    async def test_fan_out_with_rejected_devices_fails_the_step(self) -> None:
        # The engine fans out from the success outcome only, so a failure outcome would be
        # dropped silently; the step must fail loudly instead.
        with self.assertRaisesRegex(RuntimeError, "multiple_primary_ip.*fan-out"):
            await self._run_primary_csv(
                "name;interface_name;interface_address;is_primary;namespace\n"
                "bad;eth0;10.0.0.2/24;true;black\n"
                "bad;eth1;192.168.181.10/24;true;Global\n"
                "good;eth0;10.1.0.2/24;true;black\n",
                fan_out={"enabled": True, "mode": "per_device"},
            )

    async def test_fan_out_without_rejected_devices_is_unaffected(self) -> None:
        outcomes = await self._run_primary_csv(
            "name;interface_name;interface_address;is_primary;namespace\n"
            "good;eth0;10.1.0.2/24;true;black\n",
            fan_out={"enabled": True, "mode": "per_device"},
        )
        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertTrue(outcomes[0].context.metadata["_fan_out"]["enabled"])


if __name__ == "__main__":
    unittest.main()
