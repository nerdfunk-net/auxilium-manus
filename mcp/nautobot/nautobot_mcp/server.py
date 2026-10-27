"""Builds the MCP server: instructions, tools and (later) the stdio entry point."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from nautobot_mcp.context import AppContext
from nautobot_mcp.tools import dcim, ipam, organization

SERVER_NAME = "nautobot"


def build_server(app: AppContext, *, instructions: str) -> MCPServer:
    """Create the server and register every tool group against ``app``."""
    server = MCPServer(SERVER_NAME, instructions=instructions)
    organization.register(server, app)
    dcim.register(server, app)
    ipam.register(server, app)
    return server
