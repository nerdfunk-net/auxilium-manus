"""Unit tests for workflow_steps/start_workflow/executor.py.

The step starts another workflow as a run of its own. Devices reach that workflow only through a
declared run input (the ``device_param`` of its Get from User step), filled with one
``name,ip`` line per device, exactly like a schedule or a manual run supplies them.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from core.domain_exceptions import AccessDeniedError, ValidationFailedError
from models.workflow_context import DeviceContext, DeviceStatus, WorkflowContext
from services.execution.run_service import ChildRunSnapshot
from workflow_steps.start_workflow import executor as mod

A = "dev-a"
B = "dev-b"
C = "dev-c"
FIRST_RUN_ID = 99
INPUT_NODE = "inp"


def _device(did: str, *, name: str | None = None, ip: str | None = "10.0.0.1/24") -> DeviceContext:
    return DeviceContext(
        id=did, name=name or did, hostname=did, primary_ip4=ip, source="nautobot", source_id="s"
    )


def _context(*devices: DeviceContext) -> WorkflowContext:
    return WorkflowContext(
        run_id="r", workflow_id="w", devices={d.id: d for d in (devices or (_device(A),))}
    )


def _snap(
    status: str,
    worst: str | None = "success",
    steps: dict[str, str] | None = None,
    run_id: int = FIRST_RUN_ID,
) -> ChildRunSnapshot:
    return ChildRunSnapshot(
        run_id=run_id,
        status=status,
        error_message=None,
        worst_step_status=worst,
        step_statuses={INPUT_NODE: "success"} if steps is None else steps,
    )


def _config(**overrides) -> dict:
    cfg = {
        "workflow_id": 7,
        "devices_input": "targets",
        "wait": True,
        "wait_seconds": 30,
        "poll_interval_seconds": 5,
    }
    cfg.update(overrides)
    return cfg


class _Harness:
    """Patches the module's I/O seams so the executor runs without a database."""

    def __init__(self, test: unittest.IsolatedAsyncioTestCase, snapshots=None) -> None:
        sequences = (
            {FIRST_RUN_ID: list(snapshots)}
            if isinstance(snapshots, list)
            else dict(snapshots or {})
        )
        next_id = iter(range(FIRST_RUN_ID, FIRST_RUN_ID + 1000))
        self.start = AsyncMock(side_effect=lambda **_: next(next_id))
        self.snapshot = AsyncMock(side_effect=lambda run_id: self._next(sequences, run_id))
        self.parent_cancelled = AsyncMock(return_value=False)
        self.check_target = AsyncMock(return_value=[INPUT_NODE])
        self.sleep = AsyncMock()
        for attr, target in (
            ("start", "_start_child"),
            ("snapshot", "_snapshot"),
            ("parent_cancelled", "_parent_cancelled"),
            ("check_target", "_check_target"),
            ("sleep", "_sleep"),
        ):
            patcher = patch.object(mod, target, getattr(self, attr))
            patcher.start()
            test.addCleanup(patcher.stop)

    @staticmethod
    def _next(sequences: dict, run_id: int) -> ChildRunSnapshot:
        sequence = sequences[run_id]
        return sequence.pop(0) if len(sequence) > 1 else sequence[0]

    def started_inputs(self) -> list[dict]:
        return [call.kwargs["run_inputs"] for call in self.start.await_args_list]

    async def run(self, config: dict, context: WorkflowContext | None = None):
        return await mod.execute(
            config=config,
            context=context or _context(),
            run=MagicMock(id=5, triggered_by_id=1),
            artifact_service=MagicMock(),
            node_id="n1",
            device_sessions=MagicMock(),
        )


