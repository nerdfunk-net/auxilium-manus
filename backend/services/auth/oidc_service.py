"""OIDC protocol logic: discovery, authorization URL, code exchange, ID token
verification, claim extraction, and user provisioning.

ID-token verification uses jwt.PyJWKClient (PyJWT), which fetches, caches, and
matches JWKS keys by `kid` internally — no separate JWT library is needed.
"""

from __future__ import annotations

import logging
import secrets
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import certifi
import httpx
import jwt
from sqlalchemy.orm import Session

from core.config import PROJECT_ROOT
from core.models.users import User
from core.ssl_config import create_verified_ssl_context
from repositories.user_repository import UserRepository
from services.auth.auth_service import password_hash
from services.auth.oidc_config_service import OidcConfigService
from services.auth.rbac_service import RBACService

logger = logging.getLogger(__name__)

HTTP_TIMEOUT_SECONDS = 10.0
ID_TOKEN_ALGORITHMS = ["RS256", "RS384", "RS512"]
DEFAULT_SCOPES = ["openid", "profile", "email"]
DEFAULT_CLAIM_MAPPINGS = {"username": "preferred_username", "email": "email", "name": "name"}
FALLBACK_DEFAULT_ROLE = "viewer"


class OIDCError(RuntimeError):
    """Raised for any recoverable OIDC protocol/configuration failure."""


class OIDCApprovalPendingError(RuntimeError):
    """Raised when a (new or existing) user's account is not yet active."""

    def __init__(self, username: str, email: str | None, provider_id: str) -> None:
        super().__init__(f"User '{username}' is pending admin approval")
        self.username = username
        self.email = email
        self.provider_id = provider_id


class OIDCAutoProvisioningDisabledError(RuntimeError):
    """Raised when a user doesn't exist and the provider disallows auto-provisioning."""


@dataclass(frozen=True)
class OIDCConfig:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str | None
    jwks_uri: str
    end_session_endpoint: str | None = None


