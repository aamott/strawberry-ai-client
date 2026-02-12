import asyncio
import os
import signal
import sys

import pytest

# ── MCP cleanup & hang prevention ────────────────────────────────────────────
#
# The MCP skill module (skills/mcp_skill/skill.py) spawns a daemon thread
# running ``loop.run_forever()`` at import time.  Although the thread is
# daemon, pytest's own teardown (fixture finalizers, plugin hooks, gc) can
# deadlock on resources tied to that loop.
#
# Strategy:
# 1. ``_shutdown_mcp_after_session`` fixture: gracefully stop the MCP loop.
# 2. ``pytest_sessionfinish`` hook: arm a SIGALRM that will force-exit the
#    process if teardown hasn't completed within a grace period.  This fires
#    early enough in pytest's shutdown sequence to actually take effect.

_PYTEST_EXIT_TIMEOUT = int(os.environ.get("PYTEST_EXIT_TIMEOUT", "10"))


def _force_shutdown_mcp() -> None:
    """Find and shut down any MCP background loops in loaded modules."""
    for _name, mod in list(sys.modules.items()):
        if "mcp_skill" in _name and hasattr(mod, "shutdown_mcp"):
            try:
                mod.shutdown_mcp()
            except Exception:
                pass
            break


@pytest.fixture(scope="session", autouse=True)
def _shutdown_mcp_after_session():
    """Shut down MCP background loops after all tests complete."""
    yield
    _force_shutdown_mcp()


def pytest_sessionfinish(session, exitstatus):
    """Arm a SIGALRM to force-exit if pytest teardown hangs.

    This hook runs after all tests and fixture finalizers but before
    pytest's final process-level cleanup.  If that cleanup deadlocks
    on background threads / event loops, the alarm will terminate the
    process after a short grace period.
    """
    def _alarm_handler(signum, frame):
        os._exit(exitstatus if isinstance(exitstatus, int) else 0)

    try:
        signal.signal(signal.SIGALRM, _alarm_handler)
        signal.alarm(_PYTEST_EXIT_TIMEOUT)
    except (OSError, ValueError):
        # signal.alarm not available on all platforms (e.g. Windows)
        pass


@pytest.fixture(scope="session", autouse=True)
def _ensure_main_thread_event_loop() -> None:
    """Ensure the main thread has a predictable event loop.

    Python 3.12's `asyncio.get_event_loop()` may implicitly create a new loop.
    Some pytest plugins call it during setup. If that loop gets garbage-collected
    without being closed, it triggers ResourceWarnings (unclosed loop + sockets)
    which become errors under `-W error`.

    This fixture ensures a main-thread loop exists for the duration of the test
    session and is explicitly closed at teardown.
    """

    created_loop: asyncio.AbstractEventLoop | None = None

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        created_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(created_loop)

    yield

    if created_loop is not None:
        try:
            if not created_loop.is_closed():
                created_loop.close()
        finally:
            try:
                asyncio.set_event_loop(None)
            except Exception:
                pass