class ConfigTests(unittest.TestCase):
    def test_defaults(self) -> None:
        parsed = mod._parse_config({"workflow_id": 7})
        self.assertEqual(
            (parsed.wait, parsed.wait_seconds, parsed.poll_interval_seconds, parsed.allow_partial),
            (True, 300, 5, False),
        )
        self.assertEqual(
            (parsed.devices_input, parsed.per_device, parsed.max_runs, parsed.bag_name),
            ("", False, 25, "child_run"),
        )

    def test_wait_is_capped_at_ten_minutes(self) -> None:
        self.assertEqual(
            mod._parse_config({"workflow_id": 7, "wait_seconds": 600}).wait_seconds, 600
        )
        for bad in (601, 4, "abc"):
            with self.subTest(wait_seconds=bad), self.assertRaises(ValueError):
                mod._parse_config({"workflow_id": 7, "wait_seconds": bad})

    def test_workflow_id_is_required_and_numeric(self) -> None:
        for bad in ({}, {"workflow_id": ""}, {"workflow_id": "x"}, {"workflow_id": 0}):
            with self.subTest(config=bad), self.assertRaises(ValueError):
                mod._parse_config(bad)

    def test_poll_interval_bounds(self) -> None:
        for bad in (0, 61):
            with self.subTest(interval=bad), self.assertRaises(ValueError):
                mod._parse_config({"workflow_id": 7, "poll_interval_seconds": bad})

    def test_run_inputs_must_be_an_object(self) -> None:
        with self.assertRaises(ValueError):
            mod._parse_config({"workflow_id": 7, "run_inputs": [1]})

    def test_a_mistyped_flag_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            mod._parse_config({"workflow_id": 7, "wait": "ture"})

    def test_run_mode_and_run_cap(self) -> None:
        per_device = mod._parse_config(
            {"workflow_id": 7, "devices_input": "t", "run_mode": "per_device", "max_runs": 3}
        )
        self.assertEqual((per_device.per_device, per_device.max_runs), (True, 3))
        for bad in ({"run_mode": "everything"}, {"max_runs": 0}, {"max_runs": 201}):
            with self.subTest(config=bad), self.assertRaises(ValueError):
                mod._parse_config({"workflow_id": 7, "devices_input": "t", **bad})

    def test_one_run_per_device_needs_an_input_to_put_the_device_in(self) -> None:
        with self.assertRaises(ValueError):
            mod._parse_config({"workflow_id": 7, "run_mode": "per_device"})


class DeviceLineTests(unittest.TestCase):
    def test_name_and_bare_ip(self) -> None:
        self.assertEqual(
            mod._device_line(_device("x", name="sw1", ip="10.0.0.1/24")), "sw1,10.0.0.1"
        )

    def test_name_only_when_there_is_no_usable_ip(self) -> None:
        self.assertEqual(mod._device_line(_device("x", name="sw1", ip=None)), "sw1")
        self.assertEqual(mod._device_line(_device("x", name="sw1", ip="not-an-ip")), "sw1")

    def test_a_name_that_would_break_the_line_format_falls_back_to_the_ip(self) -> None:
        for name in ("a,b", "a\nb"):
            with self.subTest(name=name):
                self.assertEqual(
                    mod._device_line(_device("x", name=name, ip="10.0.0.1")), "10.0.0.1"
                )
                self.assertIsNone(mod._device_line(_device("x", name=name, ip=None)))


class InspectTargetTests(unittest.TestCase):
    def _input_node(self, node_id: str, param: str, **data: object) -> dict:
        return {
            "id": node_id,
            "data": {"kind": "get-from-user", "pluginConfig": {"device_param": param}, **data},
        }

    ATTRS = [{"name": "targets", "type": "string", "default": None, "required": True}]

    def test_returns_the_enabled_steps_that_read_the_input(self) -> None:
        nodes = [self._input_node("a", "targets"), self._input_node("b", "other")]
        self.assertEqual(mod._inspect_target("Backup", nodes, self.ATTRS, {}, "targets"), ["a"])

    def test_a_disabled_step_does_not_count(self) -> None:
        with self.assertRaises(ValueError):
            mod._inspect_target(
                "Backup",
                [self._input_node("a", "targets", disabled=True)],
                self.ATTRS,
                {},
                "targets",
            )

    def test_no_step_reading_the_input_is_an_error(self) -> None:
        for nodes in ([], [self._input_node("a", "other")], ["junk"]):
            with self.subTest(nodes=nodes), self.assertRaises(ValueError):
                mod._inspect_target("Backup", nodes, self.ATTRS, {}, "targets")

    def test_the_input_must_be_a_declared_string(self) -> None:
        nodes = [self._input_node("a", "targets")]
        for attrs in ([], [{"name": "targets", "type": "number"}]):
            with self.subTest(attrs=attrs), self.assertRaises(ValueError):
                mod._inspect_target("Backup", nodes, attrs, {}, "targets")

    def test_the_devices_input_cannot_also_be_given_a_value_by_hand(self) -> None:
        nodes = [self._input_node("a", "targets")]
        with self.assertRaises(ValueError):
            mod._inspect_target("Backup", nodes, self.ATTRS, {"targets": "x"}, "targets")

    def test_without_a_devices_input_nothing_about_devices_is_required(self) -> None:
        self.assertEqual(mod._inspect_target("Backup", [], [], {}, ""), [])

    def test_a_secret_input_is_refused_and_never_echoed(self) -> None:
        attrs = [{"name": "key", "type": "secret", "default": None, "required": True}]
        with self.assertRaises(ValueError) as ctx:
            mod._inspect_target("Backup", [], attrs, {"key": "hunter2"}, "")
        self.assertIn("key", str(ctx.exception))
        self.assertNotIn("hunter2", str(ctx.exception))


class HandingOverDevicesTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_devices_go_into_one_run_as_name_ip_lines(self) -> None:
        h = _Harness(self, [_snap("success")])
        await h.run(
            _config(run_inputs={"site": "lab"}),
            _context(_device(A, name="sw1", ip="10.0.0.1/24"), _device(B, name="sw2", ip=None)),
        )
        h.start.assert_awaited_once()
        self.assertEqual(h.started_inputs(), [{"site": "lab", "targets": "sw1,10.0.0.1\nsw2"}])

    async def test_a_target_without_a_devices_input_is_called_without_devices(self) -> None:
        h = _Harness(self, [_snap("success", steps={})])
        h.check_target.return_value = []
        outcomes = await h.run(_config(devices_input="", run_inputs={"site": "lab"}))
        self.assertEqual(h.started_inputs(), [{"site": "lab"}])
        self.assertEqual([o.name for o in outcomes], ["success"])

    async def test_a_device_without_a_usable_identity_fails_and_the_others_continue(self) -> None:
        h = _Harness(self, [_snap("success")])
        outcomes = await h.run(
            _config(), _context(_device(A, name="sw1"), _device(B, name="a,b", ip=None))
        )
        self.assertEqual(h.started_inputs(), [{"targets": "sw1,10.0.0.1"}])
        by_name = {o.name: o for o in outcomes}
        self.assertEqual(sorted(by_name["success"].context.devices), [A])
        self.assertEqual(by_name["failure"].context.devices[B].errors[0].code, "no_device_identity")

    async def test_nothing_is_started_when_no_device_has_an_identity(self) -> None:
        h = _Harness(self, [])
        outcomes = await h.run(_config(), _context(_device(A, name="a,b", ip=None)))
        h.start.assert_not_awaited()
        self.assertEqual([o.name for o in outcomes], ["failure"])

    async def test_no_devices_means_nothing_to_start(self) -> None:
        h = _Harness(self, [])
        outcomes = await h.run(_config(), WorkflowContext(run_id="r", workflow_id="w"))
        h.start.assert_not_awaited()
        self.assertEqual([o.name for o in outcomes], ["success"])


class FireAndForgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_without_waiting_it_only_starts_the_run(self) -> None:
        h = _Harness(self, [])
        outcomes = await h.run(_config(wait=False), _context(_device(A), _device(B)))

        h.start.assert_awaited_once()
        h.snapshot.assert_not_awaited()
        self.assertEqual([o.name for o in outcomes], ["success"])
        bag = outcomes[0].context.devices[A].attribute_bags["child_run"]
        self.assertEqual(
            bag,
            {"run_id": FIRST_RUN_ID, "workflow_id": 7, "status": "dispatched", "waited_seconds": 0},
        )


class WaitingTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_on_the_first_check(self) -> None:
        h = _Harness(self, [_snap("success")])
        outcomes = await h.run(_config())
        self.assertEqual([o.name for o in outcomes], ["success"])
        h.sleep.assert_not_awaited()
        bag = outcomes[0].context.devices[A].attribute_bags["child_run"]
        self.assertEqual((bag["status"], bag["waited_seconds"]), ("success", 0))

    async def test_polls_until_the_child_finishes(self) -> None:
        h = _Harness(
            self, [_snap("pending", None, {}), _snap("running", None, {}), _snap("success")]
        )
        outcomes = await h.run(_config())
        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertEqual([c.args[0] for c in h.sleep.await_args_list], [5, 5])
        bag = outcomes[0].context.devices[A].attribute_bags["child_run"]
        self.assertEqual(bag["waited_seconds"], 10)

    async def test_a_failed_child_routes_every_device_to_failure(self) -> None:
        h = _Harness(self, [_snap("failed", "failed")])
        outcomes = await h.run(_config(), _context(_device(A), _device(B)))
        self.assertEqual([o.name for o in outcomes], ["failure"])
        devices = outcomes[0].context.devices
        self.assertEqual({d.status for d in devices.values()}, {DeviceStatus.FAILED})
        error = devices[A].errors[0]
        self.assertEqual((error.step_id, error.node_id), ("start-workflow", "n1"))
        self.assertEqual((error.failure.phase, error.failure.kind), ("task", "task_failed"))
        self.assertIn(str(FIRST_RUN_ID), error.message)

    async def test_a_cancelled_child_is_a_failure(self) -> None:
        h = _Harness(self, [_snap("cancelled", None)])
        outcomes = await h.run(_config())
        self.assertEqual([o.name for o in outcomes], ["failure"])

    async def test_a_partial_result_is_a_failure_by_default(self) -> None:
        h = _Harness(self, [_snap("success", "partial")])
        self.assertEqual([o.name for o in await h.run(_config())], ["failure"])

    async def test_a_partial_result_can_be_accepted(self) -> None:
        h = _Harness(self, [_snap("success", "partial")])
        self.assertEqual([o.name for o in await h.run(_config(allow_partial=True))], ["success"])

    async def test_a_failed_step_is_never_accepted_as_partial(self) -> None:
        h = _Harness(self, [_snap("success", "failed")])
        self.assertEqual([o.name for o in await h.run(_config(allow_partial=True))], ["failure"])

    async def test_a_skipped_step_is_not_a_clean_success(self) -> None:
        h = _Harness(self, [_snap("success", "skipped")])
        self.assertEqual([o.name for o in await h.run(_config())], ["failure"])

    async def test_timeout_fails_but_leaves_the_child_running(self) -> None:
        h = _Harness(self, [_snap("running", None, {})])
        outcomes = await h.run(_config(wait_seconds=12, poll_interval_seconds=5))

        self.assertEqual([o.name for o in outcomes], ["failure"])
        self.assertEqual([c.args[0] for c in h.sleep.await_args_list], [5, 5, 2])
        error = outcomes[0].context.devices[A].errors[0]
        self.assertEqual(error.failure.kind, "task_timeout")
        self.assertTrue(error.failure.retryable)
        bag = outcomes[0].context.devices[A].attribute_bags["child_run"]
        self.assertEqual((bag["status"], bag["waited_seconds"]), ("timeout", 12))
        self.assertIsNotNone(outcomes[0].failure)

    async def test_a_cancelled_parent_stops_the_wait(self) -> None:
        h = _Harness(self, [_snap("running", None, {})])
        h.parent_cancelled.return_value = True
        outcomes = await h.run(_config())
        self.assertEqual([o.name for o in outcomes], ["failure"])
        h.sleep.assert_not_awaited()


class ChildActuallyUsedTheDevicesTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_finished_run_whose_input_step_never_ran_is_a_failure(self) -> None:
        for steps in ({}, {INPUT_NODE: "skipped"}, {INPUT_NODE: "pending"}, {"other": "success"}):
            with self.subTest(steps=steps):
                h = _Harness(self, [_snap("success", "success", steps)])
                outcomes = await h.run(_config())
                self.assertEqual([o.name for o in outcomes], ["failure"])
                self.assertEqual(
                    outcomes[0].context.devices[A].errors[0].code, "child_run_not_applied"
                )

    async def test_any_of_several_input_steps_running_is_enough(self) -> None:
        h = _Harness(self, [_snap("success", "success", {"a": "pending", "b": "success"})])
        h.check_target.return_value = ["a", "b"]
        self.assertEqual([o.name for o in await h.run(_config())], ["success"])


