"""The source-agnostic fact-step core and the outcome helpers."""

from __future__ import annotations

import unittest
from typing import Any

from pydantic import BaseModel, ConfigDict

from models.failure import FailureInfo
from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from workflow_steps.common.device_outcomes import TargetSplit, build_outcomes, failed_device
from workflow_steps.common.fact_entries import (
    FactError,
    collect_facts,
    dump,
    error_entry,
    ok_entry,
    parse_output_key_config,
    with_entries,
)


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True)
    value: int


def _device(device_id: str = "d1") -> DeviceContext:
    return DeviceContext(id=device_id, name=device_id, hostname=device_id)


class EntryTests(unittest.TestCase):
    def test_dump_turns_models_and_sequences_of_models_into_json(self) -> None:
        self.assertEqual(dump(_Model(value=1)), {"value": 1})
        self.assertEqual(dump((_Model(value=1), _Model(value=2))), [{"value": 1}, {"value": 2}])
        self.assertEqual(dump("text"), "text")
        self.assertIsNone(dump(None))

    def test_entries(self) -> None:
        self.assertEqual(ok_entry(_Model(value=3)), {"parsed": {"value": 3}, "error": None})
        self.assertEqual(error_entry("boom"), {"parsed": None, "error": "boom"})
        info = FailureInfo(phase="api", kind="timeout")
        entry = error_entry(FactError("slow", info))
        self.assertEqual((entry["parsed"], entry["error"], entry["failure"]), (None, "slow", info))

    def test_output_key_is_validated_with_the_step_id(self) -> None:
        self.assertEqual(
            parse_output_key_config(None, step_id="s", default="aci_details"), "aci_details"
        )
        self.assertEqual(parse_output_key_config(" fabric ", step_id="s", default="x"), "fabric")
        for bad in ("1abc", "has space", "a-b"):
            with self.subTest(key=bad), self.assertRaisesRegex(ValueError, "s: parsed_output_key"):
                parse_output_key_config(bad, step_id="s", default="x")


class WithEntriesTests(unittest.TestCase):
    def _call(self, device: DeviceContext, entries: dict[str, Any], code: str = "my_error"):
        return with_entries(
            device, entries, output_key="k", step_id="s", node_id="n", error_code=code
        )

    def test_the_error_code_is_the_callers_not_a_hard_coded_one(self) -> None:
        for code in ("aci_error", "catalyst_center_error"):
            updated, ok = self._call(_device(), {"a": error_entry("x")}, code)
            self.assertFalse(ok)
            self.assertEqual(updated.errors[0].code, code)

    def test_one_good_entry_keeps_the_device_ok_and_marks_parsed(self) -> None:
        updated, ok = self._call(_device(), {"a": error_entry("x"), "b": ok_entry(1)})
        self.assertTrue(ok)
        self.assertEqual(updated.status, DeviceStatus.OK)
        self.assertIn(Capability.PARSED, updated.capabilities)
        self.assertEqual(updated.parsed["k"]["a"], {"parsed": None, "error": "x"})

    def test_the_structured_failure_is_kept_on_the_error_but_not_in_the_stored_entry(self) -> None:
        info = FailureInfo(phase="api", kind="server_error")
        updated, ok = self._call(_device(), {"a": error_entry(FactError("down", info))})
        self.assertFalse(ok)
        self.assertEqual(updated.errors[0].failure, info)
        self.assertNotIn("failure", updated.parsed["k"]["a"])

    def test_the_input_device_is_not_mutated_and_no_entries_is_ok(self) -> None:
        device = _device()
        before = device.model_dump()
        self._call(device, {"a": ok_entry(1)})
        self.assertEqual(device.model_dump(), before)
        updated, ok = self._call(device, {})
        self.assertTrue(ok)
        self.assertEqual(updated.parsed["k"], {})


class OutcomeHelperTests(unittest.TestCase):
    def test_failed_device_adds_an_error_and_keeps_the_rest(self) -> None:
        first = failed_device(
            _device(), step_id="s", node_id="n", code="a", message="m1", parsed={"x": 1}
        )
        second = failed_device(first, step_id="s", node_id="n", code="b", message="m2")
        self.assertEqual([e.code for e in second.errors], ["a", "b"])
        self.assertEqual(second.status, DeviceStatus.FAILED)
        self.assertEqual(second.parsed, {"x": 1})
        self.assertEqual(first.errors[0].code, "a")  # the earlier copy is untouched

    def test_outcomes_have_a_failure_handle_only_when_something_failed(self) -> None:
        context = WorkflowContext(run_id="r", workflow_id="w", devices={"d1": _device()})
        ok_only = build_outcomes(context, {"d1": _device()}, {})
        self.assertEqual([o.name for o in ok_only], ["success"])
        both = build_outcomes(context, {"d1": _device()}, {"d2": _device("d2")})
        self.assertEqual([o.name for o in both], ["success", "failure"])
        self.assertEqual(list(both[1].context.devices), ["d2"])
        self.assertEqual(list(context.devices), ["d1"])  # the input context is untouched


class CollectFactsTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, collect, *, prepare=None, devices=("d1", "d2")):
        split = TargetSplit(
            by_source={"src": {d: _device(d) for d in devices}},
            rejected={
                "bad": failed_device(
                    _device("bad"), step_id="s", node_id="n", code="r", message="m"
                )
            },
        )
        context = WorkflowContext(
            run_id="r", workflow_id="w", devices={d: _device(d) for d in devices}
        )
        return await collect_facts(
            step_id="s",
            context=context,
            node_id="n",
            output_key="k",
            collect=collect,
            split=split,
            credentials={"src": "creds"},
            error_code="e",
            prepare=prepare,
        )

    async def test_rejected_devices_join_the_failed_ones(self) -> None:
        async def collect(creds, state, device_id, device):
            return {"a": ok_entry(device_id)}

        outcomes = await self._run(collect)
        by_name = {o.name: o for o in outcomes}
        self.assertEqual(sorted(by_name["success"].context.devices), ["d1", "d2"])
        self.assertEqual(list(by_name["failure"].context.devices), ["bad"])

    async def test_prepare_runs_once_per_source_and_its_state_reaches_collect(self) -> None:
        calls: list[str] = []

        async def prepare(creds):
            calls.append(creds)
            return {"shared": 42}

        seen: list[Any] = []

        async def collect(creds, state, device_id, device):
            seen.append((creds, state))
            return {"a": ok_entry(1)}

        await self._run(collect, prepare=prepare)
        self.assertEqual(calls, ["creds"])
        self.assertEqual(seen, [("creds", {"shared": 42})] * 2)

    async def test_without_prepare_the_state_is_none(self) -> None:
        states: list[Any] = []

        async def collect(creds, state, device_id, device):
            states.append(state)
            return {"a": ok_entry(1)}

        await self._run(collect)
        self.assertEqual(states, [None, None])


if __name__ == "__main__":
    unittest.main()
