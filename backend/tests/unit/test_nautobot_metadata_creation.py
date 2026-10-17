"""Tests for MetadataCreationService (fake Nautobot REST, no network)."""

from __future__ import annotations

import itertools
import unittest
from typing import Any
from urllib.parse import parse_qs, urlsplit

from services.nautobot.common.exceptions import NautobotAPIError
from services.nautobot.metadata_creation import (
    MetadataConflictError,
    MetadataCreationService,
    MetadataReferenceNotFoundError,
)

_LOCATION_TYPE_ID = "11111111-1111-1111-1111-111111111111"
_STATUS_ID = "22222222-2222-2222-2222-222222222222"
_MANUFACTURER_ID = "33333333-3333-3333-3333-333333333333"
_ROLE_ID = "44444444-4444-4444-4444-444444444444"
_PLATFORM_ID = "55555555-5555-5555-5555-555555555555"
_PARENT_ID = "66666666-6666-6666-6666-666666666666"


def _seed() -> dict[str, list[dict[str, Any]]]:
    return {
        "dcim/location-types": [{"id": _LOCATION_TYPE_ID, "name": "Site"}],
        "extras/statuses": [{"id": _STATUS_ID, "name": "Active"}],
        "dcim/manufacturers": [{"id": _MANUFACTURER_ID, "name": "Cisco"}],
        "extras/roles": [{"id": _ROLE_ID, "name": "Access Switch"}],
        "dcim/platforms": [{"id": _PLATFORM_ID, "name": "cisco_ios"}],
        "dcim/locations": [{"id": _PARENT_ID, "name": "Region-1", "location_type": {"id": "x"}}],
        "dcim/device-types": [],
    }


class FakeNautobot:
    """In-memory REST stand-in; GETs filter by ``name__ic``/``model__ic`` (icontains) only."""

    def __init__(
        self, data: dict[str, list[dict[str, Any]]], *, post_error: Exception | None = None
    ):
        self.data = data
        self.post_error = post_error
        self.calls: list[tuple[str, str, Any]] = []
        self._ids = (f"aaaaaaaa-0000-0000-0000-{n:012d}" for n in itertools.count(1))

    async def graphql_query(self, query: str, variables: Any = None) -> dict[str, Any]:
        raise AssertionError("service must use REST only")

    async def rest_request(
        self, endpoint: str, method: str = "GET", data: Any = None
    ) -> dict[str, Any]:
        self.calls.append((method, endpoint, data))
        parts = urlsplit(endpoint)
        collection = parts.path.strip("/")
        query = parse_qs(parts.query)
        if method == "POST":
            if self.post_error is not None:
                error, self.post_error = self.post_error, None
                raise error
            created = {"id": next(self._ids), **data}
            self.data[collection].append(created)
            return created
        items = self.data[collection]
        for key in ("name", "model"):
            if f"{key}__ic" in query:
                needle = query[f"{key}__ic"][0].lower()
                items = [i for i in items if needle in str(i.get(key, "")).lower()]
        return {"count": len(items), "results": items}

    def posts(self) -> list[tuple[str, Any]]:
        return [(endpoint, data) for method, endpoint, data in self.calls if method == "POST"]


class EnsureLocationTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_location_with_resolved_ids(self) -> None:
        fake = FakeNautobot(_seed())
        result = await MetadataCreationService(fake).ensure_location(
            location_type="site", name="Berlin", status="active", description="HQ"
        )

        self.assertTrue(result.created)
        self.assertEqual(result.name, "Berlin")
        ((endpoint, payload),) = fake.posts()
        self.assertEqual(endpoint, "dcim/locations/")
        self.assertEqual(payload["location_type"], _LOCATION_TYPE_ID)
        self.assertEqual(payload["status"], _STATUS_ID)
        self.assertEqual(payload["name"], "Berlin")
        self.assertEqual(payload["description"], "HQ")
        self.assertNotIn("parent", payload)

    async def test_status_lookup_is_scoped_to_locations(self) -> None:
        fake = FakeNautobot(_seed())
        await MetadataCreationService(fake).ensure_location(
            location_type="Site", name="Berlin", status="Active"
        )
        status_calls = [e for m, e, _ in fake.calls if e.startswith("extras/statuses")]
        self.assertTrue(status_calls)
        self.assertTrue(all("content_types=dcim.location" in e for e in status_calls))

    async def test_reuses_existing_location_without_posting(self) -> None:
        seed = _seed()
        seed["dcim/locations"].append(
            {
                "id": "77777777-7777-7777-7777-777777777777",
                "name": "Berlin",
                "location_type": {"id": _LOCATION_TYPE_ID},
            }
        )
        fake = FakeNautobot(seed)
        result = await MetadataCreationService(fake).ensure_location(
            location_type="Site", name="Berlin", status="Active"
        )

        self.assertFalse(result.created)
        self.assertEqual(result.id, "77777777-7777-7777-7777-777777777777")
        self.assertEqual(fake.posts(), [])

    async def test_same_name_under_other_type_is_not_a_match(self) -> None:
        seed = _seed()
        seed["dcim/locations"].append(
            {
                "id": "88888888-8888-8888-8888-888888888888",
                "name": "Berlin",
                "location_type": {"id": "other-type"},
            }
        )
        fake = FakeNautobot(seed)
        result = await MetadataCreationService(fake).ensure_location(
            location_type="Site", name="Berlin", status="Active"
        )
        self.assertTrue(result.created)

    async def test_parent_is_resolved_and_sent(self) -> None:
        fake = FakeNautobot(_seed())
        await MetadataCreationService(fake).ensure_location(
            location_type="Site", name="Berlin", status="Active", parent="Region-1"
        )
        ((_, payload),) = fake.posts()
        self.assertEqual(payload["parent"], _PARENT_ID)

    async def test_uuid_inputs_pass_through_without_lookup(self) -> None:
        fake = FakeNautobot(_seed())
        await MetadataCreationService(fake).ensure_location(
            location_type=_LOCATION_TYPE_ID, name="Berlin", status=_STATUS_ID
        )
        self.assertFalse(any(e.startswith("dcim/location-types") for _, e, _ in fake.calls))
        self.assertFalse(any(e.startswith("extras/statuses") for _, e, _ in fake.calls))

    async def test_unknown_location_type_raises(self) -> None:
        with self.assertRaises(MetadataReferenceNotFoundError) as ctx:
            await MetadataCreationService(FakeNautobot(_seed())).ensure_location(
                location_type="Campus", name="Berlin", status="Active"
            )
        self.assertIn("Campus", str(ctx.exception))

    async def test_unknown_parent_raises(self) -> None:
        with self.assertRaises(MetadataReferenceNotFoundError):
            await MetadataCreationService(FakeNautobot(_seed())).ensure_location(
                location_type="Site", name="Berlin", status="Active", parent="Nowhere"
            )

    async def test_duplicate_race_returns_existing(self) -> None:
        seed = _seed()
        fake = FakeNautobot(seed)
        service = MetadataCreationService(fake)

        original_post = fake.rest_request

        async def racing(endpoint: str, method: str = "GET", data: Any = None) -> dict[str, Any]:
            if method == "POST":
                seed["dcim/locations"].append(
                    {
                        "id": "99999999-9999-9999-9999-999999999999",
                        "name": "Berlin",
                        "location_type": {"id": _LOCATION_TYPE_ID},
                    }
                )
                raise NautobotAPIError("The fields location_type, name must make a unique set.")
            return await original_post(endpoint, method, data)

        fake.rest_request = racing  # type: ignore[method-assign]
        result = await service.ensure_location(location_type="Site", name="Berlin", status="Active")
        self.assertFalse(result.created)
        self.assertEqual(result.id, "99999999-9999-9999-9999-999999999999")

    async def test_non_duplicate_api_error_propagates(self) -> None:
        fake = FakeNautobot(_seed(), post_error=NautobotAPIError("500 server exploded"))
        with self.assertRaises(NautobotAPIError):
            await MetadataCreationService(fake).ensure_location(
                location_type="Site", name="Berlin", status="Active"
            )


class LocationIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_top_level_request_ignores_same_name_under_a_parent(self) -> None:
        seed = _seed()
        seed["dcim/locations"].append(
            {
                "id": "77777777-7777-7777-7777-777777777777",
                "name": "Berlin",
                "location_type": {"id": _LOCATION_TYPE_ID},
                "parent": {"id": _PARENT_ID},
            }
        )
        fake = FakeNautobot(seed)
        result = await MetadataCreationService(fake).ensure_location(
            location_type="Site", name="Berlin", status="Active"
        )
        self.assertTrue(result.created)

    async def test_same_name_other_type_conflict_gives_clear_error(self) -> None:
        seed = _seed()
        seed["dcim/locations"].append(
            {
                "id": "88888888-8888-8888-8888-888888888888",
                "name": "Berlin",
                "location_type": {"id": "other-type"},
            }
        )
        fake = FakeNautobot(seed)
        original = fake.rest_request

        async def rejecting(endpoint: str, method: str = "GET", data: Any = None) -> dict[str, Any]:
            if method == "POST":
                raise NautobotAPIError("The fields parent, name must make a unique set.")
            return await original(endpoint, method, data)

        fake.rest_request = rejecting  # type: ignore[method-assign]
        with self.assertRaises(MetadataConflictError) as ctx:
            await MetadataCreationService(fake).ensure_location(
                location_type="Site", name="Berlin", status="Active"
            )
        self.assertIn("different location type", str(ctx.exception))


class EnsureDeviceTypeTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_device_type_and_returns_references(self) -> None:
        fake = FakeNautobot(_seed())
        result = await MetadataCreationService(fake).ensure_device_type(
            manufacturer="cisco",
            model="C9300-24T",
            height=1,
            role="access switch",
            platform="cisco_ios",
        )

        self.assertTrue(result.created)
        self.assertEqual(result.model, "C9300-24T")
        self.assertEqual(result.manufacturer, "Cisco")
        self.assertEqual(result.role, "Access Switch")
        self.assertEqual(result.platform, "cisco_ios")
        self.assertEqual(result.role_id, _ROLE_ID)
        self.assertEqual(result.platform_id, _PLATFORM_ID)
        ((endpoint, payload),) = fake.posts()
        self.assertEqual(endpoint, "dcim/device-types/")
        self.assertEqual(
            payload, {"manufacturer": _MANUFACTURER_ID, "model": "C9300-24T", "u_height": 1}
        )

    async def test_role_lookup_is_scoped_to_devices(self) -> None:
        fake = FakeNautobot(_seed())
        await MetadataCreationService(fake).ensure_device_type(
            manufacturer="Cisco", model="X", height=2, role="Access Switch"
        )
        role_calls = [e for _, e, _ in fake.calls if e.startswith("extras/roles")]
        self.assertTrue(all("content_types=dcim.device" in e for e in role_calls))

    async def test_platform_is_optional(self) -> None:
        fake = FakeNautobot(_seed())
        result = await MetadataCreationService(fake).ensure_device_type(
            manufacturer="Cisco", model="X", height=1, role="Access Switch"
        )
        self.assertIsNone(result.platform)
        self.assertFalse(any(e.startswith("dcim/platforms") for _, e, _ in fake.calls))

    async def test_reuses_existing_device_type(self) -> None:
        seed = _seed()
        seed["dcim/device-types"].append(
            {
                "id": "12121212-1212-1212-1212-121212121212",
                "model": "X",
                "manufacturer": {"id": _MANUFACTURER_ID},
                "u_height": 1,
            }
        )
        fake = FakeNautobot(seed)
        result = await MetadataCreationService(fake).ensure_device_type(
            manufacturer="Cisco", model="X", height=1, role="Access Switch"
        )
        self.assertFalse(result.created)
        self.assertEqual(fake.posts(), [])

    async def test_unknown_references_raise(self) -> None:
        service = MetadataCreationService(FakeNautobot(_seed()))
        for kwargs in (
            {"manufacturer": "Juniper", "role": "Access Switch", "platform": None},
            {"manufacturer": "Cisco", "role": "Core", "platform": None},
            {"manufacturer": "Cisco", "role": "Access Switch", "platform": "nxos"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(MetadataReferenceNotFoundError):
                await service.ensure_device_type(model="X", height=1, **kwargs)


if __name__ == "__main__":
    unittest.main()
