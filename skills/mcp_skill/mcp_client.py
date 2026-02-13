"""Thin async wrapper around the MCP Python SDK for connecting to MCP servers.

Supports two transport types:
- stdio: spawns a subprocess (has `command` + `args` in config)
- streamable HTTP: connects via HTTP SSE (has `serverUrl` in config)
"""

import asyncio
import logging
import os
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

logger = logging.getLogger(__name__)

# Timeout for connecting to an MCP server and listing tools.
CONNECT_TIMEOUT_SECONDS = 30

# Timeout for individual HTTP requests (connect + read).
# The default httpx 5s connect timeout is too short for servers behind
# SSL/DynDNS (e.g. Home Assistant over HTTPS).
HTTP_TIMEOUT_SECONDS = 30.0


@dataclass
class MCPToolInfo:
    """Parsed info about a single MCP tool."""

    name: str
    description: str
    input_schema: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPServerInfo:
    """Parsed info about an MCP server, its tools, and active session."""

    server_name: str
    tools: List[MCPToolInfo] = field(default_factory=list)
    session: ClientSession | None = field(default=None, repr=False)


def _parse_server_config(name: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """Extract transport-relevant fields from a server config block.

    Returns a dict with:
      - transport: "stdio" | "streamable_http"
      - plus transport-specific keys
    """
    if "serverUrl" in config:
        return {
            "transport": "streamable_http",
            "server_url": config["serverUrl"],
            "headers": config.get("headers", {}),
        }
    elif "command" in config:
        return {
            "transport": "stdio",
            "command": config["command"],
            "args": config.get("args", []),
            "env": config.get("env", {}),
        }
    else:
        raise ValueError(
            f"MCP server '{name}' has neither 'serverUrl' nor 'command'. "
            "Cannot determine transport type."
        )


def _extract_tools(
    raw_tools: list,
    disabled_tools: List[str],
) -> List[MCPToolInfo]:
    """Filter and convert raw MCP tool objects to MCPToolInfo."""
    tools: List[MCPToolInfo] = []
    for tool in raw_tools:
        if tool.name in disabled_tools:
            logger.debug("Skipping disabled tool: %s", tool.name)
            continue
        tools.append(
            MCPToolInfo(
                name=tool.name,
                description=tool.description or "",
                input_schema=tool.inputSchema if tool.inputSchema else {},
            )
        )
    return tools


async def _connect_stdio(
    command: str,
    args: List[str],
    env: Dict[str, str],
    exit_stack: AsyncExitStack,
) -> ClientSession:
    """Connect to an MCP server via stdio and return the session."""
    merged_env = {**os.environ, **env}
    server_params = StdioServerParameters(
        command=command,
        args=args,
        env=merged_env,
    )
    read_stream, write_stream = await exit_stack.enter_async_context(
        stdio_client(server_params)
    )
    session: ClientSession = await exit_stack.enter_async_context(
        ClientSession(read_stream, write_stream)
    )
    await session.initialize()
    return session


async def _connect_http(
    server_url: str,
    headers: Dict[str, str],
    exit_stack: AsyncExitStack,
) -> ClientSession:
    """Connect to an MCP server via streamable HTTP and return the session.

    The MCP SDK's streamable_http_client does not accept a headers kwarg
    directly.  Instead we build a custom httpx.AsyncClient with the
    headers pre-configured and pass it via the http_client parameter.
    """
    # Build a custom httpx client with generous timeouts.
    # The default httpx 5s connect timeout is too short for servers
    # behind SSL/DynDNS (e.g. Home Assistant over HTTPS).
    http_client = httpx.AsyncClient(
        headers=headers or {},
        timeout=httpx.Timeout(HTTP_TIMEOUT_SECONDS),
    )
    # Ensure the httpx client is cleaned up when the exit stack closes.
    exit_stack.push_async_callback(http_client.aclose)

    read_stream, write_stream, _ = await exit_stack.enter_async_context(
        streamable_http_client(server_url, http_client=http_client)
    )
    session: ClientSession = await exit_stack.enter_async_context(
        ClientSession(read_stream, write_stream)
    )
    await session.initialize()
    return session


async def discover_server_tools(
    server_name: str,
    server_config: Dict[str, Any],
    exit_stack: AsyncExitStack,
) -> MCPServerInfo:
    """Connect to a single MCP server and discover its tools.

    The session is kept alive via exit_stack and stored on the returned
    MCPServerInfo so callers can use it for tool calls later.

    Args:
        server_name: Human-readable server name from config.
        server_config: The config block for this server.
        exit_stack: Shared AsyncExitStack that keeps connections alive.

    Returns:
        MCPServerInfo with server name, discovered tools, and live session.

    Raises:
        Exception: If the server cannot be reached or tools cannot be listed.
    """
    parsed = _parse_server_config(server_name, server_config)
    disabled_tools = server_config.get("disabledTools", [])

    if parsed["transport"] == "stdio":
        session = await asyncio.wait_for(
            _connect_stdio(
                command=parsed["command"],
                args=parsed["args"],
                env=parsed["env"],
                exit_stack=exit_stack,
            ),
            timeout=CONNECT_TIMEOUT_SECONDS,
        )
    elif parsed["transport"] == "streamable_http":
        session = await asyncio.wait_for(
            _connect_http(
                server_url=parsed["server_url"],
                headers=parsed["headers"],
                exit_stack=exit_stack,
            ),
            timeout=CONNECT_TIMEOUT_SECONDS,
        )
    else:
        raise ValueError(f"Unknown transport: {parsed['transport']}")

    result = await session.list_tools()
    tools = _extract_tools(result.tools, disabled_tools)

    logger.info(
        "Discovered %d tools from MCP server '%s'",
        len(tools),
        server_name,
    )
    return MCPServerInfo(server_name=server_name, tools=tools, session=session)


async def discover_all_servers(
    mcp_config: Dict[str, Any],
    exit_stack: AsyncExitStack,
) -> List[MCPServerInfo]:
    """Discover tools from all enabled MCP servers in the config.

    Args:
        mcp_config: The full parsed mcp_config.json.
        exit_stack: Shared AsyncExitStack that keeps connections alive.

    Returns:
        List of MCPServerInfo, one per successfully connected server.
        Servers that fail to connect are logged and skipped.
    """
    servers_config = mcp_config.get("mcpServers", {})

    # Build list of (name, config) for enabled servers.
    enabled: List[tuple] = []
    for name, config in servers_config.items():
        if config.get("disabled", False):
            logger.info("Skipping disabled MCP server: %s", name)
            continue
        enabled.append((name, config))

    if not enabled:
        return []

    # Connect to all servers in parallel for faster startup.
    async def _safe_discover(
        name: str, cfg: Dict[str, Any],
    ) -> Optional[MCPServerInfo]:
        """Discover a single server, returning None on failure."""
        try:
            info = await discover_server_tools(name, cfg, exit_stack)
            if info.tools:
                return info
            logger.warning(
                "MCP server '%s' has no enabled tools, skipping.", name,
            )
        except asyncio.TimeoutError:
            logger.error(
                "Timed out connecting to MCP server '%s' after %ds",
                name,
                CONNECT_TIMEOUT_SECONDS,
            )
        except Exception as e:
            logger.error("Failed to connect to MCP server '%s': %s", name, e)
        return None

    infos = await asyncio.gather(
        *(_safe_discover(n, c) for n, c in enabled),
    )
    return [info for info in infos if info is not None]
