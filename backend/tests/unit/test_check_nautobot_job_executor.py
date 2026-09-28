"""Unit tests for workflow_steps/check_nautobot_job/executor.py."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from models.workflow_context import DeviceContext
from workflow_steps.check_nautobot_job import executor as mod


def _device(did: str = "d1", **bags: object) -> DeviceContext:
    return DeviceContext(
        id=did, name=did, hostname=did, primary_ip4="10.0.0.1", attribute_bags=bags
    )


class CheckJobForDeviceStatusShapeTests(unittest.IsolatedAsyncioTestCase):
    async def test_nested_status_object_is_treated_as_success(self) -> None:
        jobs_service = AsyncMock()
        jobs_service.get_job_result = AsyncMock(
            return_value={"status": {"value": "SUCCESS", "label": "SUCCESS"}}
        )
        parsed = mod._ParsedConfig(
            source_id="src-1",
            job_uuid_expr="jr-1",
            max_checks=1,
            interval_seconds=0,
            bag_name="nautobot_job",
        )
        device = _device("d1")
        key, updated, ok = await mod._check_job_for_device(
            device_key="d1",
            device=device,
            node_id="n",
            jobs_service=jobs_service,
            parsed=parsed,
            run_id=None,
        )
        self.assertTrue(ok)
        self.assertEqual(updated.attribute_bags["nautobot_job"]["status"], "SUCCESS")

    async def test_nested_status_object_failure_value(self) -> None:
        jobs_service = AsyncMock()
        jobs_service.get_job_result = AsyncMock(
            return_value={"status": {"value": "FAILURE", "label": "FAILURE"}}
        )
        parsed = mod._ParsedConfig(
            source_id="src-1",
            job_uuid_expr="jr-1",
            max_checks=1,
            interval_seconds=0,
            bag_name="nautobot_job",
        )
        device = _device("d1")
        key, failed, ok = await mod._check_job_for_device(
            device_key="d1",
            device=device,
            node_id="n",
            jobs_service=jobs_service,
            parsed=parsed,
            run_id=None,
        )
        self.assertFalse(ok)
        self.assertIn("FAILURE", failed.errors[0].message)

    async def test_plain_string_status_still_works(self) -> None:
        jobs_service = AsyncMock()
        jobs_service.get_job_result = AsyncMock(return_value={"status": "SUCCESS"})
        parsed = mod._ParsedConfig(
            source_id="src-1",
            job_uuid_expr="jr-1",
            max_checks=1,
            interval_seconds=0,
            bag_name="nautobot_job",
        )
        device = _device("d1")
        key, updated, ok = await mod._check_job_for_device(
            device_key="d1",
            device=device,
            node_id="n",
            jobs_service=jobs_service,
            parsed=parsed,
            run_id=None,
        )
        self.assertTrue(ok)

    async def test_missing_status_exhausts_checks_and_fails(self) -> None:
        jobs_service = AsyncMock()
        jobs_service.get_job_result = AsyncMock(return_value={"status": {"value": None}})
        parsed = mod._ParsedConfig(
            source_id="src-1",
            job_uuid_expr="jr-1",
            max_checks=1,
            interval_seconds=0,
            bag_name="nautobot_job",
        )
        device = _device("d1")
        key, failed, ok = await mod._check_job_for_device(
            device_key="d1",
            device=device,
            node_id="n",
            jobs_service=jobs_service,
            parsed=parsed,
            run_id=None,
        )
        self.assertFalse(ok)
        self.assertIn("did not reach a terminal state", failed.errors[0].message)


class CustomBagNameTests(unittest.IsolatedAsyncioTestCase):
    async def test_custom_bag_name_leaves_default_bag_untouched(self) -> None:
        jobs_service = AsyncMock()
        jobs_service.get_job_result = AsyncMock(return_value={"status": "SUCCESS"})
        parsed = mod._ParsedConfig(
            source_id="src-1",
            job_uuid_expr="jr-2",
            max_checks=1,
            interval_seconds=0,
            bag_name="update_job",
        )
        device = _device("d1", nautobot_job={"job_result_id": "jr-1", "status": "SUCCESS"})
        key, updated, ok = await mod._check_job_for_device(
            device_key="d1",
            device=device,
            node_id="n",
            jobs_service=jobs_service,
            parsed=parsed,
            run_id=None,
        )
        self.assertTrue(ok)
        self.assertEqual(updated.attribute_bags["nautobot_job"]["job_result_id"], "jr-1")
        self.assertEqual(updated.attribute_bags["update_job"]["job_result_id"], "jr-2")

    async def test_matching_bag_name_merges_onto_start_job_bag(self) -> None:
        jobs_service = AsyncMock()
        jobs_service.get_job_result = AsyncMock(return_value={"status": "SUCCESS"})
        parsed = mod._ParsedConfig(
            source_id="src-1",
            job_uuid_expr="jr-1",
            max_checks=1,
            interval_seconds=0,
            bag_name="onboard_job",
        )
        device = _device(
            "d1", onboard_job={"job_result_id": "jr-1", "job_id": "job-1", "request": {}}
        )
        key, updated, ok = await mod._check_job_for_device(
            device_key="d1",
            device=device,
            node_id="n",
            jobs_service=jobs_service,
            parsed=parsed,
            run_id=None,
        )
        self.assertTrue(ok)
        bag = updated.attribute_bags["onboard_job"]
        self.assertEqual(bag["job_id"], "job-1")
        self.assertEqual(bag["status"], "SUCCESS")


if __name__ == "__main__":
    unittest.main()
