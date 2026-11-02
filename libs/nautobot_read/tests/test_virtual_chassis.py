import pytest

from nautobot_read.client import NautobotError
from nautobot_read.networks import InvalidInputError
from nautobot_read.queries import virtual_chassis as vc
from tests.conftest import UUID_DEV1, UUID_VC, VC_ROW, error_text, run


async def test_list_returns_one_compact_row_per_stack_in_stack_order(ctx, nautobot):
    nautobot.list_rows["virtual_chassis"] = [VC_ROW]
    data = await run(ctx, "list_virtual_chassis", name_contains="lab")
    call = nautobot.page_calls[-1]
    assert call["root"] == "virtual_chassis" and call["filters"] == {"name__ic": ["lab"]}
    assert data["items"] == [{
        "id": UUID_VC, "name": "LAB.local.zz", "member_count": 2, "master": "LAB.local.zz",
        "master_primary_ip4": "10.0.0.1/24", "members": ["LAB.local.zz", "LAB:2.local.zz"],
    }]
    assert data["applied_filters"] == {"name_contains": "lab"}


async def test_list_without_filter_sends_none_and_reports_paging(ctx, nautobot):
    nautobot.has_more = True
    data = await run(ctx, "list_virtual_chassis", limit=5, offset=10)
    assert nautobot.page_calls[-1]["filters"] == {}
    assert data["has_more"] is True and data["offset"] == 10


async def test_list_rejects_out_of_range_paging(ctx):
    with pytest.raises(InvalidInputError):
        await run(ctx, "list_virtual_chassis", limit=0)


async def test_stack_without_members_or_master_is_data_not_an_error(ctx, nautobot):
    nautobot.list_rows["virtual_chassis"] = [{"id": UUID_VC, "name": "EMPTY", "members": None}]
    data = await run(ctx, "list_virtual_chassis")
    assert data["items"][0]["member_count"] == 0
    assert data["items"][0]["master"] is None and data["items"][0]["master_primary_ip4"] is None


async def test_get_by_name_resolves_case_insensitively_and_lists_members(ctx, nautobot):
    nautobot.list_rows["virtual_chassis"] = [VC_ROW]
    data = await run(ctx, "get_virtual_chassis", virtual_chassis="lab.LOCAL.zz")
    assert nautobot.page_calls[-1]["filters"] == {"name": ["LAB.local.zz"]}
    assert [m["name"] for m in data["members"]] == ["LAB.local.zz", "LAB:2.local.zz"]
    master, other = data["members"]
    assert master == {
        "id": UUID_DEV1, "name": "LAB.local.zz", "position": 1, "priority": 15,
        "serial": "SN1", "device_type": "C9300-48P", "primary_ip4": "10.0.0.1/24",
        "is_master": True,
    }
    assert other["is_master"] is False and other["primary_ip4"] is None
    assert data["member_count"] == 2


async def test_get_by_id_filters_on_id(ctx, nautobot):
    nautobot.list_rows["virtual_chassis"] = [VC_ROW]
    await run(ctx, "get_virtual_chassis", virtual_chassis=UUID_VC.upper())
    assert nautobot.page_calls[-1]["filters"] == {"id": [UUID_VC]}
    assert nautobot.page_calls[-1]["limit"] == 2


async def test_get_refuses_a_row_the_filter_did_not_select(ctx, nautobot):
    # A filter that Nautobot accepts but ignores returns the first stack of the instance.
    other = {**VC_ROW, "id": "88888888-8888-8888-8888-888888888888", "name": "OTHER"}
    nautobot.list_rows["virtual_chassis"] = [other]
    by_name = await error_text(ctx, "get_virtual_chassis", virtual_chassis="LAB.local.zz")
    by_id = await error_text(ctx, "get_virtual_chassis", virtual_chassis=UUID_VC)
    assert "No virtual chassis 'LAB.local.zz'" in by_name
    assert f"No virtual chassis '{UUID_VC}'" in by_id


async def test_get_reports_two_stacks_with_the_same_name(ctx, nautobot):
    twin = {**VC_ROW, "id": "88888888-8888-8888-8888-888888888888"}
    nautobot.list_rows["virtual_chassis"] = [VC_ROW, twin]
    text = await error_text(ctx, "get_virtual_chassis", virtual_chassis="LAB.local.zz")
    assert "matches 2 virtual chassis" in text and twin["id"] in text and UUID_VC in text


async def test_get_takes_an_exact_spelling_before_a_case_insensitive_one(ctx, nautobot):
    nautobot.vc_names = [{"name": "Lab"}, {"name": "LAB"}]
    nautobot.list_rows["virtual_chassis"] = [{**VC_ROW, "name": "LAB"}]
    await run(ctx, "get_virtual_chassis", virtual_chassis="LAB")
    assert nautobot.page_calls[-1]["filters"] == {"name": ["LAB"]}


async def test_get_reports_a_case_only_match_that_fits_two_stacks(ctx, nautobot):
    nautobot.vc_names = [{"name": "Lab"}, {"name": "LAB"}]
    text = await error_text(ctx, "get_virtual_chassis", virtual_chassis="lab")
    assert "matches 2 virtual chassis: Lab, LAB" in text
    assert nautobot.page_calls == []


async def test_get_unknown_name_explains_what_exists(ctx, nautobot):
    text = await error_text(ctx, "get_virtual_chassis", virtual_chassis="LAB")
    assert "No virtual chassis 'LAB'" in text and "Available: LAB.local.zz, OTHER" in text
    assert nautobot.page_calls == []


async def test_get_id_that_matches_nothing_points_to_the_list_tool(ctx, nautobot):
    nautobot.list_rows["virtual_chassis"] = []
    text = await error_text(ctx, "get_virtual_chassis", virtual_chassis=UUID_VC)
    assert "list_virtual_chassis" in text


async def test_fetch_all_sends_no_variables(nautobot):
    nautobot.graphql_override = {"virtual_chassis": [VC_ROW, "junk"]}
    rows = await vc.fetch_virtual_chassis(nautobot)
    assert rows == [VC_ROW]
    assert nautobot.graphql_calls[-1][1] == {}


async def test_fetch_without_a_list_raises(nautobot):
    nautobot.graphql_override = {"virtual_chassis": None, "errors": ["boom"]}
    with pytest.raises(NautobotError) as exc:
        await vc.fetch_virtual_chassis(nautobot)
    assert "boom" not in str(exc.value)  # upstream error text never reaches a run or the model


def test_pick_master_prefers_the_flag_then_the_lowest_position():
    flagged = {"name": "b", "vc_position": 2, "vc_master_for": {"id": "x"}}
    first = {"name": "a", "vc_position": 1}
    assert vc.pick_master([first, flagged]) is flagged
    assert vc.pick_master([{"name": "z"}, first]) is first
    assert vc.pick_master([]) is None


def test_address_and_type_tolerate_missing_nested_objects():
    assert vc.address_of(None) is None
    assert vc.address_of({"primary_ip4": {"address": ""}}) is None
    assert vc.device_type_model({"device_type": None}) is None
    assert vc.device_type_model({"device_type": {"model": ""}}) is None
