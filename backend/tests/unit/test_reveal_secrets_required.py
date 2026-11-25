"""``resolve_update_field_expression`` has no default for ``reveal_secrets``: every caller says
whether it may read a sealed secret (P-K). Only the ISE key sites do."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from models.workflow_context import Capability, DeviceContext, DeviceStatus
from services.workflow_context.secret_fields import REDACTED_PLACEHOLDER, seal_secret
from workflow_steps.add_to_ise.fields import resolve_device_fields
from workflow_steps.add_to_ise.parse import parse_config
from workflow_steps.common.value_expression import resolve_update_field_expression

_KEY = {"CREDENTIAL_ENCRYPTION_KEY": "test-secret-key-for-reveal-required"}


def _device(**bags: dict) -> DeviceContext:
    return DeviceContext(
        id="d1",
        name="r1",
        hostname="r1",
        attribute_bags={"custom": {k: v for k, v in bags.items()}},
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


def test_the_argument_has_no_default() -> None:
    with pytest.raises(TypeError, match="reveal_secrets"):
        resolve_update_field_expression(  # type: ignore[call-arg]
            device=_device(), field_key="name", raw_value="{custom.a}"
        )


@pytest.mark.parametrize(("reveal", "plain"), [(True, "hunter2"), (False, REDACTED_PLACEHOLDER)])
def test_the_flag_decides_whether_a_sealed_value_is_read(reveal: bool, plain: str) -> None:
    with patch.dict(os.environ, _KEY):
        device = _device(a=seal_secret("hunter2"))
        value = resolve_update_field_expression(
            device=device, field_key="name", raw_value="{custom.a}", reveal_secrets=reveal
        )
    assert value == plain


def _config(**extra: str) -> dict:
    return {
        "ise_source_id": "lab-ise",
        "device_name": "router1",
        "ip_address": "10.10.10.1",
        "new_key": "{custom.key}",
        **extra,
    }


@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("device_name", "device_name_is_secret"),
        ("ip_address", "ip_address_is_secret"),
        ("description", "description_is_secret"),
    ],
)
def test_add_to_ise_refuses_a_sealed_secret_outside_the_key(field, code) -> None:
    with patch.dict(os.environ, _KEY):
        device = _device(key="k", sealed=seal_secret("hunter2"))
        cfg = parse_config(_config(**{field: "{custom.sealed}"}))
        result = resolve_device_fields(device, cfg, "run-1")

    assert isinstance(result, tuple)
    assert result[0] == code
    assert "hunter2" not in result[1]
    assert result[1] == f"{field} expression points to a sealed secret; only new_key may read one"
    assert REDACTED_PLACEHOLDER not in result[1]


def test_add_to_ise_still_reads_the_new_key_in_cleartext() -> None:
    with patch.dict(os.environ, _KEY):
        device = _device(key=seal_secret("hunter2"))
        result = resolve_device_fields(device, parse_config(_config()), "run-1")

    assert not isinstance(result, tuple)
    assert result.key == "hunter2"
