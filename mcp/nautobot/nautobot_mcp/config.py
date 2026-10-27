"""Server configuration, read once from the environment and validated at startup."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlparse

_FALSE_VALUES = frozenset({"false", "0", "no", "off"})
_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})
_LOCAL_HOSTS = frozenset({"localhost", "host.docker.internal"})


class ConfigError(ValueError):
    """The environment is missing a value or holds an invalid one."""


@dataclass(frozen=True)
class Config:
    url: str
    token: str = field(repr=False)  # never printed or logged
    verify_ssl: bool = True

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Config:
        url = _required(env, "NAUTOBOT_URL")
        allow_http = env.get("NAUTOBOT_ALLOW_INSECURE_HTTP", "").strip().lower() in _TRUE_VALUES
        _check_url(url, allow_http=allow_http)
        token = _required(env, "NAUTOBOT_TOKEN")
        verify_ssl = env.get("NAUTOBOT_VERIFY_SSL", "true").strip().lower() not in _FALSE_VALUES
        return cls(url=url.rstrip("/"), token=token, verify_ssl=verify_ssl)


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is not set")
    return value


def _is_local(host: str) -> bool:
    """Loopback, private-network or single-label (Docker service) hosts may use plain http."""
    if host in _LOCAL_HOSTS or "." not in host and ":" not in host:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private and not address.is_link_local


def _check_url(url: str, *, allow_http: bool) -> None:
    """The token is sent to this URL on every call: refuse targets that would leak it."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ConfigError("NAUTOBOT_URL must start with http:// or https://")
    if parsed.username is not None or parsed.password is not None:
        raise ConfigError("NAUTOBOT_URL must not contain credentials")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ConfigError("NAUTOBOT_URL has no host")
    try:
        link_local = ipaddress.ip_address(host).is_link_local
    except ValueError:
        link_local = host == "metadata.google.internal"
    if link_local:
        raise ConfigError("NAUTOBOT_URL must not point at a link-local or metadata address")
    if parsed.scheme == "http" and not allow_http and not _is_local(host):
        raise ConfigError(
            "NAUTOBOT_URL uses cleartext http:// to a non-local host; use https:// or set "
            "NAUTOBOT_ALLOW_INSECURE_HTTP=true"
        )
