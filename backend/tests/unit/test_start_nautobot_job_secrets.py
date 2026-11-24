"""W6-05: `start-nautobot-job` (Start Job) never copies a sealed value into a job request and
its coercion errors never repeat the value (it can come from a device attribute)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from services.workflow_context.secret_fields import seal_secret
from tests.unit._step_helpers import make_device
from workflow_steps.start_nautobot_job import executor as mod


@pytest.mark.parametrize(
    ("var_type", "value"),
    [
        ("IntegerVar", "S3cr3t-Key"),
        ("BooleanVar", "S3cr3t-Key"),
        ("JSONVar", '{"password": "S3cr3t-Key"'),
    ],
)
def test_a_coercion_error_never_echoes_the_value(var_type: str, value: str) -> None:
    with pytest.raises(ValueError) as caught:
        mod._coerce_value("n", value, var_type)
    assert "S3cr3t" not in str(caught.value)
    assert "parameter 'n'" in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("optional", [False, True])
async def test_a_sealed_parameter_value_is_refused_not_sent(optional: bool) -> None:
    device = make_device("d1", attribute_bags={"tacacs": {"key": seal_secret("S3cr3t-Key")}})
    spec = mod._ParamSpec(value="{tacacs.key}", uuid_resolution=None)
    with pytest.raises(ValueError) as caught:
        await mod._resolve_device_params(
            device=device,
            required_params={} if optional else {"password": spec},
            optional_params={"password": (True, spec)} if optional else {},
            variable_types={},
            device_common=MagicMock(),
            run_id=None,
        )
    assert "secret" in str(caught.value)
    assert "S3cr3t" not in str(caught.value)
    assert "REDACTED" not in str(caught.value)


@pytest.mark.asyncio
async def test_a_plain_attribute_value_is_unchanged() -> None:
    device = make_device("d1", attribute_bags={"custom": {"n": "7"}})
    data = await mod._resolve_device_params(
        device=device,
        required_params={"n": mod._ParamSpec(value="{custom.n}", uuid_resolution=None)},
        optional_params={},
        variable_types={"n": "IntegerVar"},
        device_common=MagicMock(),
        run_id=None,
    )
    assert data == {"n": 7}
