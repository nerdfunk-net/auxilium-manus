"""OIDC SSO login/callback/logout endpoints, plus admin debug/test-login routes
that power the /tools/oidc-test dashboard."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

import service_factory
from core.auth import require_permission
from core.database import get_db
from core.safe_http_errors import raise_internal_server_error
from dependencies import get_oidc_config_service, get_oidc_service
from models.auth import (
    ApprovalPendingResponse,
    OIDCCallbackRequest,
    OIDCLoginResponse,
    OIDCLogoutResponse,
    OIDCProvider,
    OIDCProvidersResponse,
    OIDCTestLoginRequest,
    TokenResponse,
)
from services.auth.auth_service import AuthService
from services.auth.oidc_config_service import OidcConfigService
from services.auth.oidc_service import (
    OIDCApprovalPendingError,
    OIDCAutoProvisioningDisabledError,
    OIDCError,
    OIDCService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/oidc", tags=["oidc"])

OIDC_STATE_TTL_SECONDS = 600


def _cache_or_503():
    cache = service_factory.build_cache_service()
    if cache is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC login is temporarily unavailable",
        )
    return cache


@router.get("/providers", response_model=OIDCProvidersResponse)
async def list_providers(
    config_service: OidcConfigService = Depends(get_oidc_config_service),
) -> OIDCProvidersResponse:
    enabled = config_service.get_enabled_providers()
    global_settings = config_service.get_global_settings()

    return OIDCProvidersResponse(
        providers=[
            OIDCProvider(
                provider_id=provider["provider_id"],
                name=provider.get("name", provider["provider_id"]),
                description=provider.get("description"),
                icon=provider.get("icon"),
                display_order=provider.get("display_order", 999),
            )
            for provider in enabled
        ],
        allow_traditional_login=global_settings.get("allow_traditional_login", True),
    )


@router.get("/{provider_id}/login", response_model=OIDCLoginResponse)
async def initiate_login(
    provider_id: str,
    redirect_uri: str,
    oidc_service: OIDCService = Depends(get_oidc_service),
) -> OIDCLoginResponse:
    return await _build_login_response(provider_id, redirect_uri, oidc_service=oidc_service)


@router.post("/{provider_id}/test-login", response_model=OIDCLoginResponse)
async def initiate_test_login(
    provider_id: str,
    body: OIDCTestLoginRequest,
    _: None = Depends(require_permission("system.oidc", "read")),
    oidc_service: OIDCService = Depends(get_oidc_service),
) -> OIDCLoginResponse:
    if not body.redirect_uri:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="redirect_uri is required",
        )
    return await _build_login_response(
        provider_id,
        body.redirect_uri,
        scopes=body.scopes,
        response_type=body.response_type or "code",
        client_id=body.client_id,
        oidc_service=oidc_service,
    )


async def _build_login_response(
    provider_id: str,
    redirect_uri: str,
    *,
    scopes: list[str] | None = None,
    response_type: str = "code",
    client_id: str | None = None,
    oidc_service: OIDCService,
) -> OIDCLoginResponse:
    cache = _cache_or_503()

    try:
        state = oidc_service.generate_state()
        state_with_provider = f"{provider_id}:{state}"
        authorization_url = await oidc_service.generate_authorization_url(
            provider_id,
            redirect_uri,
            state_with_provider,
            scopes=scopes,
            response_type=response_type,
            client_id=client_id,
        )
    except OIDCError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    cache.set(f"oidc-state:{state_with_provider}", "1", ttl_seconds=OIDC_STATE_TTL_SECONDS)

    return OIDCLoginResponse(
        authorization_url=authorization_url,
        state=state_with_provider,
        provider_id=provider_id,
    )


@router.post(
    "/{provider_id}/callback",
    response_model=None,
)
async def handle_callback(
    provider_id: str,
    body: OIDCCallbackRequest,
    db: Session = Depends(get_db),
    oidc_service: OIDCService = Depends(get_oidc_service),
) -> TokenResponse | ApprovalPendingResponse:
    cache = _cache_or_503()

    if not body.state or not body.state.startswith(f"{provider_id}:"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid state")

    state_key = f"oidc-state:{body.state}"
    if cache.get(state_key) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid state")
    cache.delete(state_key)

    redirect_uri = body.redirect_uri or ""

    try:
        tokens = await oidc_service.exchange_code_for_tokens(provider_id, body.code, redirect_uri)
        id_token = tokens.get("id_token")
        if not id_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Provider did not return an ID token",
            )
        claims = await oidc_service.verify_id_token(provider_id, id_token)
        user_data = oidc_service.extract_user_data(provider_id, claims)
        user = oidc_service.provision_or_get_user(provider_id, user_data, db)
    except OIDCApprovalPendingError as exc:
        return ApprovalPendingResponse(
            username=exc.username,
            email=exc.email,
            oidc_provider=exc.provider_id,
        )
    except OIDCAutoProvisioningDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except OIDCError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise_internal_server_error(logger, "OIDC callback failed", exc)

    access_token, expires_in = AuthService(db).create_access_token(user)
    return TokenResponse(access_token=access_token, expires_in=expires_in)


@router.post("/{provider_id}/logout", response_model=OIDCLogoutResponse)
async def logout(
    provider_id: str,
    id_token_hint: str | None = None,
    oidc_service: OIDCService = Depends(get_oidc_service),
) -> OIDCLogoutResponse:
    try:
        logout_url = await oidc_service.get_end_session_url(provider_id, id_token_hint)
    except OIDCError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return OIDCLogoutResponse(logout_url=logout_url, requires_redirect=logout_url is not None)


@router.get("/debug", dependencies=[Depends(require_permission("system.oidc", "read"))])
async def debug_status(
    config_service: OidcConfigService = Depends(get_oidc_config_service),
    oidc_service: OIDCService = Depends(get_oidc_service),
) -> dict:
    global_settings = config_service.get_global_settings()
    providers = config_service.get_providers()

    provider_debug = []
    for provider_id, config in providers.items():
        ca_cert_path = config.get("ca_cert_path")
        ca_cert_exists = (
            oidc_service.resolve_ca_cert_path(ca_cert_path).exists() if ca_cert_path else None
        )

        endpoints = None
        discovery_error = None
        if config.get("enabled", False):
            try:
                oidc_config = await oidc_service.get_oidc_config(provider_id)
                endpoints = {
                    "issuer": oidc_config.issuer,
                    "authorization_endpoint": oidc_config.authorization_endpoint,
                    "token_endpoint": oidc_config.token_endpoint,
                    "userinfo_endpoint": oidc_config.userinfo_endpoint,
                    "jwks_uri": oidc_config.jwks_uri,
                    "end_session_endpoint": oidc_config.end_session_endpoint,
                }
            except OIDCError as exc:
                discovery_error = str(exc)

        provider_debug.append(
            {
                "provider_id": provider_id,
                "name": config.get("name", provider_id),
                "enabled": config.get("enabled", False),
                "client_id": config.get("client_id"),
                "discovery_url": config.get("discovery_url"),
                "scopes": config.get("scopes", []),
                "claim_mappings": config.get("claim_mappings", {}),
                "auto_provision": config.get("auto_provision", True),
                "default_role": config.get("default_role"),
                "ca_cert_path": ca_cert_path,
                "ca_cert_exists": ca_cert_exists,
                "endpoints": endpoints,
                "discovery_error": discovery_error,
            }
        )

    return {
        "oidc_enabled": config_service.is_enabled(),
        "allow_traditional_login": global_settings.get("allow_traditional_login", True),
        "providers": provider_debug,
        "config_path": str(config_service.get_config_path()),
    }
