"""Outbound HTTP(S) proxy for the AI providers (doc/ai_integration/AI_ASSISTANT.md, "Proxy").

The proxy URL and its Basic Auth credential are handed to httpx separately, so the password never
ends up in a URL string, a log line or an exception text.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from core.ssl_config import create_verified_ssl_context

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProxyConfig:
    """A resolved proxy. ``password`` is excluded from ``repr``."""

    url: str
    username: str | None = None
    password: str = field(default="", repr=False)
    bypass_hosts: tuple[str, ...] = ()


class BypassEntryError(ValueError):
    """A bypass entry that is not an exact name, a domain, an IP address or a CIDR range."""


_LABEL = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")

IpNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
# ("net", network) | ("ip", address) | ("domain", name) | ("name", single-label name)
ParsedEntry = tuple[str, Any]


def _as_ip(text: str) -> IpAddress | None:
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        return None


def _normalise_host(host: str) -> str:
    """Lower-case, no trailing dot (``ollama.corp.`` is the same host as ``ollama.corp``)."""
    return host.strip().lower().rstrip(".")


def parse_bypass_entry(raw: str) -> ParsedEntry:
    """Classify one bypass entry, or raise ``BypassEntryError``.

    - ``10.0.0.0/8``: an IP network, matching only addresses of its family. A prefix of 0
      (``0.0.0.0/0``) would exempt every address and is refused.
    - ``10.1.2.3``: exactly that address.
    - ``corp.example`` / ``*.corp.example`` / ``.corp.example``: the domain and its subdomains.
      At least two labels, so a bare ``com`` can never take a public provider off the proxy.
    - ``ollama``: exactly that single-label host name.
    Entries that look numeric but are not an IP (``1``, ``2.3``, ``10.0.0``) are refused rather
    than read as a name.
    """
    entry = raw.strip().lower()
    if "/" in entry:
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError as exc:
            raise BypassEntryError(f"Not a valid CIDR range: {raw!r}") from exc
        if network.prefixlen == 0:
            raise BypassEntryError(
                "A range with prefix length 0 would bypass the proxy for everything"
            )
        return ("net", network)
    address = _as_ip(entry)
    if address is not None:
        return ("ip", address)
    wildcard = entry.startswith(("*.", "."))
    name = _normalise_host(entry.removeprefix("*").lstrip("."))
    labels = name.split(".")
    if not name or not all(_LABEL.fullmatch(label) for label in labels):
        raise BypassEntryError(f"Not a valid host name: {raw!r}")
    if labels[-1].isdigit():
        raise BypassEntryError(f"Not a valid host name or IP address: {raw!r}")
    if len(labels) == 1:
        if wildcard:
            raise BypassEntryError(f"A domain needs at least two labels: {raw!r}")
        return ("name", name)
    return ("domain", name)


def _matches(host: str, entry: ParsedEntry) -> bool:
    kind, value = entry
    address = _as_ip(host)
    if kind == "net":
        return address is not None and address.version == value.version and address in value
    if kind == "ip":
        return address is not None and address == value
    if address is not None:  # a name entry never matches an IP literal
        return False
    return host == value or (kind == "domain" and host.endswith(f".{value}"))


def is_bypassed(proxy: ProxyConfig, target_url: str) -> bool:
    """True when the target host matches a bypass entry. Entries that do not parse never match,
    so a bad stored value keeps the traffic on the proxy."""
    host = _normalise_host(urlparse(target_url).hostname or "")
    if not host:
        return False
    for raw in proxy.bypass_hosts:
        try:
            if _matches(host, parse_bypass_entry(raw)):
                return True
        except BypassEntryError:
            logger.debug("Ignoring an unusable proxy bypass entry")
    return False


def httpx_client_options(proxy: ProxyConfig | None, target_url: str) -> dict[str, Any]:
    """Keyword arguments for ``httpx.AsyncClient`` that route ``target_url`` as configured.

    TLS always verifies against the shared context (OS trust store + certifi, like the other
    sources), so a company CA installed with ``INSTALL_CERTIFICATE_FILES`` is trusted by the
    provider, by an https proxy and by a TLS-inspecting proxy. Verification is never disabled.

    No proxy configured: httpx keeps honouring ``HTTPS_PROXY`` and friends. A configured proxy
    is authoritative: environment variables are ignored, and a bypassed host connects directly.
    """
    context = create_verified_ssl_context()
    options: dict[str, Any] = {"verify": context}
    if proxy is None:
        return options
    options["trust_env"] = False
    if not is_bypassed(proxy, target_url):
        auth = (proxy.username or "", proxy.password) if proxy.username is not None else None
        # httpx accepts a TLS context for the proxy hop only on an https proxy URL.
        https_proxy = urlparse(proxy.url).scheme.lower() == "https"
        options["proxy"] = httpx.Proxy(
            proxy.url, auth=auth, ssl_context=context if https_proxy else None
        )
    return options
