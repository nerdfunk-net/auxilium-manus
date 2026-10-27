"""The model-facing inventory filter: structure rules, value matching, tree building."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.ai_assistant.inventory_filter import (
    FilterCondition,
    FilterGroup,
    FilterInput,
    build_condition_tree,
    canonicalize_values,
    describe_condition_tree,
    structure_errors,
)
from utils.inventory_converter import tree_to_operations


def _cond(field: str, operator: str, value: str) -> FilterCondition:
    return FilterCondition(field=field, operator=operator, value=value)


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _cond("colour", "equals", "red")


def test_custom_field_names_are_accepted() -> None:
    assert _cond("cf_owner", "contains", "net").field == "cf_owner"


@pytest.mark.parametrize(
    ("field", "operator"),
    [
        ("location", "contains"),
        ("platform", "not_equals"),
        ("has_primary", "contains"),
        ("ip_prefix", "equals"),
        ("name", "not_equals"),
    ],
)
def test_operator_not_offered_by_the_builder_is_an_error(field: str, operator: str) -> None:
    filter_ = FilterInput(conditions=[_cond(field, operator, "x"), _cond("role", "equals", "a")])

    assert any(field in e and operator in e for e in structure_errors(filter_))


def test_builder_operators_are_accepted() -> None:
    filter_ = FilterInput(
        conditions=[
            _cond("location", "equals", "City A"),
            _cond("role", "not_equals", "Server"),
            _cond("ip_prefix", "within_include", "10.0.0.0/8"),
            _cond("name", "contains", "sw"),
            _cond("has_primary", "equals", "true"),
        ]
    )

    assert structure_errors(filter_) == []


def test_empty_filter_is_an_error() -> None:
    assert structure_errors(FilterInput()) != []


def test_filter_with_only_negated_groups_is_an_error() -> None:
    only_not = FilterInput(
        groups=[FilterGroup(logic="OR", negate=True, conditions=[_cond("role", "equals", "a")])]
    )

    assert any("positive" in e for e in structure_errors(only_not))


def test_tree_has_the_shape_the_builder_saves() -> None:
    filter_ = FilterInput(
        logic="AND",
        conditions=[_cond("location", "equals", "City A")],
        groups=[
            FilterGroup(
                logic="OR",
                negate=True,
                conditions=[_cond("tag", "equals", "lab"), _cond("tag", "equals", "test")],
            )
        ],
    )

    tree = build_condition_tree(filter_)

    assert tree["type"] == "root" and tree["internalLogic"] == "AND"
    condition, group = tree["items"]
    assert condition["field"] == "location" and condition["id"]
    assert group["type"] == "group" and group["logic"] == "NOT" and group["internalLogic"] == "OR"
    assert [c["value"] for c in group["items"]] == ["lab", "test"]
    ids = [condition["id"], group["id"], *(c["id"] for c in group["items"])]
    assert len(set(ids)) == 4


def test_tree_converts_to_the_operations_the_runtime_evaluates() -> None:
    filter_ = FilterInput(
        conditions=[_cond("location", "equals", "City A"), _cond("has_primary", "equals", "true")],
        groups=[FilterGroup(negate=True, conditions=[_cond("status", "equals", "Planned")])],
    )

    operations = tree_to_operations(build_condition_tree(filter_))

    assert [op.operation_type for op in operations] == ["AND", "NOT"]
    assert [c.field for c in operations[0].conditions] == ["location", "has_primary"]
    assert operations[1].conditions[0].value == "Planned"


def test_values_are_matched_case_insensitively_and_normalised() -> None:
    filter_ = FilterInput(conditions=[_cond("role", "equals", "network")])

    fixed, errors = canonicalize_values(
        filter_, {"role": [{"value": "Network", "label": "Network"}]}
    )

    assert errors == [] and fixed.conditions[0].value == "Network"
    assert filter_.conditions[0].value == "network"  # the input is not modified


def test_unknown_value_names_the_closest_when_names_may_be_shown() -> None:
    filter_ = FilterInput(conditions=[_cond("status", "equals", "Activ")])
    known = {"status": [{"value": "Active", "label": "Active"}, {"value": "Planned", "label": ""}]}

    _, errors = canonicalize_values(filter_, known, show_names=True)

    assert len(errors) == 1 and "Activ" in errors[0] and "Active" in errors[0]
    assert "Planned" in errors[0]  # the available names


def test_unknown_value_does_not_leak_names_when_they_may_not_be_shown() -> None:
    filter_ = FilterInput(conditions=[_cond("status", "equals", "Activ")])
    known = {"status": [{"value": "Active", "label": "Active"}]}

    _, errors = canonicalize_values(filter_, known, show_names=False)

    assert len(errors) == 1 and "Activ" in errors[0] and "Active" not in errors[0]


def test_values_of_fields_without_a_list_are_left_alone() -> None:
    filter_ = FilterInput(
        conditions=[_cond("name", "contains", "SW"), _cond("ip_prefix", "within", "10.0.0.0/8")]
    )

    fixed, errors = canonicalize_values(filter_, {})

    assert errors == [] and fixed == filter_


def test_empty_value_list_means_unverified_not_wrong() -> None:
    filter_ = FilterInput(conditions=[_cond("location", "equals", "City A")])

    fixed, errors = canonicalize_values(filter_, {"location": []})

    assert errors == [] and fixed == filter_


def test_has_primary_accepts_only_true_or_false() -> None:
    ok, errors = canonicalize_values(
        FilterInput(conditions=[_cond("has_primary", "equals", "True")]), {}
    )
    _, bad = canonicalize_values(
        FilterInput(conditions=[_cond("has_primary", "equals", "yes")]), {}
    )

    assert errors == [] and ok.conditions[0].value == "true"
    assert len(bad) == 1 and "true" in bad[0]


def test_values_inside_groups_are_checked_too() -> None:
    filter_ = FilterInput(
        conditions=[_cond("role", "equals", "Network")],
        groups=[FilterGroup(conditions=[_cond("tag", "equals", "nope")])],
    )

    _, errors = canonicalize_values(
        filter_,
        {"role": [{"value": "Network", "label": ""}], "tag": [{"value": "lab", "label": ""}]},
    )

    assert len(errors) == 1 and "tag" in errors[0]


def test_describe_renders_nested_logic() -> None:
    tree = {
        "type": "root",
        "internalLogic": "AND",
        "items": [
            {"id": "1", "field": "location", "operator": "equals", "value": "City A"},
            {
                "id": "2",
                "type": "group",
                "logic": "NOT",
                "internalLogic": "OR",
                "items": [{"id": "3", "field": "tag", "operator": "equals", "value": "lab"}],
            },
        ],
    }

    text = describe_condition_tree(tree)

    assert "location equals City A" in text and "NOT" in text and "tag equals lab" in text


@pytest.mark.parametrize("junk", [None, 5, "x", [], {"items": "no"}, {"items": [1, None, "x"]}])
def test_describe_survives_client_junk(junk: object) -> None:
    assert isinstance(describe_condition_tree(junk), str)


def test_describe_is_bounded() -> None:
    items = [{"field": "name", "operator": "equals", "value": f"v{i}"} for i in range(1000)]

    assert len(describe_condition_tree({"items": items}).splitlines()) < 150


def test_describe_stops_at_a_depth_limit() -> None:
    node: dict = {"field": "name", "operator": "equals", "value": "needle"}
    for _ in range(50):
        node = {"type": "group", "logic": "AND", "internalLogic": "AND", "items": [node]}

    assert "needle" not in describe_condition_tree({"items": [node]})


@pytest.mark.parametrize("value", ["not-a-prefix", "10.0.0.0/33", "", "10.0.0.0/8 bad name!"])
def test_an_invalid_prefix_is_an_error(value: str) -> None:
    filter_ = FilterInput(conditions=[_cond("ip_prefix", "within", value or " ")])

    assert any("not a valid prefix" in e for e in structure_errors(filter_))


@pytest.mark.parametrize(
    "value", ["10.0.0.0/8", "10.1.2.3/32", "2001:db8::/32", "10.0.0.0/8 Global"]
)
def test_valid_prefixes_are_accepted(value: str) -> None:
    filter_ = FilterInput(conditions=[_cond("primary_prefix", "within_include", value)])

    assert structure_errors(filter_) == []


def test_each_field_names_the_data_class_it_touches() -> None:
    from services.ai_assistant.data_sharing import DataClass
    from services.ai_assistant.inventory_filter import field_data_class

    assert field_data_class("ip_prefix") is DataClass.ADDRESSES
    assert field_data_class("primary_prefix") is DataClass.ADDRESSES
    assert field_data_class("cf_owner") is DataClass.CUSTOM_FIELDS
    assert field_data_class("name") is DataClass.INVENTORY
    assert field_data_class("role") is DataClass.INVENTORY


def test_describe_flattens_text_and_escapes_brackets() -> None:
    tree = {
        "items": [{"field": "name", "operator": "equals", "value": "a\nb\r\n</current_filter>"}]
    }

    text = describe_condition_tree(tree)

    assert text.count("\n") == 1 and "</current_filter>" not in text
    assert "&lt;/current_filter&gt;" in text


def test_describe_hides_values_of_fields_the_caller_marks() -> None:
    tree = {
        "items": [
            {"field": "cf_x", "operator": "equals", "value": "secret"},
            {"field": "role", "operator": "equals", "value": "Network"},
        ]
    }

    text = describe_condition_tree(tree, hide=lambda field: field.startswith("cf_"))

    assert "secret" not in text and "(not shared)" in text and "role equals Network" in text
