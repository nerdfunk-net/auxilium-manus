"""Update Attribute step editor APIs."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from core.auth import get_current_user
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from models.update_attribute import (
    UpdateAttributeProbeDeviceRequest,
    UpdateAttributeProbeRequest,
    UpdateAttributeProbeResponse,
)
from models.workflow_context import DeviceContext
from workflow_steps.common.attribute_path import resolve_device_attribute
from workflow_steps.common.attribute_regex import RegexFlagsConfig, probe_regex_transform

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/workflow-steps/update-attribute",
    tags=["workflow-steps"],
    dependencies=[Depends(get_current_user)],
)


def _build_probe_response(raw: dict[str, object]) -> UpdateAttributeProbeResponse:
    groups = raw.get("groups")
    named_groups = raw.get("named_groups")
    return UpdateAttributeProbeResponse(
        matched=bool(raw.get("matched")),
        source_text=str(raw["source_text"]) if raw.get("source_text") is not None else None,
        full_match=str(raw["full_match"]) if raw.get("full_match") is not None else None,
        groups={str(key): str(value) for key, value in dict(groups or {}).items()},
        named_groups={
            str(key): str(value) for key, value in dict(named_groups or {}).items()
        },
        destination_value=(
            str(raw["destination_value"])
            if raw.get("destination_value") is not None
            else None
        ),
    )


@router.post("/probe", response_model=UpdateAttributeProbeResponse)
async def probe_regex(
    request: UpdateAttributeProbeRequest,
    _: User = Depends(get_current_user),
) -> UpdateAttributeProbeResponse:
    try:
        result = probe_regex_transform(
            source_text=request.sample_text,
            pattern=request.pattern,
            destination_template=request.destination_template,
            flags=RegexFlagsConfig.from_mapping(request.regex_flags.model_dump()),
        )
        return _build_probe_response(result)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to probe update-attribute regex: ", exc)


@router.post("/probe/device", response_model=UpdateAttributeProbeResponse)
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

        result = probe_regex_transform(
            source_text=source_value,
            pattern=request.pattern,
            destination_template=request.destination_template,
            flags=RegexFlagsConfig.from_mapping(request.regex_flags.model_dump()),
        )
        return _build_probe_response(result)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(
            logger,
            "Failed to probe update-attribute regex from device: ",
            exc,
        )
