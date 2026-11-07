"""Cisco ACI (APIC) REST client, read-only.

App-scoped httpx pools (TLS-verifying and non-verifying, because ``verify_ssl`` is a
per-source setting); credentials arrive per call. Authentication is the APIC login flow:
``POST /api/aaaLogin.json`` returns a token that is sent as the ``APIC-cookie`` cookie. The
cookie is set as an explicit request header and the pools' cookie jars are cleared after every
response, so one source's session can never ride along on another source's request.

Read-only by construction: the only public request method is :meth:`get`; the transport
refuses every method except ``GET`` and the login ``POST``.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from core.safe_urls import UnsafeURLError, validate_source_transport_async
from core.ssl_config import create_verified_ssl_context, verify_option
from services.aci.common.exceptions import (
    AciAPIError,
    AciAuthError,
    AciNotFoundError,
    AciRateLimitError,
    AciValidationError,
)
from services.aci.credentials import AciCredentials

logger = logging.getLogger(__name__)

LOGIN_PATH = "/api/aaaLogin.json"

DEFAULT_PAGE_SIZE = 1000
DEFAULT_MAX_OBJECTS = 50_000

# APIC reports the idle timeout of a session (default 600 s). Log in again a bit before it ends:
# the margin is 60 s, but never more than half of a short timeout, so a session is never cached
# past the moment the APIC drops it.
_SESSION_MARGIN_SECONDS = 60.0
_DEFAULT_REFRESH_TIMEOUT_SECONDS = 300.0
_MAX_ERROR_MESSAGE_CHARS = 300
# APIC throttles bursts with HTTP 429: wait (Retry-After, else exponential 1s/2s/4s backoff,
# capped) and retry a bounded number of times before giving up.
_MAX_RATE_LIMIT_RETRIES = 3
_MAX_RETRY_WAIT_SECONDS = 30.0

_CLASS_NAME = re.compile(r"[A-Za-z][A-Za-z0-9]{0,63}")
# The part of a distinguished name below a switch, e.g. ``sys/health``.
_RELATIVE_DN = re.compile(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*")

_SessionKey = tuple[str, str, str]
# token, monotonic expiry, version reported at login
_Session = tuple[str, float, str | None]


@dataclass(frozen=True)
class AciLoginInfo:
    """What the APIC reports at login (used by test-connection)."""

    version: str | None


class AciService:
    """Async Cisco APIC client (cookie session, paging, typed errors, GET only)."""

    def __init__(self) -> None:
        self._client_verify: httpx.AsyncClient | None = None
        self._client_no_verify: httpx.AsyncClient | None = None
        self._sessions: dict[_SessionKey, _Session] = {}
        # One lock per fabric login: a slow or unreachable APIC must not block the logins of others.
        self._login_locks: dict[_SessionKey, asyncio.Lock] = {}
        self._sleep = asyncio.sleep  # replaced in tests

    async def startup(self) -> None:
        self._client_verify = httpx.AsyncClient(verify=create_verified_ssl_context())
        # verify=False is an opt-in per-source setting (verify_ssl); see doc/SECURITY-NOTES.md
        self._client_no_verify = httpx.AsyncClient(verify=False)  # noqa: S501
        logger.info("AciService started")

    async def shutdown(self) -> None:
        if self._client_verify is not None:
            await self._client_verify.aclose()
            self._client_verify = None
        if self._client_no_verify is not None:
            await self._client_no_verify.aclose()
            self._client_no_verify = None
        self._sessions.clear()
        self._login_locks.clear()
        logger.info("AciService shut down")

    # --- public, read-only API ---------------------------------------------

    async def get(
        self,
        credentials: AciCredentials,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """GET an APIC path and return the decoded JSON body (``{}`` if empty)."""
        base = await self._validated_base(credentials)
        url = f"{base}/{path.lstrip('/')}"
        key = self._session_key(credentials, base)
        for attempt in (0, 1):
            token = (await self._session(credentials, base))[0]
            response = await self._send(
                credentials,
                "GET",
                url,
                params=params,
                headers={"Accept": "application/json", "Cookie": f"APIC-cookie={token}"},
            )
            if response.status_code == 403 and attempt == 0:
                # Expired or invalidated session: log in once more and retry.
                self._sessions.pop(key, None)
                continue
            return self._handle_response(response, path)
        raise AciAPIError("APIC request failed")  # pragma: no cover

    async def query_class(
        self,
        credentials: AciCredentials,
        class_name: str,
        *,
        query_filter: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_objects: int = DEFAULT_MAX_OBJECTS,
    ) -> list[dict[str, Any]]:
        """Return the attribute dicts of every object of one class in the fabric (all pages).

        Fails with ``too_many_objects`` rather than returning a silently truncated list.
        ``query_filter`` is an APIC ``query-target-filter`` expression the caller built from
        validated values.

        Paging ends on a short page, or earlier when the APIC's ``totalCount`` parses and has been
        reached. A missing or unparsable ``totalCount`` never ends it: only a short page does.
        Every raw object counts toward ``max_objects`` (also the ones of another class that are
        not returned), so a source that keeps sending full pages cannot loop for ever.
        """
        _check_class_name(class_name)
        return await self._query_paged(
            credentials,
            f"/api/class/{class_name}.json",
            class_name,
            query_filter=query_filter,
            page_size=page_size,
            max_objects=max_objects,
        )

    async def query_class_tree(
        self,
        credentials: AciCredentials,
        class_name: str,
        *,
        query_filter: str | None = None,
        child_classes: tuple[str, ...] = (),
        page_size: int = DEFAULT_PAGE_SIZE,
        max_objects: int = DEFAULT_MAX_OBJECTS,
    ) -> list[dict[str, Any]]:
        """Objects of one class with selected child objects: ``{"attributes", "children"}``.

        ``children`` maps a child class name to the attribute dicts of the children of that class
        (``rsp-subtree=children`` limited with ``rsp-subtree-class``); a class not asked for is
        dropped. Paging and the ``too_many_objects`` rule are those of ``query_class``.
        """
        _check_class_name(class_name)
        for child in child_classes:
            _check_class_name(child)
        return await self._query_paged(
            credentials,
            f"/api/class/{class_name}.json",
            class_name,
            query_filter=query_filter,
            page_size=page_size,
            max_objects=max_objects,
            child_classes=child_classes,
        )

    async def query_node_class(
        self,
        credentials: AciCredentials,
        pod_id: int,
        node_id: int,
        class_name: str,
        *,
        query_filter: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_objects: int = DEFAULT_MAX_OBJECTS,
    ) -> list[dict[str, Any]]:
        """Like :meth:`query_class`, but only the objects below one switch of the fabric.

        ``GET /api/node/class/topology/pod-<pod>/node-<node>/<class>.json``. Pod and node are
        positive whole numbers (the path is built from them, never from text), so a caller cannot
        reach another part of the object tree.
        """
        _check_class_name(class_name)
        path = f"/api/node/class/{_node_dn(pod_id, node_id)}/{class_name}.json"
        return await self._query_paged(
            credentials,
            path,
            class_name,
            query_filter=query_filter,
            page_size=page_size,
            max_objects=max_objects,
        )

    async def get_node_mo(
        self,
        credentials: AciCredentials,
        pod_id: int,
        node_id: int,
        relative_dn: str,
        class_name: str,
    ) -> dict[str, Any] | None:
        """The attributes of one managed object below a switch, or ``None`` if it does not exist.

        ``relative_dn`` is the part after ``topology/pod-<p>/node-<n>/`` (for example
        ``sys/health``); it may only contain letters, digits, ``_``, ``-`` and single ``/``. An
        empty one is the switch node itself (the ``fabricNode`` object, which is not *below* the
        node and so cannot be reached with :meth:`query_node_class`).
        """
        _check_class_name(class_name)
        if relative_dn != "" and not _RELATIVE_DN.fullmatch(relative_dn or ""):
            raise AciValidationError(f"Invalid APIC object path: {(relative_dn or '')[:40]!r}")
        suffix = f"/{relative_dn}" if relative_dn else ""
        body = await self.get(credentials, f"/api/mo/{_node_dn(pod_id, node_id)}{suffix}.json")
        imdata = body.get("imdata") if isinstance(body, dict) else None
        if not isinstance(imdata, list):
            raise AciAPIError(
                f"APIC returned an unexpected body for {class_name}", code="invalid_response"
            )
        for item in imdata:
            attributes = _attributes_of(item, class_name)
            if attributes is not None:
                return attributes
        return None

    async def _query_paged(
        self,
        credentials: AciCredentials,
        path: str,
        class_name: str,
        *,
        query_filter: str | None,
        page_size: int,
        max_objects: int,
        child_classes: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen = 0
        page = 0
        while True:
            params: dict[str, Any] = {"page": page, "page-size": page_size}
            if query_filter:
                params["query-target-filter"] = query_filter
            if child_classes is not None:
                params["rsp-subtree"] = "children"
                if child_classes:
                    params["rsp-subtree-class"] = ",".join(child_classes)
            body = await self.get(credentials, path, params=params)
            imdata = body.get("imdata") if isinstance(body, dict) else None
            if not isinstance(imdata, list):
                raise AciAPIError(
                    f"APIC returned an unexpected body for class {class_name}",
                    code="invalid_response",
                )
            seen += len(imdata)
            for item in imdata:
                attributes = _attributes_of(item, class_name)
                if attributes is None:
                    continue
                if child_classes is None:
                    rows.append(attributes)
                else:
                    rows.append(
                        {
                            "attributes": attributes,
                            "children": _children_of(item, class_name, child_classes),
                        }
                    )
            if seen > max_objects:
                raise AciAPIError(
                    f"APIC class {class_name} has more than {max_objects} objects; "
                    "narrow the filters",
                    code="too_many_objects",
                )
            total = _total_count(body)
            if len(imdata) < page_size or (total is not None and seen >= total):
                return rows
            page += 1

    async def login_info(self, credentials: AciCredentials, *, fresh: bool = False) -> AciLoginInfo:
        """Log in (or reuse the session) and report the APIC version from the login reply."""
        base = await self._validated_base(credentials)
        if fresh:
            self._sessions.pop(self._session_key(credentials, base), None)
        _, _, version = await self._session(credentials, base)
        return AciLoginInfo(version=version)

    # --- session -----------------------------------------------------------

    async def _validated_base(self, credentials: AciCredentials) -> str:
        if not credentials.base_url or not credentials.username or not credentials.password:
            raise AciValidationError("APIC base URL, username, and password are required")
        try:
            base = await validate_source_transport_async(
                credentials.base_url, verify_ssl=credentials.verify_ssl
            )
        except UnsafeURLError as exc:
            raise AciValidationError(str(exc)) from exc
        if not credentials.verify_ssl:
            logger.warning(
                "APIC request with verify_ssl=False url_host=%s", urlparse(base).hostname
            )
        return base.rstrip("/")

    @staticmethod
    def _session_key(credentials: AciCredentials, base: str) -> _SessionKey:
        digest = hashlib.sha256(credentials.password.encode()).hexdigest()
        return (base, credentials.login_name, digest)

    async def _session(self, credentials: AciCredentials, base: str) -> _Session:
        key = self._session_key(credentials, base)
        cached = self._sessions.get(key)
        if cached is not None and cached[1] > time.monotonic():
            return cached
        async with self._login_lock_for(key):
            cached = self._sessions.get(key)
            if cached is not None and cached[1] > time.monotonic():
                return cached
            session = await self._login(credentials, base)
            self._sessions[key] = session
            return session

    def _login_lock_for(self, key: _SessionKey) -> asyncio.Lock:
        # No await between the lookup and the insert, so this is atomic on the event loop.
        return self._login_locks.setdefault(key, asyncio.Lock())

    async def _login(self, credentials: AciCredentials, base: str) -> _Session:
        response = await self._send(
            credentials,
            "POST",
            f"{base}{LOGIN_PATH}",
            headers={"Accept": "application/json"},
            json={
                "aaaUser": {
                    "attributes": {"name": credentials.login_name, "pwd": credentials.password}
                }
            },
        )
        if response.status_code in (401, 403):
            raise AciAuthError(
                "APIC rejected the credentials",
                http_status=response.status_code,
                code="token_rejected",
            )
        if response.status_code != 200:
            raise AciAPIError(
                f"APIC login failed with status {response.status_code}",
                http_status=response.status_code,
            )
        attributes = _login_attributes(response)
        token = attributes.get("token")
        if not isinstance(token, str) or not token:
            raise AciAPIError("APIC login response had no token", code="invalid_response")
        lifetime = _session_seconds(attributes.get("refreshTimeoutSeconds"))
        version = attributes.get("version")
        return (
            token,
            time.monotonic() + lifetime,
            version if isinstance(version, str) and version else None,
        )

    # --- transport ---------------------------------------------------------

    async def _send(
        self,
        credentials: AciCredentials,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> httpx.Response:
        """Send one logical request, retrying HTTP 429 a bounded number of times."""
        # Read-only guard: GET, plus the one POST that logs in. Nothing else leaves this class.
        if not (method == "GET" or (method == "POST" and urlparse(url).path == LOGIN_PATH)):
            raise AciValidationError("This APIC client is read-only")
        for attempt in range(_MAX_RATE_LIMIT_RETRIES + 1):
            response = await self._send_once(
                credentials, method, url, headers=headers, params=params, json=json
            )
            if response.status_code != 429:
                return response
            if attempt == _MAX_RATE_LIMIT_RETRIES:
                break
            wait = _retry_wait(response, attempt)
            logger.warning("APIC rate limited; retrying in %.1fs", wait)
            await self._sleep(wait)
        raise AciRateLimitError("APIC rate limit exceeded; try again later", http_status=429)

    async def _send_once(
        self,
        credentials: AciCredentials,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> httpx.Response:
        client = self._client_verify if credentials.verify_ssl else self._client_no_verify
        try:
            if client is not None:
                try:
                    return await client.request(
                        method,
                        url,
                        params=params,
                        json=json,
                        headers=headers,
                        timeout=credentials.timeout,
                    )
                finally:
                    # The pool is shared by every source: never keep a session cookie in it.
                    client.cookies.clear()
            async with httpx.AsyncClient(verify=verify_option(credentials.verify_ssl)) as fallback:
                return await fallback.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers=headers,
                    timeout=credentials.timeout,
                )
        except httpx.TimeoutException as exc:
            raise AciAPIError(
                f"APIC request timed out after {credentials.timeout} seconds", code="timeout"
            ) from exc
        except Exception as exc:
            logger.error("APIC request failed: %s", type(exc).__name__)
            raise AciAPIError("APIC request failed", code="transport") from exc

    def _handle_response(self, response: httpx.Response, path: str) -> Any:
        status = response.status_code
        if 200 <= status < 300:
            if not response.content:
                return {}
            try:
                return response.json()
            except ValueError as exc:
                raise AciAPIError(
                    f"APIC returned a non-JSON body for {path}",
                    http_status=status,
                    code="invalid_response",
                ) from exc
        if status in (401, 403):
            raise AciAuthError("APIC denied the request", http_status=status, code="request_denied")
        if status == 404:
            raise AciNotFoundError(f"APIC resource not found: {path}", http_status=404)
        if status == 400:
            raise AciValidationError(self._error_message(response), http_status=400)
        raise AciAPIError(
            f"APIC request failed with status {status} for {path}", http_status=status
        )

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        fallback = "APIC rejected the request (400 Bad Request)"
        try:
            payload = response.json()
        except ValueError:
            return fallback
        imdata = payload.get("imdata") if isinstance(payload, dict) else None
        first = imdata[0] if isinstance(imdata, list) and imdata else None
        error = first.get("error") if isinstance(first, dict) else None
        attributes = error.get("attributes") if isinstance(error, dict) else None
        text = attributes.get("text") if isinstance(attributes, dict) else None
        if isinstance(text, str) and text.strip():
            return text.strip()[:_MAX_ERROR_MESSAGE_CHARS]
        return fallback


def _check_class_name(class_name: str) -> None:
    if not _CLASS_NAME.fullmatch(class_name or ""):
        raise AciValidationError(f"Invalid APIC class name: {(class_name or '')[:40]!r}")


def _positive_int(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AciValidationError(f"{name} must be a positive whole number")
    return value


def _node_dn(pod_id: Any, node_id: Any) -> str:
    """``topology/pod-<p>/node-<n>`` from two validated numbers."""
    return (
        f"topology/pod-{_positive_int('pod_id', pod_id)}/node-{_positive_int('node_id', node_id)}"
    )


def _children_of(
    item: Any, class_name: str, child_classes: tuple[str, ...]
) -> dict[str, list[dict[str, Any]]]:
    """Attribute dicts of the wanted child classes of one object, grouped by class."""
    obj = item.get(class_name) if isinstance(item, dict) else None
    raw = obj.get("children") if isinstance(obj, dict) else None
    grouped: dict[str, list[dict[str, Any]]] = {}
    for child in raw if isinstance(raw, list) else ():
        for child_class in child_classes:
            attributes = _attributes_of(child, child_class)
            if attributes is not None:
                grouped.setdefault(child_class, []).append(attributes)
    return grouped


def _attributes_of(item: Any, class_name: str) -> dict[str, Any] | None:
    obj = item.get(class_name) if isinstance(item, dict) else None
    attributes = obj.get("attributes") if isinstance(obj, dict) else None
    return attributes if isinstance(attributes, dict) else None


def _total_count(body: dict[str, Any]) -> int | None:
    """The APIC's ``totalCount`` as an int, or ``None`` when it is missing or not a number."""
    try:
        return int(body["totalCount"])
    except KeyError, TypeError, ValueError:
        return None


