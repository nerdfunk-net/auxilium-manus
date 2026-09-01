"""Tests for compare-pyats-snapshot executor."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import (
    ArtifactRef,
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.artifacts import InMemoryArtifactService
from services.pyats.common.exceptions import PyATSAPIError, PyATSValidationError
from workflow_steps.compare_pyats_snapshot.executor import execute

_SOURCE_STEP_NODE_ID = "get-pyats-snapshot-5"
_NODE_ID = "compare-pyats-snapshot-1"
_BASE_CONFIG = {
    "features": ["bgp"],
    "source_step_node_id": _SOURCE_STEP_NODE_ID,
    "parsed_output_key": "pyats_snapshot",
    "reference_location": "filesystem",
    "reference_subdirectory": "pyats-snapshots",
    "filename_template": "{device.name}.pyats-snapshot.json",
}


def _device_with_snapshot(
    artifact_ref: ArtifactRef, *, source_id: str = "lab-pyats"
) -> DeviceContext:
    return DeviceContext(
        id="device-1",
        name="lab",
        hostname="lab",
        attribute_bags={"pyats_testbed": {"pyats_source_id": source_id, "host": "10.0.0.1"}},
        parsed={
            "pyats_snapshot": {
                "kind": "pyats_snapshot",
                "artifact_ref": artifact_ref.model_dump(mode="json"),
                "step_node_id": _SOURCE_STEP_NODE_ID,
                "features": {"bgp": {"success": True, "error": None}},
            }
        },
        capabilities={Capability.IDENTITY, Capability.PARSED},
        status=DeviceStatus.OK,
    )


class ComparePyatsSnapshotExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def _run(
        self,
        *,
        device: DeviceContext,
        reference_content: str,
        shim_diff_result: dict | None = None,
        shim_diff_results: list[dict] | None = None,
        shim_diff_side_effect: Exception | None = None,
        config: dict | None = None,
        live_content: str | None = None,
        resolve_credentials_side_effect: Exception | None = None,
    ):
        run = MagicMock()
        run.id = 42
        db = MagicMock()

        with tempfile.TemporaryDirectory() as tmp:
            ref_dir = Path(tmp) / "pyats-snapshots"
            ref_dir.mkdir()
            if reference_content is not None:
                (ref_dir / "lab.pyats-snapshot.json").write_text(
                    reference_content, encoding="utf-8"
                )

            with (
                patch(
                    "workflow_steps.compare_pyats_snapshot.executor.object_session",
                    return_value=db,
                ),
                patch(
                    "workflow_steps.compare_pyats_snapshot.executor.PyATSSourceConfigService"
                ) as config_service_cls,
                patch(
                    "workflow_steps.compare_pyats_snapshot.executor.service_factory"
                ) as service_factory_mock,
                patch("workflow_steps.compare_data.reference_reader.settings") as settings_mock,
            ):
                settings_mock.data_directory = Path(tmp)
                if resolve_credentials_side_effect is not None:
                    config_service_cls.return_value.resolve_credentials.side_effect = (
                        resolve_credentials_side_effect
                    )
                else:
                    config_service_cls.return_value.resolve_credentials.return_value = MagicMock()

                shim = MagicMock()
                if shim_diff_side_effect is not None:
                    shim.diff = AsyncMock(side_effect=shim_diff_side_effect)
                elif shim_diff_results is not None:
                    shim.diff = AsyncMock(side_effect=shim_diff_results)
                else:
                    shim.diff = AsyncMock(return_value=shim_diff_result or {})
                service_factory_mock.get_pyats_app_service.return_value = shim

                artifact_service = InMemoryArtifactService()
                artifact_ref = await artifact_service.store(
                    content=live_content
                    or json.dumps({"bgp": {"success": True, "data": {"peers": 2}}}),
                    kind="pyats_snapshot",
                    device_id="device-1",
                    run_id="run-uuid-1",
                    media_type="application/json",
                )
                if "pyats_snapshot" in device.parsed:
                    device = device.model_copy(
                        update={
                            "parsed": {
                                **device.parsed,
                                "pyats_snapshot": {
                                    **device.parsed["pyats_snapshot"],
                                    "artifact_ref": artifact_ref.model_dump(mode="json"),
                                },
                            }
                        }
                    )

                outcomes = await execute(
                    config=config or _BASE_CONFIG,
                    context=WorkflowContext(
                        run_id="run-uuid-1",
                        workflow_id="wf-1",
                        devices={"device-1": device},
                    ),
                    run=run,
                    artifact_service=artifact_service,
                    node_id=_NODE_ID,
                    device_sessions=MagicMock(),
                )
        return outcomes, shim, artifact_service

    async def test_match_routes_to_match_outcome(self) -> None:
        device = _device_with_snapshot(
            ArtifactRef(artifact_id="placeholder", kind="pyats_snapshot")
        )
        outcomes, shim, _ = await self._run(
            device=device,
            reference_content=json.dumps({"bgp": {"success": True, "data": {"peers": 2}}}),
            shim_diff_result={"identical": True, "diff": ""},
        )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(list(by_name["match"].context.devices), ["device-1"])
        self.assertEqual(by_name["mismatch"].context.devices, {})
        self.assertEqual(by_name["failure"].context.devices, {})

        comparison = by_name["match"].context.devices["device-1"].parsed[f"{_NODE_ID}.comparison"]
        self.assertTrue(comparison["matched"])
        self.assertEqual(comparison["features"], ["bgp"])
        self.assertEqual(comparison["mismatched_features"], [])
        counts = by_name["match"].context.metadata[f"{_NODE_ID}.comparison_counts"]
        self.assertEqual(counts, {"match": 1, "mismatch": 0, "failure": 0})

        shim.diff.assert_awaited_once()
        call_kwargs = shim.diff.call_args.kwargs
        self.assertEqual(call_kwargs["snapshot_a"], {"peers": 2})
        self.assertEqual(call_kwargs["snapshot_b"], {"peers": 2})
        self.assertEqual(call_kwargs["exclude_keys"], [])

    async def test_exclude_keys_passed_through_to_shim_diff(self) -> None:
        device = _device_with_snapshot(
            ArtifactRef(artifact_id="placeholder", kind="pyats_snapshot")
        )
        outcomes, shim, _ = await self._run(
            device=device,
            reference_content=json.dumps({"bgp": {"success": True, "data": {"peers": 2}}}),
            shim_diff_result={"identical": True, "diff": ""},
            config={**_BASE_CONFIG, "exclude_keys": ["updated", " last_change ", "", 5]},
        )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(list(by_name["match"].context.devices), ["device-1"])

        call_kwargs = shim.diff.call_args.kwargs
        self.assertEqual(call_kwargs["exclude_keys"], ["updated", "last_change", "5"])

    async def test_mismatch_routes_to_mismatch_outcome_and_stores_diff(self) -> None:
        device = _device_with_snapshot(
            ArtifactRef(artifact_id="placeholder", kind="pyats_snapshot")
        )
        outcomes, _, artifact_service = await self._run(
            device=device,
            reference_content=json.dumps({"bgp": {"success": True, "data": {"peers": 1}}}),
            shim_diff_result={"identical": False, "diff": "-peers: 1\n+peers: 2\n"},
        )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(list(by_name["mismatch"].context.devices), ["device-1"])
        device_out = by_name["mismatch"].context.devices["device-1"]
        comparison = device_out.parsed[f"{_NODE_ID}.comparison"]
        self.assertFalse(comparison["matched"])
        self.assertEqual(comparison["comparison_diff_key"], f"{_NODE_ID}.comparison_diff")
        self.assertEqual(comparison["mismatched_features"], ["bgp"])

        diff_map = device_out.parsed[f"{_NODE_ID}.comparison_diff"]
        diff_entry = diff_map["bgp"]
        self.assertEqual(diff_entry["kind"], "comparison_diff")
        self.assertEqual(diff_entry["feature"], "bgp")
        self.assertIn("artifact_ref", diff_entry)
        diff_text = await artifact_service.resolve(
            ArtifactRef.model_validate(diff_entry["artifact_ref"])
        )
        self.assertIn("peers", diff_text)

    async def test_multiple_features_all_match_routes_to_match(self) -> None:
        device = _device_with_snapshot(
            ArtifactRef(artifact_id="placeholder", kind="pyats_snapshot")
        )
        snapshot = json.dumps(
            {
                "bgp": {"success": True, "data": {"peers": 2}},
                "ospf": {"success": True, "data": {"areas": 1}},
            }
        )
        outcomes, shim, _ = await self._run(
            device=device,
            reference_content=snapshot,
            live_content=snapshot,
            config={**_BASE_CONFIG, "features": ["bgp", "ospf"]},
            shim_diff_results=[
                {"identical": True, "diff": ""},
                {"identical": True, "diff": ""},
            ],
        )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(list(by_name["match"].context.devices), ["device-1"])
        self.assertEqual(by_name["mismatch"].context.devices, {})
        comparison = by_name["match"].context.devices["device-1"].parsed[
            f"{_NODE_ID}.comparison"
        ]
        self.assertEqual(comparison["features"], ["bgp", "ospf"])
        self.assertEqual(comparison["mismatched_features"], [])
        self.assertEqual(shim.diff.await_count, 2)

    async def test_multiple_features_one_diff_routes_to_mismatch(self) -> None:
        device = _device_with_snapshot(
            ArtifactRef(artifact_id="placeholder", kind="pyats_snapshot")
        )
        live = json.dumps(
            {
                "bgp": {"success": True, "data": {"peers": 2}},
                "ospf": {"success": True, "data": {"areas": 2}},
            }
        )
        reference = json.dumps(
            {
                "bgp": {"success": True, "data": {"peers": 2}},
                "ospf": {"success": True, "data": {"areas": 1}},
            }
        )
        outcomes, _, _ = await self._run(
            device=device,
            reference_content=reference,
            live_content=live,
            config={**_BASE_CONFIG, "features": ["bgp", "ospf"]},
            shim_diff_results=[
                {"identical": True, "diff": ""},
                {"identical": False, "diff": "-areas: 1\n+areas: 2\n"},
            ],
        )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(list(by_name["mismatch"].context.devices), ["device-1"])
        self.assertEqual(by_name["match"].context.devices, {})
        device_out = by_name["mismatch"].context.devices["device-1"]
        comparison = device_out.parsed[f"{_NODE_ID}.comparison"]
        self.assertFalse(comparison["matched"])
        self.assertEqual(comparison["mismatched_features"], ["ospf"])

        diff_map = device_out.parsed[f"{_NODE_ID}.comparison_diff"]
        self.assertEqual(list(diff_map), ["ospf"])
        self.assertEqual(diff_map["ospf"]["feature"], "ospf")

    async def test_multiple_features_one_missing_on_reference_fails_device(self) -> None:
        device = _device_with_snapshot(
            ArtifactRef(artifact_id="placeholder", kind="pyats_snapshot")
        )
        live = json.dumps(
            {
                "bgp": {"success": True, "data": {"peers": 2}},
                "ospf": {"success": True, "data": {"areas": 1}},
            }
        )
        outcomes, _, _ = await self._run(
            device=device,
            reference_content=json.dumps({"bgp": {"success": True, "data": {"peers": 2}}}),
            live_content=live,
            config={**_BASE_CONFIG, "features": ["bgp", "ospf"]},
            shim_diff_results=[
                {"identical": True, "diff": ""},
                {"identical": True, "diff": ""},
            ],
        )

        failure_outcome = next(o for o in outcomes if o.name == "failure")
        self.assertEqual(list(failure_outcome.context.devices), ["device-1"])
        error = failure_outcome.context.devices["device-1"].errors[0]
        self.assertEqual(error.code, "missing_feature")
        self.assertIn("Reference", error.message)
        self.assertIn("ospf", error.message)

    async def test_missing_testbed_bag_fails_device(self) -> None:
        device = DeviceContext(id="device-1", name="lab", hostname="lab", status=DeviceStatus.OK)
        outcomes, _, _ = await self._run(
            device=device,
            reference_content='{"bgp": {"success": true, "data": {}}}',
        )
        failure_outcome = next(o for o in outcomes if o.name == "failure")
        error_code = failure_outcome.context.devices["device-1"].errors[0].code
        self.assertEqual(error_code, "missing_testbed")

    async def test_missing_live_content_fails_device(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            attribute_bags={"pyats_testbed": {"pyats_source_id": "lab-pyats"}},
            status=DeviceStatus.OK,
        )
        outcomes, _, _ = await self._run(
            device=device,
            reference_content='{"bgp": {"success": true, "data": {}}}',
        )
        failure_outcome = next(o for o in outcomes if o.name == "failure")
        error_code = failure_outcome.context.devices["device-1"].errors[0].code
        self.assertEqual(error_code, "missing_content")

    async def test_feature_missing_on_live_side_fails_device(self) -> None:
        device = _device_with_snapshot(
            ArtifactRef(artifact_id="placeholder", kind="pyats_snapshot")
        )
        outcomes, _, _ = await self._run(
            device=device,
            reference_content='{"bgp": {"success": true, "data": {}}}',
            config={**_BASE_CONFIG, "features": ["ospf"]},
        )
        failure_outcome = next(o for o in outcomes if o.name == "failure")
        error_code = failure_outcome.context.devices["device-1"].errors[0].code
        self.assertEqual(error_code, "missing_feature")
        message = failure_outcome.context.devices["device-1"].errors[0].message
        self.assertIn("Live", message)

    async def test_feature_missing_on_reference_side_fails_device(self) -> None:
        device = _device_with_snapshot(
            ArtifactRef(artifact_id="placeholder", kind="pyats_snapshot")
        )
        outcomes, _, _ = await self._run(
            device=device,
            reference_content=json.dumps({"ospf": {"success": True, "data": {}}}),
        )
        failure_outcome = next(o for o in outcomes if o.name == "failure")
        error_code = failure_outcome.context.devices["device-1"].errors[0].code
        self.assertEqual(error_code, "missing_feature")
        message = failure_outcome.context.devices["device-1"].errors[0].message
        self.assertIn("Reference", message)

    async def test_malformed_reference_json_fails_device(self) -> None:
        device = _device_with_snapshot(
            ArtifactRef(artifact_id="placeholder", kind="pyats_snapshot")
        )
        outcomes, _, _ = await self._run(
            device=device,
            reference_content="not valid json",
        )
        failure_outcome = next(o for o in outcomes if o.name == "failure")
        error_code = failure_outcome.context.devices["device-1"].errors[0].code
        self.assertEqual(error_code, "invalid_snapshot")

    async def test_missing_reference_file_fails_device(self) -> None:
        device = _device_with_snapshot(
            ArtifactRef(artifact_id="placeholder", kind="pyats_snapshot")
        )
        outcomes, _, _ = await self._run(device=device, reference_content=None)
        failure_outcome = next(o for o in outcomes if o.name == "failure")
        error_code = failure_outcome.context.devices["device-1"].errors[0].code
        self.assertEqual(error_code, "missing_reference")

    async def test_shim_error_fails_device(self) -> None:
        device = _device_with_snapshot(
            ArtifactRef(artifact_id="placeholder", kind="pyats_snapshot")
        )
        outcomes, _, _ = await self._run(
            device=device,
            reference_content=json.dumps({"bgp": {"success": True, "data": {"peers": 1}}}),
            shim_diff_side_effect=PyATSAPIError("shim unreachable"),
        )
        failure_outcome = next(o for o in outcomes if o.name == "failure")
        error_code = failure_outcome.context.devices["device-1"].errors[0].code
        self.assertEqual(error_code, "shim_error")

    async def test_source_resolution_error_fails_device(self) -> None:
        device = _device_with_snapshot(
            ArtifactRef(artifact_id="placeholder", kind="pyats_snapshot")
        )
        outcomes, _, _ = await self._run(
            device=device,
            reference_content=json.dumps({"bgp": {"success": True, "data": {"peers": 1}}}),
            resolve_credentials_side_effect=PyATSValidationError("no credential"),
        )
        failure_outcome = next(o for o in outcomes if o.name == "failure")
        error_code = failure_outcome.context.devices["device-1"].errors[0].code
        self.assertEqual(error_code, "source_error")

    async def test_missing_feature_config_raises_value_error(self) -> None:
        run = MagicMock()
        with self.assertRaises(ValueError):
            await execute(
                config={**_BASE_CONFIG, "features": []},
                context=WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1", devices={}),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id=_NODE_ID,
                device_sessions=MagicMock(),
            )

    async def test_missing_source_step_node_id_raises_value_error(self) -> None:
        run = MagicMock()
        with self.assertRaises(ValueError):
            await execute(
                config={**_BASE_CONFIG, "source_step_node_id": ""},
                context=WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1", devices={}),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id=_NODE_ID,
                device_sessions=MagicMock(),
            )

    async def test_no_devices_short_circuits(self) -> None:
        run = MagicMock()
        outcomes = await execute(
            config=_BASE_CONFIG,
            context=WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1", devices={}),
            run=run,
            artifact_service=InMemoryArtifactService(),
            node_id=_NODE_ID,
            device_sessions=MagicMock(),
        )
        names = {outcome.name for outcome in outcomes}
        self.assertEqual(names, {"match", "mismatch", "failure"})
        for outcome in outcomes:
            self.assertEqual(outcome.context.devices, {})


if __name__ == "__main__":
    unittest.main()
