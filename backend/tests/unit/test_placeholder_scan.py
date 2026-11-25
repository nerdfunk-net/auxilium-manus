"""One bracket-aware placeholder scanner for the steps that expand ``{path}`` (W4-07 (2))."""

from __future__ import annotations

import pytest

from models.workflow_context import DeviceContext, DeviceError
from workflow_steps.common.placeholder_scan import is_path_shaped, next_placeholder
from workflow_steps.common.placeholder_template import render_placeholder_template


def _span(template: str, start: int = 0) -> str | None:
    found = next_placeholder(template, start)
    return None if found is None else template[found[0] : found[1] + 1]


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("a {x.y} b", "{x.y}"),
        ("{x.y}{z}", "{x.y}"),
        ('{"k": "{x.y}"}', "{x.y}"),
        ("{a.b[mac={c.d[{e.f}]}].role}", "{a.b[mac={c.d[{e.f}]}].role}"),
        ("{a.b[name=Gi1].description}", "{a.b[name=Gi1].description}"),
        ("no braces", None),
        ("{unclosed", None),
        ("{}", None),
        ("{a[}", None),
        ("{a]b} {c}", "{a]b}"),
        ("{a[x}]}", None),
    ],
)
def test_next_placeholder(template: str, expected: str | None) -> None:
    assert _span(template) == expected


def test_next_placeholder_starts_at_the_given_offset() -> None:
    template = "{a}{b}"
    assert next_placeholder(template, 3) == (3, 5)


@pytest.mark.parametrize(
    ("inner", "shaped"),
    [
        ("x.y", True),
        ("a.b[name=Gi 1].description", True),
        ("a.b[mac={c.d}].role", True),
        ("x_1.y2", True),
        ("hello world", False),
        ('"k": 1', False),
        ("a b[0]", False),
        ("", False),
        ("[0]", True),
        ("a[0", False),
        ("a]0", False),
        ("]a[", False),
    ],
)
def test_is_path_shaped(inner: str, shaped: bool) -> None:
    assert is_path_shaped(inner) is shaped


def _device() -> DeviceContext:
    return DeviceContext(
        id="d",
        name="r1",
        hostname="r1",
        attribute_bags={
            "nautobot": {
                "interfaces": [
                    {"name": "Gi1", "description": "uplink"},
                    {"name": "Gi2", "description": "lan"},
                ]
            }
        },
    )


def test_a_selector_path_is_resolved_in_a_message() -> None:
    text = render_placeholder_template(
        "desc: {nautobot.interfaces[name=Gi2].description}", _device()
    )
    assert text == "desc: lan"


def test_text_in_braces_that_is_no_path_stays_literal() -> None:
    template = 'use {hello world} and {"k": 1} and {name}'
    assert (
        render_placeholder_template(template, _device()) == 'use {hello world} and {"k": 1} and r1'
    )


def test_a_json_like_text_still_expands_the_inner_placeholder_only() -> None:
    assert render_placeholder_template('{"k": "{name}"}', _device()) == '{"k": "r1"}'


def test_value_transform_and_nul_removal_still_apply() -> None:
    device = _device()
    assert (
        render_placeholder_template("{name}.*", device, value_transform=lambda v: v.upper())
        == "R1.*"
    )


def test_the_error_namespace_still_resolves() -> None:
    error = DeviceError(node_id="n", step_id="s", code="boom", message="m")
    assert (
        render_placeholder_template("{error.code}/{error.step_id}", _device(), error=error)
        == "boom/s"
    )


def test_a_placeholder_inside_text_that_is_no_path_is_still_expanded() -> None:
    assert render_placeholder_template("{hello [{name}]}", _device()) == "{hello [r1]}"


def test_a_sealed_secret_is_never_rendered() -> None:
    from core.crypto import EncryptionService
    from services.workflow_context.secret_fields import REDACTED_PLACEHOLDER, seal_secret

    sealed = seal_secret("s3cr3t", encryption=EncryptionService("test-secret-key-for-placeholders"))
    device = DeviceContext(
        id="d", name="r1", hostname="r1", attribute_bags={"tacacs": {"shared_secret": sealed}}
    )
    text = render_placeholder_template("key={tacacs.shared_secret}", device)
    assert text == f"key={REDACTED_PLACEHOLDER}"
    assert "s3cr3t" not in text