class OIDCService:
    def __init__(self, config_service: OidcConfigService | None = None) -> None:
        self._config_service = config_service or OidcConfigService()
        self._discovery_cache: dict[str, OIDCConfig] = {}
        self._jwks_clients: dict[str, jwt.PyJWKClient] = {}
        self._ssl_contexts: dict[str, ssl.SSLContext | None] = {}

    def _get_provider_config(self, provider_id: str) -> dict[str, Any]:
        provider = self._config_service.get_provider(provider_id)
        if provider is None:
            raise OIDCError(f"OIDC provider '{provider_id}' not found")
        if not provider.get("enabled", False):
            raise OIDCError(f"OIDC provider '{provider_id}' is not enabled")
        return provider

    def resolve_ca_cert_path(self, ca_cert_path: str) -> Path:
        ca_cert_file = Path(ca_cert_path)
        if not ca_cert_file.is_absolute():
            return PROJECT_ROOT / ca_cert_path
        return ca_cert_file

    def _get_ssl_context(self, provider_id: str) -> ssl.SSLContext | None:
        if provider_id in self._ssl_contexts:
            return self._ssl_contexts[provider_id]

        provider = self._get_provider_config(provider_id)
        ca_cert_path = provider.get("ca_cert_path")
        if not ca_cert_path:
            self._ssl_contexts[provider_id] = None
            return None

        ca_cert_file = self.resolve_ca_cert_path(ca_cert_path)

        if not ca_cert_file.exists():
            logger.warning(
                "CA certificate for OIDC provider '%s' not found at %s",
                provider_id,
                ca_cert_file,
            )
            self._ssl_contexts[provider_id] = None
            return None

        context = ssl.create_default_context()
        context.load_verify_locations(cafile=certifi.where())
        context.load_verify_locations(cafile=str(ca_cert_file))
        self._ssl_contexts[provider_id] = context
        return context

    async def get_oidc_config(self, provider_id: str) -> OIDCConfig:
        if provider_id in self._discovery_cache:
            return self._discovery_cache[provider_id]

        provider = self._get_provider_config(provider_id)
        ssl_context = self._get_ssl_context(provider_id)

        async with httpx.AsyncClient(
            verify=ssl_context or create_verified_ssl_context(), timeout=HTTP_TIMEOUT_SECONDS
        ) as client:
            try:
                response = await client.get(provider["discovery_url"])
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise OIDCError(
                    f"Unable to reach OIDC discovery endpoint for '{provider_id}'"
                ) from exc

        document = response.json()
        config = OIDCConfig(
            issuer=document["issuer"],
            authorization_endpoint=document["authorization_endpoint"],
            token_endpoint=document["token_endpoint"],
            userinfo_endpoint=document.get("userinfo_endpoint"),
            jwks_uri=document["jwks_uri"],
            end_session_endpoint=document.get("end_session_endpoint"),
        )
        self._discovery_cache[provider_id] = config
        return config

    def generate_state(self) -> str:
        return secrets.token_urlsafe(32)

    async def generate_authorization_url(
        self,
        provider_id: str,
        redirect_uri: str,
        state: str,
        *,
        scopes: list[str] | None = None,
        response_type: str = "code",
        client_id: str | None = None,
    ) -> str:
        provider = self._get_provider_config(provider_id)
        config = await self.get_oidc_config(provider_id)

        params = {
            "client_id": client_id or provider["client_id"],
            "response_type": response_type,
            "scope": " ".join(scopes or provider.get("scopes") or DEFAULT_SCOPES),
            "redirect_uri": redirect_uri,
            "state": state,
        }

        return str(httpx.URL(config.authorization_endpoint).copy_with(params=params))

    async def exchange_code_for_tokens(
        self, provider_id: str, code: str, redirect_uri: str
    ) -> dict[str, Any]:
        provider = self._get_provider_config(provider_id)
        config = await self.get_oidc_config(provider_id)
        ssl_context = self._get_ssl_context(provider_id)

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": provider["client_id"],
            "client_secret": provider["client_secret"],
        }

        async with httpx.AsyncClient(
            verify=ssl_context or create_verified_ssl_context(), timeout=HTTP_TIMEOUT_SECONDS
        ) as client:
            try:
                response = await client.post(config.token_endpoint, data=data)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise OIDCError(
                    f"Failed to exchange authorization code with provider '{provider_id}'"
                ) from exc

        return response.json()

    def _get_jwks_client(self, provider_id: str, jwks_uri: str) -> jwt.PyJWKClient:
        client = self._jwks_clients.get(provider_id)
        if client is not None:
            return client

        client = jwt.PyJWKClient(
            jwks_uri,
            cache_keys=True,
            ssl_context=self._get_ssl_context(provider_id),
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        self._jwks_clients[provider_id] = client
        return client

    async def verify_id_token(self, provider_id: str, id_token: str) -> dict[str, Any]:
        provider = self._get_provider_config(provider_id)
        config = await self.get_oidc_config(provider_id)
        jwks_client = self._get_jwks_client(provider_id, config.jwks_uri)

        try:
            signing_key = jwks_client.get_signing_key_from_jwt(id_token)
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=ID_TOKEN_ALGORITHMS,
                audience=provider["client_id"],
                issuer=config.issuer,
            )
        except jwt.InvalidTokenError as exc:
            raise OIDCError(f"Invalid ID token from provider '{provider_id}'") from exc

        return claims

    def extract_user_data(self, provider_id: str, claims: dict[str, Any]) -> dict[str, Any]:
        provider = self._get_provider_config(provider_id)
        mappings = {**DEFAULT_CLAIM_MAPPINGS, **(provider.get("claim_mappings") or {})}

        username = claims.get(mappings["username"])
        if not username:
            raise OIDCError(
                f"Username claim '{mappings['username']}' not found in ID token "
                f"from provider '{provider_id}'"
            )

        return {
            "username": username,
            "email": claims.get(mappings["email"]),
            "display_name": claims.get(mappings["name"]),
            "sub": claims.get("sub"),
            "provider_id": provider_id,
        }

    def provision_or_get_user(
        self, provider_id: str, user_data: dict[str, Any], db: Session
    ) -> User:
        """Look up or create the local user; raises if the account isn't active yet."""
        provider = self._get_provider_config(provider_id)
        users = UserRepository(db)
        username = user_data["username"]

        existing = users.get_by_username(username)
        if existing is not None:
            updates: dict[str, Any] = {}
            if user_data.get("email") and existing.email != user_data["email"]:
                updates["email"] = user_data["email"]
            if user_data.get("display_name") and existing.display_name != user_data["display_name"]:
                updates["display_name"] = user_data["display_name"]
            if existing.oidc_provider != provider_id:
                updates["oidc_provider"] = provider_id

            if updates:
                existing = users.update_user(existing.id, **updates) or existing

            if not existing.is_active:
                raise OIDCApprovalPendingError(username, existing.email, provider_id)

            return existing

        if not provider.get("auto_provision", True):
            raise OIDCAutoProvisioningDisabledError(
                f"User '{username}' does not exist and auto-provisioning is disabled "
                f"for provider '{provider_id}'"
            )

        random_password = secrets.token_urlsafe(32)
        new_user = users.create_user(
            username=username,
            password_hash=password_hash.hash(random_password),
            is_active=False,
            email=user_data.get("email"),
            display_name=user_data.get("display_name"),
            oidc_provider=provider_id,
        )

        default_role = provider.get("default_role") or FALLBACK_DEFAULT_ROLE
        rbac = RBACService(db)
        if rbac.get_role_by_name(default_role) is None:
            logger.warning(
                "OIDC provider '%s' configured default_role '%s' does not exist; "
                "falling back to '%s'",
                provider_id,
                default_role,
                FALLBACK_DEFAULT_ROLE,
            )
            default_role = FALLBACK_DEFAULT_ROLE
        rbac.assign_role_to_user_by_name(new_user.id, default_role)

        raise OIDCApprovalPendingError(username, new_user.email, provider_id)

    async def get_end_session_url(self, provider_id: str, id_token_hint: str | None) -> str | None:
        config = await self.get_oidc_config(provider_id)
        if not config.end_session_endpoint:
            return None
        if not id_token_hint:
            return config.end_session_endpoint
        return str(
            httpx.URL(config.end_session_endpoint).copy_with(
                params={"id_token_hint": id_token_hint}
            )
        )
