"""Tests for the get-git-devices executor (mocked git layer)."""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from models.workflow_context import WorkflowContext
from workflow_steps.get_git_devices.config import get_config
from workflow_steps.get_git_devices.executor import execute

_MODULE = "workflow_steps.get_git_devices.executor"


async def _run(config: dict[str, Any], repo_dir: Path):
    run = MagicMock()
    run.id = 1
    with (
        patch(f"{_MODULE}.load_git_repository", return_value={"name": "r"}),
        patch("services.git.device_service.clone_or_pull", return_value=repo_dir),
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

    async def test_default_mapping_when_unset(self) -> None:
        (self.repo / "d.yaml").write_text("devices:\n  - name: r2\n    network_driver: ios\n")
        outcomes = await _run({}, self.repo)
        device = next(iter(outcomes[0].context.devices.values()))
        self.assertEqual((device.name, device.network_driver), ("r2", "ios"))


if __name__ == "__main__":
    unittest.main()
