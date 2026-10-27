import pytest

from nautobot_mcp.vocabularies import (
    AmbiguousNameError,
    LocationDirectory,
    VocabularyCache,
    roles_spec,
)
from nautobot_mcp.vocabulary import UnknownNameError

UUID_A = "11111111-1111-1111-1111-111111111111"
UUID_B = "22222222-2222-2222-2222-222222222222"
UUID_C = "33333333-3333-3333-3333-333333333333"
UUID_D = "44444444-4444-4444-4444-444444444444"
ROWS = [
    {"id": UUID_A, "name": "Germany", "location_type": {"name": "Country"}, "parent": None},
    {"id": UUID_B, "name": "Berlin", "location_type": {"name": "City"}, "parent": {"id": UUID_A}},
    {"id": UUID_C, "name": "Berlin", "location_type": {"name": "Site"}, "parent": {"id": UUID_D}},
    {"id": UUID_D, "name": "Texas", "location_type": {"name": "State"}, "parent": None},
]


@pytest.fixture
def directory():
    return LocationDirectory.from_rows(ROWS)


def test_unique_name_resolves_to_record_with_path(directory):
    record = directory.resolve("germany")
    assert (record.id, record.path, record.location_type) == (UUID_A, "Germany", "Country")


def test_full_path_resolves_with_either_separator(directory):
    assert directory.resolve("Germany → Berlin").id == UUID_B
    assert directory.resolve("texas > berlin").id == UUID_C


def test_uuid_resolves_when_known_and_fails_when_unknown(directory):
    assert directory.resolve(UUID_C.upper()).id == UUID_C
    with pytest.raises(UnknownNameError):
        directory.resolve("99999999-9999-9999-9999-999999999999")


def test_duplicate_name_is_ambiguous_and_lists_paths_and_ids(directory):
    with pytest.raises(AmbiguousNameError) as exc:
        directory.resolve("Berlin")
    message = str(exc.value)
    assert "'Berlin' matches 2 locations" in message
    assert f"Germany → Berlin (City, id {UUID_B})" in message
    assert f"Texas → Berlin (Site, id {UUID_C})" in message


def test_unknown_name_suggests_closest(directory):
    with pytest.raises(UnknownNameError, match="Closest: 'Germany'"):
        directory.resolve("Germeny")


def test_names_and_paths_listing(directory):
    assert directory.names == ("Germany", "Berlin", "Texas")
    assert len(directory.records) == 4


class FakeClient:
    def __init__(self):
        self.calls = []

    async def list_all(self, root, selection, filters=None, **_):
        self.calls.append((root, filters))
        if root == "locations":
            return ROWS
        return [{"name": "Network"}, {"name": "Server"}]


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


async def test_cache_loads_once_within_ttl_and_reloads_after():
    client, clock = FakeClient(), Clock()
    cache = VocabularyCache(client, ttl_seconds=60, clock=clock)
    first = await cache.get(roles_spec("dcim.device"))
    assert first.names == ("Network", "Server")
    clock.now = 59
    await cache.get(roles_spec("dcim.device"))
    assert len(client.calls) == 1
    assert client.calls[0] == ("roles", {"content_types": ["dcim.device"]})
    clock.now = 61
    await cache.get(roles_spec("dcim.device"))
    assert len(client.calls) == 2


async def test_cache_keeps_specs_apart_and_caches_locations():
    client, clock = FakeClient(), Clock()
    cache = VocabularyCache(client, ttl_seconds=60, clock=clock)
    await cache.get(roles_spec("dcim.device"))
    await cache.get(roles_spec("ipam.ipaddress"))
    assert len(client.calls) == 2
    locations = await cache.locations()
    assert await cache.locations() is locations
    assert len(client.calls) == 3


async def test_invalidate_forces_a_reload():
    client, clock = FakeClient(), Clock()
    cache = VocabularyCache(client, ttl_seconds=60, clock=clock)
    await cache.get(roles_spec("dcim.device"))
    cache.invalidate()
    await cache.get(roles_spec("dcim.device"))
    assert len(client.calls) == 2


def test_specs_filter_by_content_type():
    from nautobot_mcp.vocabularies import statuses_spec, tags_spec

    assert statuses_spec("dcim.device").filters == (("content_types", ("dcim.device",)),)
    assert tags_spec("dcim.device").root == "tags"


def test_name_containing_the_separator_still_resolves_and_unknown_paths_fail():
    rows = [{"id": UUID_A, "name": "A > B", "location_type": None, "parent": None}]
    odd = LocationDirectory.from_rows(rows)
    assert odd.resolve("A > B").id == UUID_A
    with pytest.raises(UnknownNameError):
        odd.resolve("Nowhere → Else")