def _login_attributes(response: httpx.Response) -> dict[str, Any]:
    try:
        imdata = response.json().get("imdata")
        attributes = imdata[0]["aaaLogin"]["attributes"]
    except (ValueError, AttributeError, KeyError, IndexError, TypeError) as exc:
        raise AciAPIError("APIC login response was not valid", code="invalid_response") from exc
    if not isinstance(attributes, dict):
        raise AciAPIError("APIC login response was not valid", code="invalid_response")
    return attributes


def _session_seconds(value: Any) -> float:
    try:
        timeout = float(value)
    except TypeError, ValueError:
        timeout = _DEFAULT_REFRESH_TIMEOUT_SECONDS
    if not math.isfinite(timeout):
        timeout = _DEFAULT_REFRESH_TIMEOUT_SECONDS
    timeout = max(timeout, 0.0)
    return max(timeout - _SESSION_MARGIN_SECONDS, timeout / 2)


def _retry_wait(response: httpx.Response, attempt: int) -> float:
    """Seconds to wait before retrying a 429: ``Retry-After`` if usable, else backoff."""
    try:
        requested = float(response.headers.get("Retry-After", ""))
    except ValueError:
        requested = math.nan
    if math.isfinite(requested) and requested >= 0:
        return min(requested, _MAX_RETRY_WAIT_SECONDS)
    return min(float(2**attempt), _MAX_RETRY_WAIT_SECONDS)
