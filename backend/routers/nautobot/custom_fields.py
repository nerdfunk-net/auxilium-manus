"""Nautobot custom field metadata endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

import service_factory
from core.auth import get_current_user
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from dependencies import nautobot_credentials_from_query
from services.nautobot.credentials import NautobotCredentials

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/nautobot", tags=["nautobot"])


@router.get("/custom-fields/devices")
async def get_nautobot_device_custom_fields(
    credentials: NautobotCredentials = Depends(nautobot_credentials_from_query),
    _: User = Depends(get_current_user),
):
    try:
        metadata = service_factory.build_nautobot_metadata_service(credentials)
        return await metadata.get_device_custom_fields()
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to fetch device custom fields: ", exc)


@router.get("/custom-field-choices/{custom_field_name}")
async def get_nautobot_custom_field_choices(
    custom_field_name: str,
    credentials: NautobotCredentials = Depends(nautobot_credentials_from_query),
    _: User = Depends(get_current_user),
):
    try:
        metadata = service_factory.build_nautobot_metadata_service(credentials)
        return await metadata.get_custom_field_choices(custom_field_name)
    except Exception as exc:
        raise_internal_server_error(
            logger,
            f"Failed to fetch custom field choices for {custom_field_name}",
            exc,
        )
