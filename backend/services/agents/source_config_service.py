"""Agent source configuration: how to reach an agent and which secret it shares with the app.

A source is a Settings row ``sources.agent.<id>``. It names the transport (``http`` or ``redis``),
the agent's identity (``agent_id``, bound into every message), the global ``shared_secret``
credential that keys the message envelope, and per-agent limits. The secret itself is never part
of the row or of any API response.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy.orm import Session

from core.safe_urls import UnsafeURLError, validate_outbound_http_url
from core.secret_policy import MIN_AGENT_SECRET_LENGTH
from core.source_keys import SOURCE_ID_PATTERN
from services.agents.exceptions import AgentValidationError
from services.credentials.credentials_service import CredentialsService
from services.credentials.source_credentials import (
    SourceCredentialError,
    assert_global_credential,
    resolve_global_secret,
)
from services.settings.source_config_base import (
    SourceConfigStore,
    SourceConflictError,
    SourceNotFoundError,
)

Transport = Literal["http", "redis"]
TRANSPORTS: frozenset[str] = frozenset({"http", "redis"})

DEFAULT_MAX_CONCURRENCY = 4
DEFAULT_MAX_REQUEST_BYTES = 1_048_576
DEFAULT_MAX_TIMEOUT_SECONDS = 60
_CONCURRENCY_RANGE = (1, 64)
_REQUEST_BYTES_RANGE = (1_024, 8 * 1_048_576)
_TIMEOUT_RANGE = (1, 600)


class AgentSourceNotFoundError(SourceNotFoundError):
    display_name = "Agent"


class AgentSourceConflictError(SourceConflictError):
    display_name = "Agent"


@dataclass(frozen=True)
class AgentConnection:
    """Everything a step needs to call one agent. ``secret`` stays out of ``repr``."""

    source_id: str
    transport: Transport
    agent_id: str
    url: str | None
    max_concurrency: int
    max_request_bytes: int
    max_timeout_seconds: int
    secret: str = field(repr=False)


def _bounded(name: str, value: int, bounds: tuple[int, int]) -> int:
    low, high = bounds
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise AgentValidationError(f"{name} must be between {low} and {high}")
    return value


def _validate_agent_id(agent_id: str) -> str:
    candidate = (agent_id or "").strip()
    # The id becomes part of Redis key names and of the key-derivation context.
    if not SOURCE_ID_PATTERN.fullmatch(candidate):
        raise AgentValidationError(
            "Agent ID must start with a letter and contain only lowercase letters, numbers, "
            "underscores and hyphens (max 64 characters)."
        )
    return candidate


def _validate_target(transport: str, url: str | None, *, resolve_dns: bool) -> str | None:
    if transport not in TRANSPORTS:
        raise AgentValidationError("transport must be 'http' or 'redis'")
    if transport == "redis":
        return None
    raw = (url or "").strip()
    if not raw:
        raise AgentValidationError("An agent with the http transport needs a URL")
    try:
        # The payload is encrypted by the envelope, so plain http inside a Docker network is
        # acceptable (unlike credential-bearing sources); the SSRF policy still applies.
        return validate_outbound_http_url(raw, resolve_dns=resolve_dns)
    except UnsafeURLError as exc:
        raise AgentValidationError(f"Agent URL is not allowed: {exc}") from exc


class AgentSourceConfigService(SourceConfigStore):
    source_type = "agent"
    description_label = "Agent source"
    not_found_error = AgentSourceNotFoundError
    conflict_error = AgentSourceConflictError

    def __init__(self, db: Session) -> None:
        super().__init__(db)
        self._db_session = db
        self._credentials = CredentialsService(db)

    # -- write ---------------------------------------------------------------------

    def create_source(
        self,
        *,
        source_id: str,
        transport: str,
        agent_id: str,
        credential_id: int,
        url: str | None = None,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
        max_timeout_seconds: int = DEFAULT_MAX_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        key = self._new_setting_key(source_id)
        value = self._normalized(
            transport=transport,
            agent_id=agent_id,
            url=url,
            credential_id=credential_id,
            max_concurrency=max_concurrency,
            max_request_bytes=max_request_bytes,
            max_timeout_seconds=max_timeout_seconds,
            resolve_dns=True,
        )
        self._assert_usable_credential(credential_id)
        return self._persist_new(key=key, source_id=source_id, value=value)

    def update_source(
        self,
        source_id: str,
        *,
        transport: str | None = None,
        agent_id: str | None = None,
        url: str | None = None,
        credential_id: int | None = None,
        max_concurrency: int | None = None,
        max_request_bytes: int | None = None,
        max_timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        setting = self._get_setting_or_raise(source_id)
        current = dict(setting.value)
        changes = {
            "transport": transport,
            "agent_id": agent_id,
            "url": url,
            "credential_id": credential_id,
            "max_concurrency": max_concurrency,
            "max_request_bytes": max_request_bytes,
            "max_timeout_seconds": max_timeout_seconds,
        }
        merged = {**current, **{k: v for k, v in changes.items() if v is not None}}
        normalized = self._normalized(
            transport=str(merged.get("transport") or ""),
            agent_id=str(merged.get("agent_id") or ""),
            url=merged.get("url"),
            credential_id=merged.get("credential_id"),
            max_concurrency=merged.get("max_concurrency", DEFAULT_MAX_CONCURRENCY),
            max_request_bytes=merged.get("max_request_bytes", DEFAULT_MAX_REQUEST_BYTES),
            max_timeout_seconds=merged.get("max_timeout_seconds", DEFAULT_MAX_TIMEOUT_SECONDS),
            resolve_dns=True,
        )
        if credential_id is not None:
            self._assert_usable_credential(credential_id)
        updated = self._settings.update(setting, {"value": {**current, **normalized}})
        return self._to_public(updated.value)

    # -- resolve (steps, test-connection) -----------------------------------------------

    def resolve_connection(self, source_id: str) -> AgentConnection:
        value = self._get_setting_or_raise(source_id).value
        normalized = self._normalized(
            transport=str(value.get("transport") or ""),
            agent_id=str(value.get("agent_id") or ""),
            url=value.get("url"),
            credential_id=value.get("credential_id"),
            max_concurrency=value.get("max_concurrency", DEFAULT_MAX_CONCURRENCY),
            max_request_bytes=value.get("max_request_bytes", DEFAULT_MAX_REQUEST_BYTES),
            max_timeout_seconds=value.get("max_timeout_seconds", DEFAULT_MAX_TIMEOUT_SECONDS),
            resolve_dns=False,  # no DNS on the worker hot path; rows can predate the policy
        )
        return AgentConnection(
            source_id=source_id,
            transport=normalized["transport"],
            agent_id=normalized["agent_id"],
            url=normalized["url"],
            max_concurrency=normalized["max_concurrency"],
            max_request_bytes=normalized["max_request_bytes"],
            max_timeout_seconds=normalized["max_timeout_seconds"],
            secret=self._secret(normalized["credential_id"]),
        )

    # -- internals -------------------------------------------------------------------

    def _normalized(
        self,
        *,
        transport: str,
        agent_id: str,
        url: str | None,
        credential_id: Any,
        max_concurrency: int,
        max_request_bytes: int,
        max_timeout_seconds: int,
        resolve_dns: bool,
    ) -> dict[str, Any]:
        if isinstance(credential_id, bool) or not isinstance(credential_id, int):
            raise AgentValidationError("An agent source needs a shared-secret credential")
        return {
            "transport": transport,
            "agent_id": _validate_agent_id(agent_id),
            "url": _validate_target(transport, url, resolve_dns=resolve_dns),
            "credential_id": credential_id,
            "max_concurrency": _bounded("max_concurrency", max_concurrency, _CONCURRENCY_RANGE),
            "max_request_bytes": _bounded(
                "max_request_bytes", max_request_bytes, _REQUEST_BYTES_RANGE
            ),
            "max_timeout_seconds": _bounded(
                "max_timeout_seconds", max_timeout_seconds, _TIMEOUT_RANGE
            ),
        }

    def _secret(self, credential_id: int) -> str:
        try:
            _, secret = resolve_global_secret(
                self._db_session, credential_id, source_type=self.source_type
            )
        except SourceCredentialError as exc:
            raise AgentValidationError(str(exc)) from exc
        if len(secret) < MIN_AGENT_SECRET_LENGTH:
            raise AgentValidationError(
                f"The agent secret must be at least {MIN_AGENT_SECRET_LENGTH} characters "
                "(generate one, for example: openssl rand -base64 32)"
            )
        return secret

    def _assert_usable_credential(self, credential_id: int) -> None:
        try:
            assert_global_credential(
                self._db_session, credential_id, source_type=self.source_type
            )
        except SourceCredentialError as exc:
            raise AgentValidationError(str(exc)) from exc
        self._secret(credential_id)  # length policy, checked at save time

    def _to_public(self, value: dict[str, Any]) -> dict[str, Any]:
        credential_id = value.get("credential_id")
        credential = (
            self._credentials.get_credential_by_id(credential_id)
            if isinstance(credential_id, int)
            else None
        )
        return {
            "source_id": value.get("source_id"),
            "transport": value.get("transport"),
            "agent_id": value.get("agent_id"),
            "url": value.get("url"),
            "credential_id": credential_id,
            "credential_name": credential.get("name") if credential else None,
            "max_concurrency": value.get("max_concurrency", DEFAULT_MAX_CONCURRENCY),
            "max_request_bytes": value.get("max_request_bytes", DEFAULT_MAX_REQUEST_BYTES),
            "max_timeout_seconds": value.get("max_timeout_seconds", DEFAULT_MAX_TIMEOUT_SECONDS),
        }
