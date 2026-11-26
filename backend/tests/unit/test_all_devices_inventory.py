"""``all_devices`` end to end: tree -> operations -> evaluator -> devices, and what happens when
the part that subtracts fails (it must never turn "all but X" into "all")."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from core.domain_exceptions import InvalidFilterInputError
from models.sources_nautobot import DeviceInfo
from services.nautobot.credentials import NautobotCredentials
from services.sources.nautobot.evaluator import (
    InventoryEvaluationError,
    NautobotSourceEvaluator,
)
from services.sources.nautobot.source_service import NautobotSourceService
from utils.inventory_converter import (
    tree_to_operations,
    validate_conditions_for_save,
)

_CREDS = NautobotCredentials(url="http://nb.test", token="tok")


def _dev(did: str, **kw) -> DeviceInfo:
    return DeviceInfo(id=did, name=kw.pop("name", did), **kw)


def _cond(field: str, value: str, operator: str = "equals") -> dict:
    return {"field": field, "operator": operator, "value": value}


def _not_group(*conditions: dict) -> dict:
    return {"type": "group", "logic": "NOT", "internalLogic": "AND", "items": list(conditions)}


# "All devices but the device LAB.local.zz", as the builder and the assistant save it.
_ALL_BUT_LAB = {
    "internalLogic": "AND",
    "items": [_cond("all_devices", "true"), _not_group(_cond("name", "LAB.local.zz"))],
}
_FLEET = [_dev("a"), _dev("lab", name="LAB.local.zz"), _dev("c")]


def _service(name_query: AsyncMock | None = None) -> NautobotSourceService:
    svc = NautobotSourceService(MagicMock(), _CREDS, persistence_service=MagicMock())
    qs = MagicMock()
    qs._query_all_devices = AsyncMock(return_value=_FLEET)
    qs._query_devices_by_name = name_query or AsyncMock(return_value=[_FLEET[1]])
    for name in (
        "_query_devices_by_location",
        "_query_devices_by_role",
        "_query_devices_by_status",
        "_query_devices_by_tag",
        "_query_devices_by_devicetype",
        "_query_devices_by_manufacturer",
        "_query_devices_by_platform",
        "_query_devices_by_has_primary",
    ):
        setattr(qs, name, AsyncMock(return_value=[]))
    svc.query_service = qs
    svc.evaluator = NautobotSourceEvaluator(qs)
    return svc


class AllButOneDeviceTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_two_operation_tree_subtracts_the_excluded_device(self) -> None:
        operations = tree_to_operations(_ALL_BUT_LAB)
        # the converter emits the positive operation and the NOT group separately
        self.assertEqual([o.operation_type for o in operations], ["AND", "NOT"])

        devices, _ = await _service().preview_inventory(operations, strict=True)

        self.assertEqual(sorted(d.id for d in devices), ["a", "c"])

    async def test_a_failed_exclusion_is_refused_when_strict(self) -> None:
        svc = _service(AsyncMock(side_effect=RuntimeError("nautobot down")))

        with self.assertRaises(InventoryEvaluationError) as ctx:
            await svc.preview_inventory(tree_to_operations(_ALL_BUT_LAB), strict=True)

        self.assertIn("name equals", str(ctx.exception))
        self.assertNotIn("nautobot down", str(ctx.exception))  # no raw exception text

    async def test_the_inventory_page_preview_still_degrades(self) -> None:
        # Not strict: the builder shows what it can and the failure is on the evaluator.
        svc = _service(AsyncMock(side_effect=RuntimeError("nautobot down")))

        devices, _ = await svc.preview_inventory(tree_to_operations(_ALL_BUT_LAB))

        self.assertEqual(len(devices), 3)
        self.assertEqual(svc.evaluator.failures, ["name equals"])

    async def test_strict_only_looks_at_failures_of_its_own_call(self) -> None:
        svc = _service()
        svc.evaluator.failures.append("something older")

        devices, _ = await svc.preview_inventory(tree_to_operations(_ALL_BUT_LAB), strict=True)

        self.assertEqual(len(devices), 2)

    async def test_a_saved_inventory_with_a_failed_exclusion_does_not_resolve(self) -> None:
        svc = _service(AsyncMock(side_effect=RuntimeError("nautobot down")))
        svc._persistence_service.get_inventory_as = MagicMock(
            return_value={
                "inventory_type": "filter",
                "is_active": True,
                "conditions": [{"version": 2, "tree": _ALL_BUT_LAB}],
            }
        )

        with self.assertRaises(InventoryEvaluationError):
            await svc.resolve_saved_inventory_devices_by_id(1, "alice")

    async def test_every_saved_inventory_resolver_is_strict(self) -> None:
        inventory = {
            "inventory_type": "filter",
            "conditions": [{"version": 2, "tree": _ALL_BUT_LAB}],
            "name": "n",
        }
        failing = AsyncMock(side_effect=RuntimeError("nautobot down"))
        for resolve in (
            lambda s: s.resolve_saved_inventory_devices(inventory),
            lambda s: s.resolve_saved_inventory_ids(inventory, 1),
            lambda s: s.resolve_saved_inventory_detailed(inventory, 1),
        ):
            with self.subTest(resolve=resolve):
                with self.assertRaises(InventoryEvaluationError):
                    await resolve(_service(failing))


class ValidateConditionsForSaveTests(unittest.TestCase):
    @staticmethod
    def _saved(tree: dict) -> list[dict]:
        return [{"version": 2, "tree": tree}]

    def test_all_but_one_device_is_accepted(self) -> None:
        validate_conditions_for_save(self._saved(_ALL_BUT_LAB))

    def test_all_devices_under_or_beside_a_condition_is_refused(self) -> None:
        tree = {
            "internalLogic": "OR",
            "items": [_cond("all_devices", "true"), _cond("location", "City A", "not_equals")],
        }
        with self.assertRaises(InvalidFilterInputError) as ctx:
            validate_conditions_for_save(self._saved(tree))
        self.assertIn("OR", ctx.exception.detail)

    def test_all_devices_under_or_with_only_an_excluding_group_is_accepted(self) -> None:
        tree = {
            "internalLogic": "OR",
            "items": [_cond("all_devices", "true"), _not_group(_cond("name", "x"))],
        }
        validate_conditions_for_save(self._saved(tree))

    def test_a_wrong_value_is_refused(self) -> None:
        for value in ("false", ""):
            with self.subTest(value=value):
                tree = {"internalLogic": "AND", "items": [_cond("all_devices", value)]}
                with self.assertRaises(InvalidFilterInputError):
                    validate_conditions_for_save(self._saved(tree))

    def test_trees_without_all_devices_and_odd_shapes_are_left_alone(self) -> None:
        validate_conditions_for_save(
            self._saved({"internalLogic": "OR", "items": [_cond("role", "a"), _cond("role", "b")]})
        )
        validate_conditions_for_save(None)
        validate_conditions_for_save([{"version": 1}, "x"])