class PerDeviceTests(unittest.IsolatedAsyncioTestCase):
    def _config(self, **kw) -> dict:
        return _config(run_mode="per_device", **kw)

    async def test_one_run_per_device_with_its_own_line(self) -> None:
        h = _Harness(self, {99: [_snap("success", run_id=99)], 100: [_snap("success", run_id=100)]})
        outcomes = await h.run(
            self._config(), _context(_device(A, name="sw1"), _device(B, name="sw2", ip=None))
        )
        self.assertEqual(h.started_inputs(), [{"targets": "sw1,10.0.0.1"}, {"targets": "sw2"}])
        self.assertEqual([o.name for o in outcomes], ["success"])
        devices = outcomes[0].context.devices
        self.assertEqual(devices[A].attribute_bags["child_run"]["run_id"], 99)
        self.assertEqual(devices[B].attribute_bags["child_run"]["run_id"], 100)

    async def test_each_device_is_routed_by_its_own_run(self) -> None:
        h = _Harness(
            self,
            {
                99: [_snap("success", run_id=99)],
                100: [_snap("failed", "failed", run_id=100)],
                101: [_snap("running", None, {}, run_id=101)],
            },
        )
        outcomes = await h.run(
            self._config(wait_seconds=5), _context(_device(A), _device(B), _device(C))
        )
        by_name = {o.name: o for o in outcomes}
        self.assertEqual(sorted(by_name["success"].context.devices), [A])
        self.assertEqual(sorted(by_name["failure"].context.devices), [B, C])
        kinds = {
            key: by_name["failure"].context.devices[key].errors[0].failure.kind for key in (B, C)
        }
        self.assertEqual(kinds, {B: "task_failed", C: "task_timeout"})

    async def test_more_devices_than_the_run_cap_start_nothing(self) -> None:
        h = _Harness(self, [])
        with self.assertRaises(ValueError) as ctx:
            await h.run(self._config(max_runs=2), _context(_device(A), _device(B), _device(C)))
        self.assertIn("max_runs", str(ctx.exception))
        h.start.assert_not_awaited()

    async def test_the_cap_counts_runs_not_devices_in_all_devices_mode(self) -> None:
        h = _Harness(self, [_snap("success")])
        outcomes = await h.run(_config(max_runs=1), _context(_device(A), _device(B), _device(C)))
        self.assertEqual([o.name for o in outcomes], ["success"])

    async def test_an_unavailable_engine_stops_starting_more_runs(self) -> None:
        h = _Harness(self, [])
        h.start.side_effect = HTTPException(status_code=503, detail="engine unavailable")
        outcomes = await h.run(self._config(), _context(_device(A), _device(B)))
        h.start.assert_awaited_once()
        self.assertEqual([o.name for o in outcomes], ["failure"])
        self.assertEqual(sorted(outcomes[0].context.devices), [A, B])
        error = outcomes[0].context.devices[B].errors[0]
        self.assertEqual((error.code, error.failure.kind), ("engine_unavailable", "server_error"))


class DispatchProblemTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_unavailable_engine_fails_the_devices(self) -> None:
        h = _Harness(self, [])
        h.start.side_effect = HTTPException(status_code=503, detail="engine unavailable")
        outcomes = await h.run(_config())
        self.assertEqual([o.name for o in outcomes], ["failure"])
        error = outcomes[0].context.devices[A].errors[0]
        self.assertEqual((error.failure.phase, error.failure.kind), ("api", "server_error"))
        self.assertTrue(error.failure.retryable)
        h.snapshot.assert_not_awaited()

    async def test_domain_refusals_are_configuration_errors(self) -> None:
        for exc in (AccessDeniedError("no"), ValidationFailedError("recursion")):
            with self.subTest(exc=type(exc).__name__):
                h = _Harness(self, [])
                h.start.side_effect = exc
                with self.assertRaises(ValueError):
                    await h.run(_config())

    async def test_a_target_that_does_not_fit_is_refused_before_dispatch(self) -> None:
        h = _Harness(self, [])
        h.check_target.side_effect = ValueError("no step reads the input")
        with self.assertRaises(ValueError):
            await h.run(_config())
        h.start.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
