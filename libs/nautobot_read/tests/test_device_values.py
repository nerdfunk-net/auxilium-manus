import pytest

from nautobot_read.client import NautobotError
from nautobot_read.networks import InvalidInputError
from tests.conftest import (
    DEVICE_ROW,
    UUID_DE,
    UUID_DEV2,
    error_text,
    run,
)

SECOND = {
    "id": UUID_DEV2, "name": "device-2", "serial": "",
    "location": {"id": UUID_DE, "name": "Germany"},
    "primary_ip4": None, "software_version": {"version": "17.9.4"},
}


async def test_serial_values_one_item_per_device(ctx, nautobot):
    nautobot.list_rows["devices"] = [DEVICE_ROW, SECOND]
    data = await run(ctx, "list_device_values", field="serial")
    call = nautobot.all_calls[-1]
    assert call["filters"] == {}
    assert "serial" in call["selection"] and "location" in call["selection"]
    assert data["field"] == "serial" and data["count"] == 2
    assert data["items"][0] == {
        "id": DEVICE_ROW["id"], "name": "device-1", "location": "Germany → Berlin", "value": "SN1",
    }
    # an empty serial is "no value", not an empty string
    assert data["items"][1]["value"] is None and data["items"][1]["location"] == "Germany"


async def test_each_field_reads_its_own_selection_and_value(ctx, nautobot):
    nautobot.list_rows["devices"] = [DEVICE_ROW, SECOND]
    expected = {
        "name": ("device-1", "device-2"),
        "primary_ip4": ("10.0.0.2/24", None),
        "location": ("Germany → Berlin", "Germany"),
        "software_version": (None, "17.9.4"),
    }
    for field, values in expected.items():
        data = await run(ctx, "list_device_values", field=field)
        assert tuple(item["value"] for item in data["items"]) == values, field
    assert "primary_ip4 { address }" in nautobot.all_calls[1]["selection"]
    assert "software_version { version }" in nautobot.all_calls[3]["selection"]


async def test_filters_are_resolved_like_list_devices(ctx, nautobot):
    nautobot.list_rows["devices"] = [DEVICE_ROW]
    data = await run(
        ctx, "list_device_values", field="serial", location="germany", role="network",
        status="active", tag="LAB", device_type="NETWORKA", platform="cisco ios",
    )
    assert nautobot.all_calls[-1]["filters"] == {
        "location": [UUID_DE], "role": ["Network"], "status": ["Active"], "tags": ["lab"],
        "device_type": ["networkA"], "platform": ["Cisco IOS"],
    }
    assert data["applied_filters"]["location"] == "Germany"


async def test_unknown_filter_value_explains_what_exists(ctx, nautobot):
    text = await error_text(ctx, "list_device_values", field="serial", role="router")
    assert "No dcim.device role 'router'" in text
    assert nautobot.all_calls == []


async def test_unknown_field_is_refused(ctx):
    with pytest.raises(InvalidInputError):
        await run(ctx, "list_device_values", field="comments")


async def test_more_than_the_cap_asks_for_a_filter(ctx, nautobot):
    nautobot.too_many_devices = True
    text = await error_text(ctx, "list_device_values", field="serial")
    assert "filter" in text and "5000" in text


async def test_the_cap_is_passed_to_the_paging(ctx, nautobot):
    await run(ctx, "list_device_values", field="serial", max_items=123)
    assert nautobot.all_calls[-1]["options"]["max_items"] == 123


async def test_a_software_version_failure_names_the_version_requirement(ctx, nautobot):
    nautobot.devices_error = NautobotError("Nautobot could not answer the query")
    text = await error_text(ctx, "list_device_values", field="software_version")
    assert "Nautobot 2.2" in text and "could not answer" in text


async def test_another_field_failure_is_not_blamed_on_the_version(ctx, nautobot):
    nautobot.devices_error = NautobotError("Nautobot could not answer the query")
    text = await error_text(ctx, "list_device_values", field="serial")
    assert text == "Nautobot could not answer the query"


async def test_max_items_is_bounded(ctx):
    for bad in (0, 100_001):
        with pytest.raises(InvalidInputError):
            await run(ctx, "list_device_values", field="serial", max_items=bad)
