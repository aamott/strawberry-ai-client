"""MCP Skill entrypoint — dynamically generates *Skill classes from MCP servers.

When this module is imported by the SkillLoader, it:
1. Reads config/mcp_config.json
2. Connects to each enabled MCP server
3. Discovers available tools via tools/list
4. Builds one *Skill class per server (e.g. HomeAssistantSkill, FirebaseSkill)
5. Assigns each class to module scope so the loader picks them up

The generated classes use kwargs-based methods that bridge to MCP tools/call.

A persistent background event loop keeps MCP sessions alive for the lifetime
of the process.  Tool calls are dispatched to this loop via
``asyncio.run_coroutine_threadsafe``.
"""

import asyncio
import json
import logging
import threading
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Dict

from mcp import ClientSession, types

from .class_builder import build_all_skill_classes
from .mcp_client import discover_all_servers

logger = logging.getLogger(__name__)

# ── Config discovery ────────────────────────────────────────────────────────

# Walk up from this file to find the project root (ai-pc-spoke/)
_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent.parent  # skills/mcp_skill -> skills -> ai-pc-spoke
_CONFIG_PATH = _PROJECT_ROOT / "config" / "mcp_config.json"


def _load_mcp_config() -> Dict[str, Any]:
    """Load and parse mcp_config.json.

    Returns:
        Parsed config dict, or empty dict on failure.
    """
    if not _CONFIG_PATH.exists():
        logger.warning("MCP config not found at %s", _CONFIG_PATH)
        return {}

    try:
        with open(_CONFIG_PATH, "r") as f:
            config = json.load(f)
        logger.info("Loaded MCP config from %s", _CONFIG_PATH)
        return config
    except Exception as e:
        logger.error("Failed to parse MCP config: %s", e)
        return {}


# ── Persistent background event loop ───────────────────────────────────────
#
# MCP sessions live inside async context managers (streamable_http_client,
# stdio_client) that use anyio task groups.  These *must* be entered and
# exited on the same event loop / task.  Using asyncio.run() would destroy
# the loop after discovery, triggering cross-task cancel-scope errors.
#
# Instead we spin up a dedicated daemon thread with its own event loop.
# Discovery runs on it, sessions remain alive, and later tool calls are
# dispatched to the same loop via run_coroutine_threadsafe().

_bg_loop: asyncio.AbstractEventLoop | None = None
_bg_thread: threading.Thread | None = None


def shutdown_mcp() -> None:
    """Cleanly shut down the MCP background loop and sessions.

    Safe to call multiple times. Used by test teardown to prevent
    daemon threads from blocking pytest exit.
    """
    global _bg_loop, _exit_stack, _sessions, _bg_thread
    global _discovery_done, _discovery_future, _generated_classes

    if _bg_loop is None:
        return

    loop = _bg_loop

    async def _cleanup() -> None:
        global _exit_stack, _sessions
        if _exit_stack is not None:
            try:
                await _exit_stack.__aexit__(None, None, None)
            except Exception:
                pass
            _exit_stack = None
        _sessions.clear()

    try:
        future = asyncio.run_coroutine_threadsafe(_cleanup(), loop)
        future.result(timeout=5)
    except Exception:
        pass

    loop.call_soon_threadsafe(loop.stop)
    if _bg_thread is not None:
        _bg_thread.join(timeout=3)
    _bg_loop = None
    _bg_thread = None
    _discovery_done = False
    _discovery_future = None
    _generated_classes = []


