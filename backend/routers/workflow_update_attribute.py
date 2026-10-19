"""Update Attribute step editor APIs."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from core.auth import get_current_user, require_permission
from core.models.users import User
from core.rate_limit import rate_limited
from core.regex_isolated import run_regex
from core.safe_http_errors import client_error_message, raise_internal_server_error
from models.update_attribute import (
    UpdateAttributeProbeDeviceRequest,
    UpdateAttributeProbeRequest,
    UpdateAttributeProbeResponse,
)
from models.workflow_context import DeviceContext
from services.workflow_context.attribute_path import resolve_device_attribute

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/workflow-steps/update-attribute",
    tags=["workflow-steps"],
    dependencies=[
        Depends(get_current_user),
        Depends(require_permission("workflow_steps", "read")),
    ],
)


def _str_map(value: object) -> dict[str, str]:
    return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}


def _build_probe_response(raw: dict[str, object]) -> UpdateAttributeProbeResponse:
    groups = raw.get("groups")
    named_groups = raw.get("named_groups")
    return UpdateAttributeProbeResponse(
        matched=bool(raw.get("matched")),
        source_text=str(raw["source_text"]) if raw.get("source_text") is not None else None,
        full_match=str(raw["full_match"]) if raw.get("full_match") is not None else None,
        groups=_str_map(groups),
        named_groups=_str_map(named_groups),
        destination_value=(
            str(raw["destination_value"]) if raw.get("destination_value") is not None else None
        ),
    )


async def _isolated_probe(
    *, text: str, pattern: str, destination_template: str, flags: dict[str, bool]
) -> dict[str, object]:
    """Run the user's pattern in a killable child process (S4-07)."""
    outcome = await run_regex(
        {
            "op": "probe",
            "text": text,
            "pattern": pattern,
            "destination_template": destination_template,
            "flags": flags,
        }
    )
    if not outcome.ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=outcome.error)
    return outcome.result


@router.post(
    "/probe",
    response_model=UpdateAttributeProbeResponse,
    dependencies=[Depends(rate_limited("regex-probe", attempts=30, window_seconds=60))],
)
async def probe_regex(
    request: UpdateAttributeProbeRequest,
    _: User = Depends(get_current_user),
) -> UpdateAttributeProbeResponse:
    try:
        result = await _isolated_probe(
            text=request.sample_text,
            pattern=request.pattern,
            destination_template=request.destination_template,
            flags=request.regex_flags.model_dump(),
        )
        return _build_probe_response(result)
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to probe update-attribute regex: ", exc)


@router.post(
    "/probe/device",
    response_model=UpdateAttributeProbeResponse,
    dependencies=[Depends(rate_limited("regex-probe", attempts=30, window_seconds=60))],
)
async def probe_regex_from_device(
    request: UpdateAttributeProbeDeviceRequest,
    _: User = Depends(get_current_user),
) -> UpdateAttributeProbeResponse:
    try:
        device = DeviceContext.model_validate(request.device)
        source_path = request.source_path.strip()
        if not source_path:
            raise ValueError("source_path is required")

        source_value = resolve_device_attribute(device, source_path)
        if source_value is None:
            return UpdateAttributeProbeResponse(
                matched=False,
                source_text=None,
            )

        result = await _isolated_probe(
            text=source_value,
            pattern=request.pattern,
            destination_template=request.destination_template,
            flags=request.regex_flags.model_dump(),
        )
        return _build_probe_response(result)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=client_error_message(exc)
        ) from exc
    except Exception as exc:
        raise_internal_server_error(
            logger,
            "Failed to probe update-attribute regex from device: ",
            exc,
        )
