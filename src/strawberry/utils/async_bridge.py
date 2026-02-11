"""Async-to-sync bridging utilities.

Provides a single, consistent way to call async coroutines from sync
contexts across the codebase.  Replaces ad-hoc ``asyncio.run()``,
``run_coroutine_threadsafe()``, and thread-pool patterns.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Coroutine, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Shared thread-pool for offloading async work when the current thread
# already owns a running event loop.
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="async_bridge")

# Default timeout (seconds) when blocking on a future from another thread.
DEFAULT_TIMEOUT: float = 30.0


def run_sync(
    coro: Coroutine[Any, Any, T],
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> T:
    """Run an async coroutine from a synchronous context.

    Strategy:
    1. If no event loop is running in this thread → ``asyncio.run(coro)``.
    2. If there *is* a running loop → offload to a worker thread that
       creates its own loop via ``asyncio.run()``, then block on the result.

    Args:
        coro: The coroutine to execute.
        timeout: Max seconds to wait when offloading to a thread (case 2).

    Returns:
        The coroutine's return value.

    Raises:
        TimeoutError: If the thread-pool future exceeds *timeout*.
        Any exception raised by the coroutine.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — safe to use asyncio.run() directly.
        return asyncio.run(coro)

    # Running loop in this thread: offload to a worker thread.
    def _runner() -> T:
        return asyncio.run(coro)

    return _executor.submit(_runner).result(timeout=timeout)


def schedule_on_loop(
    coro: Coroutine[Any, Any, T],
    loop: asyncio.AbstractEventLoop,
    *,
    timeout: Optional[float] = None,
) -> T:
    """Schedule a coroutine on a *specific* event loop and block for its result.

    Use this when you are on a worker/callback thread and need to run
    something on the main event loop (e.g., voice callbacks scheduling
    async component init).

    Args:
        coro: The coroutine to execute.
        loop: The target event loop (must be running in another thread).
        timeout: Max seconds to wait.  ``None`` means wait forever.

    Returns:
        The coroutine's return value.

    Raises:
        TimeoutError: If the future exceeds *timeout*.
        Any exception raised by the coroutine.
    """
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)
