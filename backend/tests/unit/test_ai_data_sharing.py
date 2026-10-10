"""SharingPolicy categories and the run attribute mask."""

from __future__ import annotations

from services.ai_assistant.data_sharing import (
    DataClass,
    SharingPolicy,
    filter_nautobot_attributes,
    mask_run_attributes,
)


def test_default_policy_shares_nothing() -> None:
    policy = SharingPolicy()

    assert not any(policy.allows(c) for c in DataClass)
    assert policy.describe() == "nothing"


def test_categories_require_the_base_switch() -> None:
    policy = SharingPolicy(addresses=True, custom_fields=True, config_context=True)

    assert not policy.allows(DataClass.ADDRESSES)
    assert not policy.allows(DataClass.CUSTOM_FIELDS)
    assert not policy.allows(DataClass.CONFIG_CONTEXT)


def test_content_is_independent_of_inventory() -> None:
    assert SharingPolicy(content=True).allows(DataClass.CONTENT)
    assert not SharingPolicy(content=True).allows(DataClass.INVENTORY)


def test_describe_lists_what_is_on() -> None:
    policy = SharingPolicy(inventory=True, custom_fields=True, content=True)

    assert policy.describe() == "device basics, custom fields, run and device content"


def test_filter_withholds_unknown_names_always() -> None:
    policy = SharingPolicy(inventory=True, addresses=True, custom_fields=True, config_context=True)

    kept, withheld = filter_nautobot_attributes(policy, {"name": "a", "weird": 1, "serial": "S"})

    assert kept == {"name": "a", "serial": "S"} and withheld == {"weird": "never"}


def test_mask_replaces_nested_category_keys_only() -> None:
    bag = {
        "nautobot": {
            "name": "sw",
            "primary_ip4": {"address": "10.0.0.1"},
            "custom_fields": {"a": 1},
        },
        "other": [{"config_context": {"k": "v"}, "keep": 1}],
    }

    masked = mask_run_attributes(SharingPolicy(inventory=True, custom_fields=True), bag)

    assert masked["nautobot"]["name"] == "sw" and masked["nautobot"]["custom_fields"] == {"a": 1}
    assert masked["nautobot"]["primary_ip4"] == {"not_shared": "device_addresses"}
    assert masked["other"][0] == {"config_context": {"not_shared": "config_context"}, "keep": 1}
    assert bag["nautobot"]["primary_ip4"] == {"address": "10.0.0.1"}  # input untouched
