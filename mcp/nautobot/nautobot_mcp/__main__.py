"""Entry point: ``python -m nautobot_mcp`` serves MCP over stdio (default) or HTTP."""

from __future__ import annotations

import asyncio
import logging
import os
import sys

import uvicorn
from mcp.server.mcpserver import MCPServer

from nautobot_mcp.client import NautobotClient
from nautobot_mcp.config import Config, ConfigError
from nautobot_mcp.context import AppContext
from nautobot_mcp.http_app import build_http_app
from nautobot_mcp.http_config import HttpConfig
from nautobot_mcp.instructions import build_instructions
from nautobot_mcp.server import build_server
from nautobot_mcp.vocabularies import VocabularyCache

TRANSPORTS = ("stdio", "http")


async def _build(client: NautobotClient) -> MCPServer:
    app = AppContext(client=client, vocabularies=VocabularyCache(client))
    # Instructions are fixed when the server is built, so fetch the vocabulary first.
    return build_server(app, instructions=await build_instructions(app.vocabularies))


async def _serve(config: Config) -> None:
    async with NautobotClient(config) as client:
        await (await _build(client)).run_stdio_async()


async def _serve_http(config: Config, http_config: HttpConfig) -> None:
    async with NautobotClient(config) as client:
        asgi = build_http_app(await _build(client), http_config)
        server = uvicorn.Server(
            uvicorn.Config(
                asgi,
                host=http_config.host,
                port=http_config.port,
                log_level="info",
                server_header=False,  # do not advertise the server software
            )
        )
        await server.serve()


def main() -> int:
    # stdout carries the MCP protocol in stdio mode; all logging goes to stderr.
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    try:
        config = Config.from_env(os.environ)
        transport = os.environ.get("MCP_TRANSPORT", "stdio").strip().lower()
        if transport not in TRANSPORTS:
            raise ConfigError(f"MCP_TRANSPORT must be one of: {', '.join(TRANSPORTS)}")
        http_config = HttpConfig.from_env(os.environ) if transport == "http" else None
    except ConfigError as exc:
        print(f"nautobot-mcp: {exc}", file=sys.stderr)
        return 2
    if http_config is None:
        asyncio.run(_serve(config))
    else:
        asyncio.run(_serve_http(config, http_config))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
