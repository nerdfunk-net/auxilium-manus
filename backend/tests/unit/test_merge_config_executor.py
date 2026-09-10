"""Tests for the merge-config executor."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.network.netmiko.connection import CommandResult as NetmikoCommandResult
from workflow_steps.merge_config.executor import execute

_EXEC = "workflow_steps.merge_config.executor"


def _device(device_id: str = "device-1", *, hostname: str = "router1") -> DeviceContext:
    return DeviceContext(
        id=device_id,
        name=hostname or device_id,
        hostname=hostname,
        primary_ip4="10.0.0.1/24" if hostname else None,
        network_driver="cisco_ios",
        status=DeviceStatus.OK,
    )


def _context(devices: dict[str, DeviceContext]) -> WorkflowContext:
    return WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1", devices=devices)


def _run() -> MagicMock:
    run = MagicMock()
    run.id = 1
    run.run_inputs = {}
    return run


def _ok_result(confirmed: list[str] | None = None) -> NetmikoCommandResult:
    return NetmikoCommandResult(
        success=True,
        output="Building configuration...\n[OK]\n1024 bytes copied in 0.4 secs\nR1#",
        command_outputs={"copy flash:partial.cfg running-config": "ok"},
        confirmed_prompts=confirmed or [],
    )


class MergeConfigExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_stores_command_result_and_artifact(self) -> None:
        with (
            patch(f"{_EXEC}.object_session", return_value=MagicMock()),
            patch(f"{_EXEC}.resolve_ssh_credential", return_value=("admin", "secret")),
            patch(f"{_EXEC}.NetmikoService") as netmiko_cls,
        ):
            netmiko_cls.return_value.merge_config = AsyncMock(return_value=_ok_result())

            outcomes = await execute(
                config={
                    "credential_reference": "lab-ssh",
                    "source_filename": "flash:partial.cfg",
                },
                context=_context({"device-1": _device()}),
                run=_run(),
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual([o.name for o in outcomes], ["success"])
        device = outcomes[0].context.devices["device-1"]
        self.assertEqual(device.status, DeviceStatus.OK)
        results = device.command_results["node-1"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].command, "copy flash:partial.cfg running-config")
        self.assertIsNotNone(results[0].output_ref)

    async def test_auto_answered_prompt_in_summary_and_warns(self) -> None:
        with (
            patch(f"{_EXEC}.object_session", return_value=MagicMock()),
            patch(f"{_EXEC}.resolve_ssh_credential", return_value=("admin", "secret")),
            patch(f"{_EXEC}.NetmikoService") as netmiko_cls,
        ):
            netmiko_cls.return_value.merge_config = AsyncMock(
                return_value=_ok_result(confirmed=["destination filename"])
            )

            with self.assertLogs(_EXEC, level="WARNING") as logs:
                outcomes = await execute(
                    config={
                        "credential_reference": "lab-ssh",
                        "source_filename": "flash:partial.cfg",
                    },
                    context=_context({"device-1": _device()}),
                    run=_run(),
                    artifact_service=InMemoryArtifactService(),
                    node_id="node-1",
                    device_sessions=MagicMock(),
                )

        summary = outcomes[0].context.devices["device-1"].command_results["node-1"][0].summary
        self.assertIn("1 interactive prompt(s) auto-answered", summary or "")
        self.assertTrue(any("auto-answered" in line for line in logs.output))

    async def test_no_prompt_answered_summary_is_plain(self) -> None:
        with (
            patch(f"{_EXEC}.object_session", return_value=MagicMock()),
            patch(f"{_EXEC}.resolve_ssh_credential", return_value=("admin", "secret")),
            patch(f"{_EXEC}.NetmikoService") as netmiko_cls,
        ):
            netmiko_cls.return_value.merge_config = AsyncMock(return_value=_ok_result())

            outcomes = await execute(
                config={
                    "credential_reference": "lab-ssh",
                    "source_filename": "flash:partial.cfg",
                },
                context=_context({"device-1": _device()}),
                run=_run(),
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        summary = outcomes[0].context.devices["device-1"].command_results["node-1"][0].summary
        self.assertNotIn("auto-answered", summary or "")

    async def test_copy_error_produces_failure_outcome(self) -> None:
        with (
            patch(f"{_EXEC}.object_session", return_value=MagicMock()),
            patch(f"{_EXEC}.resolve_ssh_credential", return_value=("admin", "secret")),
            patch(f"{_EXEC}.NetmikoService") as netmiko_cls,
        ):
            netmiko_cls.return_value.merge_config = AsyncMock(
                return_value=NetmikoCommandResult(
                    success=False,
                    output="%Error opening flash:missing.cfg (No such file or directory)",
                    error="%Error opening flash:missing.cfg (No such file or directory)",
                )
            )

            outcomes = await execute(
                config={
                    "credential_reference": "lab-ssh",
                    "source_filename": "flash:missing.cfg",
                },
                context=_context({"device-1": _device()}),
                run=_run(),
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        failed = outcomes[1].context.devices["device-1"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        err = failed.errors[-1]
        self.assertEqual(err.step_id, "merge-config")
        self.assertEqual(err.code, "merge_failed")
        self.assertIn("%Error opening", err.message)
        # the CommandResult is still recorded on the failed device
        self.assertIn("node-1", failed.command_results)

    async def test_credential_fixed_passes_literal_name(self) -> None:
        with (
            patch(f"{_EXEC}.object_session", return_value=MagicMock()),
            patch(
                f"{_EXEC}.resolve_ssh_credential", return_value=("admin", "secret")
            ) as resolve,
            patch(f"{_EXEC}.NetmikoService") as netmiko_cls,
        ):
            netmiko_cls.return_value.merge_config = AsyncMock(return_value=_ok_result())

            await execute(
                config={
                    "credential_reference": "lab-ssh",
                    "source_filename": "flash:partial.cfg",
                },
                context=_context({"device-1": _device()}),
                run=_run(),
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(resolve.call_args.args[1], "lab-ssh")

    async def test_credential_run_param_resolves_from_run_inputs(self) -> None:
        run = _run()
        run.run_inputs = {"ssh_cred": "team-b-ssh"}
        with (
            patch(f"{_EXEC}.object_session", return_value=MagicMock()),
            patch(
                f"{_EXEC}.resolve_ssh_credential", return_value=("admin", "secret")
            ) as resolve,
            patch(f"{_EXEC}.NetmikoService") as netmiko_cls,
        ):
            netmiko_cls.return_value.merge_config = AsyncMock(return_value=_ok_result())

            await execute(
                config={
                    "credential_source": "run_param",
                    "credential_param": "ssh_cred",
                    "source_filename": "flash:partial.cfg",
                },
                context=_context({"device-1": _device()}),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(resolve.call_args.args[1], "team-b-ssh")

    async def test_credential_run_param_missing_key_raises(self) -> None:
        with (
            patch(f"{_EXEC}.object_session", return_value=MagicMock()),
            patch(f"{_EXEC}.resolve_ssh_credential", return_value=("admin", "secret")),
            patch(f"{_EXEC}.NetmikoService"),
        ):
            with self.assertRaises(ValueError):
                await execute(
                    config={
                        "credential_source": "run_param",
                        "credential_param": "missing",
                        "source_filename": "flash:partial.cfg",
                    },
                    context=_context({"device-1": _device()}),
                    run=_run(),
                    artifact_service=InMemoryArtifactService(),
                    node_id="node-1",
                    device_sessions=MagicMock(),
                )

    async def test_network_driver_override_forwarded(self) -> None:
        with (
            patch(f"{_EXEC}.object_session", return_value=MagicMock()),
            patch(f"{_EXEC}.resolve_ssh_credential", return_value=("admin", "secret")),
            patch(
                f"{_EXEC}.resolve_connection_device_type", return_value="cisco_nxos"
            ) as resolver,
            patch(f"{_EXEC}.NetmikoService") as netmiko_cls,
        ):
            merge = AsyncMock(return_value=_ok_result())
            netmiko_cls.return_value.merge_config = merge

            await execute(
                config={
                    "credential_reference": "lab-ssh",
                    "source_filename": "flash:partial.cfg",
                    "network_driver_override": "cisco_nxos",
                },
                context=_context({"device-1": _device()}),
                run=_run(),
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(resolver.call_args.kwargs["override"], "cisco_nxos")
        self.assertEqual(merge.await_args.kwargs["device_type"], "cisco_nxos")

    async def test_read_timeout_bounds(self) -> None:
        for bad in (1, 99999):
            with self.subTest(read_timeout=bad):
                with self.assertRaises(ValueError):
                    await execute(
                        config={
                            "credential_reference": "lab-ssh",
                            "source_filename": "flash:partial.cfg",
                            "read_timeout": bad,
                        },
                        context=_context({"device-1": _device()}),
                        run=_run(),
                        artifact_service=InMemoryArtifactService(),
                        node_id="node-1",
                        device_sessions=MagicMock(),
                    )

    async def test_read_timeout_forwarded(self) -> None:
        with (
            patch(f"{_EXEC}.object_session", return_value=MagicMock()),
            patch(f"{_EXEC}.resolve_ssh_credential", return_value=("admin", "secret")),
            patch(f"{_EXEC}.NetmikoService") as netmiko_cls,
        ):
            merge = AsyncMock(return_value=_ok_result())
            netmiko_cls.return_value.merge_config = merge

            await execute(
                config={
                    "credential_reference": "lab-ssh",
                    "source_filename": "flash:partial.cfg",
                    "read_timeout": 120,
                },
                context=_context({"device-1": _device()}),
                run=_run(),
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(merge.await_args.kwargs["read_timeout"], 120)

    async def test_read_timeout_non_integer_raises(self) -> None:
        with self.assertRaises(ValueError):
            await execute(
                config={
                    "credential_reference": "lab-ssh",
                    "source_filename": "flash:partial.cfg",
                    "read_timeout": "not-a-number",
                },
                context=_context({"device-1": _device()}),
                run=_run(),
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

    async def test_missing_db_session_raises_runtime_error(self) -> None:
        with (
            patch(f"{_EXEC}.object_session", return_value=None),
            patch(f"{_EXEC}.resolve_ssh_credential", return_value=("admin", "secret")),
            patch(f"{_EXEC}.NetmikoService"),
        ):
            with self.assertRaises(RuntimeError):
                await execute(
                    config={
                        "credential_reference": "lab-ssh",
                        "source_filename": "flash:partial.cfg",
                    },
                    context=_context({"device-1": _device()}),
                    run=_run(),
                    artifact_service=InMemoryArtifactService(),
                    node_id="node-1",
                    device_sessions=MagicMock(),
                )

    async def test_source_filename_required(self) -> None:
        for value in ("", "   ", None):
            with self.subTest(source_filename=value):
                cfg: dict = {"credential_reference": "lab-ssh"}
                if value is not None:
                    cfg["source_filename"] = value
                with self.assertRaises(ValueError):
                    await execute(
                        config=cfg,
                        context=_context({"device-1": _device()}),
                        run=_run(),
                        artifact_service=InMemoryArtifactService(),
                        node_id="node-1",
                        device_sessions=MagicMock(),
                    )

    async def test_fan_out_over_multiple_devices(self) -> None:
        with (
            patch(f"{_EXEC}.object_session", return_value=MagicMock()),
            patch(f"{_EXEC}.resolve_ssh_credential", return_value=("admin", "secret")),
            patch(f"{_EXEC}.NetmikoService") as netmiko_cls,
        ):
            merge = AsyncMock(
                side_effect=[
                    _ok_result(),
                    NetmikoCommandResult(success=False, output="boom", error="boom"),
                    _ok_result(),
                ]
            )
            netmiko_cls.return_value.merge_config = merge

            outcomes = await execute(
                config={
                    "credential_reference": "lab-ssh",
                    "source_filename": "flash:partial.cfg",
                },
                context=_context(
                    {
                        "d1": _device("d1"),
                        "d2": _device("d2"),
                        "d3": _device("d3"),
                    }
                ),
                run=_run(),
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(merge.await_count, 3)
        by_name = {o.name: o for o in outcomes}
        self.assertEqual(set(by_name["success"].context.devices), {"d1", "d3"})
        self.assertEqual(set(by_name["failure"].context.devices), {"d2"})

    async def test_empty_device_list_returns_success(self) -> None:
        with patch(f"{_EXEC}.NetmikoService") as netmiko_cls:
            outcomes = await execute(
                config={
                    "credential_reference": "lab-ssh",
                    "source_filename": "flash:partial.cfg",
                },
                context=_context({}),
                run=_run(),
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual([o.name for o in outcomes], ["success"])
        netmiko_cls.assert_not_called()

    async def test_missing_host_fails_device_without_calling_merge(self) -> None:
        with (
            patch(f"{_EXEC}.object_session", return_value=MagicMock()),
            patch(f"{_EXEC}.resolve_ssh_credential", return_value=("admin", "secret")),
            patch(f"{_EXEC}.NetmikoService") as netmiko_cls,
        ):
            merge = AsyncMock(return_value=_ok_result())
            netmiko_cls.return_value.merge_config = merge

            outcomes = await execute(
                config={
                    "credential_reference": "lab-ssh",
                    "source_filename": "flash:partial.cfg",
                },
                context=_context({"d1": _device("d1", hostname="")}),
                run=_run(),
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        merge.assert_not_awaited()
        by_name = {o.name: o for o in outcomes}
        failed = by_name["failure"].context.devices["d1"]
        self.assertEqual(failed.errors[-1].code, "missing_host")

    async def test_merge_config_exception_fails_device(self) -> None:
        with (
            patch(f"{_EXEC}.object_session", return_value=MagicMock()),
            patch(f"{_EXEC}.resolve_ssh_credential", return_value=("admin", "secret")),
            patch(f"{_EXEC}.NetmikoService") as netmiko_cls,
        ):
            netmiko_cls.return_value.merge_config = AsyncMock(
                side_effect=RuntimeError("connect fail")
            )

            outcomes = await execute(
                config={
                    "credential_reference": "lab-ssh",
                    "source_filename": "flash:partial.cfg",
                },
                context=_context({"device-1": _device()}),
                run=_run(),
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        by_name = {o.name: o for o in outcomes}
        failed = by_name["failure"].context.devices["device-1"]
        self.assertEqual(failed.errors[-1].code, "runtimeerror")
        self.assertIn("connect fail", failed.errors[-1].message)


if __name__ == "__main__":
    unittest.main()
