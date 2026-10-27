"""The HTTP application: the MCP streamable-HTTP app behind bearer-token authentication."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp

from nautobot_mcp.http_auth import BearerTokenMiddleware
from nautobot_mcp.http_config import HttpConfig


def build_http_app(server: MCPServer, config: HttpConfig) -> ASGIApp:
    """Wrap ``server`` for HTTP: token check outside, Host-header check inside.

    ``stateless_http`` keeps no per-client session in memory, so several replicas can run
    behind a load balancer without sticky sessions.
    """
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(config.allowed_hosts),
        allowed_origins=[],
    )
    mcp_app = server.streamable_http_app(
        stateless_http=True, transport_security=security, host=config.host
    )
    return BearerTokenMiddleware(mcp_app, {c.name: c.token for c in config.clients})
