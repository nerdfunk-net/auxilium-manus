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


def test_nautobot_bag_goes_through_the_allow_list() -> None:
    bag = {
        "nautobot": {
            "name": "sw",
            "primary_ip4": {"address": "10.0.0.1"},
            "custom_fields": {"a": 1},
            "comments": "the admin password is hunter2",
        },
    }

    masked = mask_run_attributes(SharingPolicy(inventory=True, custom_fields=True), bag)["nautobot"]

    assert masked["name"] == "sw" and masked["custom_fields"] == {"a": 1}
    assert "primary_ip4" not in masked and "comments" not in masked  # nautobot comments never sent
    assert masked["withheld"] == {
        "primary_ip4": "Addresses and serial numbers",
        "comments": "never",
    }
    assert bag["nautobot"]["primary_ip4"] == {"address": "10.0.0.1"}  # input untouched


def test_pyats_bag_is_key_names_only_with_base_switch() -> None:
    bags = {"pyats": {"host": "10.0.0.9", "username": "admin", "comments": "x"}}

    masked = mask_run_attributes(SharingPolicy(inventory=True), bags)["pyats"]

    assert masked["keys"] == ["comments", "host", "username"]
    assert "10.0.0.9" not in str(masked) and "admin" not in str(masked["keys"][1:])
    assert masked["not_shared"] == "content_data"


def test_content_switch_releases_other_bags_with_deny_list() -> None:
    bags = {"other": [{"config_context": {"k": "v"}, "keep": 1}]}

    masked = mask_run_attributes(SharingPolicy(inventory=True, content=True), bags)

    assert masked["other"][0] == {"config_context": {"not_shared": "config_context"}, "keep": 1}


def test_report_data_is_independent_of_the_other_classes() -> None:
    assert SharingPolicy(report_data=True).allows(DataClass.REPORT_DATA)
    assert not SharingPolicy(report_data=True).allows(DataClass.INVENTORY)
    assert not SharingPolicy(inventory=True, content=True).allows(DataClass.REPORT_DATA)


def test_describe_names_report_data() -> None:
    assert SharingPolicy(report_data=True).describe() == "report data"
    assert (
        SharingPolicy(inventory=True, report_data=True).describe() == "device basics, report data"
    )


def test_known_secret_bare_on_a_line_becomes_a_token() -> None:
    from services.ai_assistant.redaction import Redactor

    redactor = Redactor()
    redactor.add_known_secrets(["Sup3rS3cretPw", "short"])
    out = redactor.redact("login ok\nSup3rS3cretPw\nshort stays")

    assert "Sup3rS3cretPw" not in out and "__SECRET_" in out
    assert "short stays" in out  # values under 8 characters are never tracked
    assert "Sup3rS3cretPw" in redactor.restore(out)