def _start_background_loop() -> asyncio.AbstractEventLoop:
    """Start a daemon thread running an asyncio event loop forever.

    Returns:
        The running event loop (safe to submit coroutines to).
    """
    loop = asyncio.new_event_loop()

    def _run(lp: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(lp)
        lp.run_forever()

    global _bg_thread
    _bg_thread = threading.Thread(target=_run, args=(loop,), daemon=True)
    _bg_thread.start()
    return loop


# ── Session management ──────────────────────────────────────────────────────

# Module-level singletons initialised once during discovery.
_exit_stack: AsyncExitStack | None = None
_sessions: Dict[str, ClientSession] = {}


async def _call_tool(server_name: str, tool_name: str, arguments: Dict[str, Any]) -> Any:
    """Call an MCP tool on a specific server.

    Args:
        server_name: Name of the MCP server (key in mcp_config.json).
        tool_name: Name of the tool to call.
        arguments: Keyword arguments for the tool.

    Returns:
        Concatenated text content from the tool result, or the raw content list.
    """
    session = _sessions.get(server_name)
    if session is None:
        raise RuntimeError(
            f"No active MCP session for server '{server_name}'. "
            "The server may have failed to connect at startup."
        )

    logger.info("Calling MCP tool '%s' on server '%s'", tool_name, server_name)
    logger.debug("Arguments: %s", arguments)

    result = await session.call_tool(tool_name, arguments=arguments)

    # Extract text content from the result
    texts = []
    for content in result.content:
        if isinstance(content, types.TextContent):
            texts.append(content.text)
        else:
            texts.append(str(content))

    combined = "\n".join(texts)
    logger.debug("Tool result (%d chars): %s", len(combined), combined[:200])
    return combined


def _make_call_tool_fn(server_name: str):
    """Create a bound call_tool function for a specific server.

    The returned function dispatches an async tool call to the persistent
    background event loop, so it is safe to call from synchronous code.

    Args:
        server_name: The MCP server name to bind.

    Returns:
        A sync function(tool_name, arguments) -> result.
    """

    def call_tool_fn(tool_name: str, arguments: Dict[str, Any]) -> Any:
        if _bg_loop is None:
            raise RuntimeError("MCP background event loop is not running.")
        future = asyncio.run_coroutine_threadsafe(
            _call_tool(server_name, tool_name, arguments), _bg_loop
        )
        return future.result(timeout=60)

    return call_tool_fn


# ── Async discovery ─────────────────────────────────────────────────────────


async def _discover_and_build() -> list:
    """Connect to MCP servers and build skill classes.

    Returns:
        List of dynamically created skill class types.
    """
    global _exit_stack, _sessions

    config = _load_mcp_config()
    if not config:
        return []

    servers_config = config.get("mcpServers", {})
    if not servers_config:
        logger.info("No MCP servers configured.")
        return []

    _exit_stack = AsyncExitStack()
    await _exit_stack.__aenter__()

    servers = await discover_all_servers(config, _exit_stack)

    if not servers:
        logger.warning("No MCP servers successfully connected.")
        await _exit_stack.__aexit__(None, None, None)
        _exit_stack = None
        return []

    # Sessions come back from discovery on each MCPServerInfo object.
    # Store them in the module-level dict for tool calls later.
    for server in servers:
        if server.session is not None:
            _sessions[server.server_name] = server.session
            logger.info("Session stored for MCP server '%s'", server.server_name)

    # Build call_tool functions for each connected server
    call_tool_fns = {name: _make_call_tool_fn(name) for name in _sessions}

    # Only build classes for servers we actually have sessions for
    connected_servers = [s for s in servers if s.server_name in _sessions]
    classes = build_all_skill_classes(
        connected_servers, call_tool_fns, caller_module=__name__
    )

    logger.info(
        "MCP skill discovery complete: %d servers, %d skill classes",
        len(connected_servers),
        len(classes),
    )
    return classes


_discovery_done = False
_discovery_future: Any = None  # concurrent.futures.Future set by _start_discovery()
_generated_classes: list = []


def _start_discovery() -> None:
    """Kick off MCP discovery on the background loop (non-blocking).

    Safe to call multiple times — only the first call starts discovery.
    The result can be collected later via ``wait_for_discovery()``.
    """
    global _bg_loop, _discovery_done, _discovery_future

    if _discovery_done:
        return
    _discovery_done = True

    config = _load_mcp_config()
    if not config or not config.get("mcpServers"):
        logger.info("No MCP servers configured — skipping discovery.")
        return

    _bg_loop = _start_background_loop()
    _discovery_future = asyncio.run_coroutine_threadsafe(
        _discover_and_build(), _bg_loop,
    )


def wait_for_discovery(timeout: float = 60.0) -> list:
    """Block until MCP discovery finishes (or times out) and return classes.

    Assigns generated classes to module globals so ``inspect.getmembers``
    picks them up. Safe to call multiple times — subsequent calls are no-ops
    that return the cached list.

    Args:
        timeout: Max seconds to wait for discovery to complete.

    Returns:
        List of dynamically created skill class types.
    """
    global _generated_classes

    if _generated_classes:
        return _generated_classes

    if _discovery_future is None:
        return []

    try:
        classes = _discovery_future.result(timeout=timeout)
    except Exception as e:
        logger.error("MCP skill discovery failed: %s: %s", type(e).__name__, e)
        return []

    _generated_classes = classes

    # Assign to module scope so SkillLoader/inspect.getmembers finds them.
    for cls in classes:
        globals()[cls.__name__] = cls

    return classes


# ── Module-level: start discovery immediately but don't block ──────────────
# The SkillLoader will call wait_for_discovery() when it's ready to collect
# the results. This lets imports return instantly while MCP connections
# proceed in the background.

_start_discovery()
