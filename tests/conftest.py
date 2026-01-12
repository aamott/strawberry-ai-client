import asyncio

import pytest


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
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("Event loop is closed")
    except Exception:
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
