"""EventBus - thread-safe async event distribution for SpokeCore."""

import asyncio
import logging
from typing import Any, AsyncIterator, Callable, List, Optional

from .events import CoreEvent

logger = logging.getLogger(__name__)


class Subscription:
    """Handle for an event subscription."""

    def __init__(self, cancel_fn: Callable[[], None]) -> None:
        self._cancel = cancel_fn

    def cancel(self) -> None:
        self._cancel()

    def __enter__(self) -> "Subscription":
        return self

    def __exit__(self, *args) -> None:
        self.cancel()


class EventBus:
    """Thread-safe async event bus for CoreEvent distribution.

    Provides:
    - Callback-based subscriptions via `subscribe(handler)`
    - Async iterator subscriptions via `events()`
    - Safe iteration over subscribers during emit
    - Safe removal of subscribers during iteration/cancellation

    Usage:
        bus = EventBus()
        bus.set_loop(asyncio.get_running_loop())

        # Callback subscription
        sub = bus.subscribe(lambda e: print(e))
        # ... later
        sub.cancel()

        # Async iterator subscription
        async for event in bus.events():
            print(event)
    """

    def __init__(self) -> None:
        self._subscribers: List[asyncio.Queue] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Set the event loop for task scheduling.

        Args:
            loop: The asyncio event loop to use for creating tasks.
        """
        self._loop = loop

    @property
    def loop(self) -> Optional[asyncio.AbstractEventLoop]:
        """Get the configured event loop."""
        return self._loop

    async def emit(self, event: CoreEvent) -> None:
        """Emit an event to all subscribers.

        Args:
            event: The CoreEvent to distribute.
        """
        # Iterate over a snapshot to allow safe modification during iteration
        for queue in list(self._subscribers):
            await queue.put(event)

    def subscribe(self, handler: Callable[[CoreEvent], Any]) -> Subscription:
        """Subscribe to events with a callback handler.

        The handler is invoked for each event. If the handler returns a
        coroutine, it will be scheduled as a task on the configured loop.

        Args:
            handler: Callback function that receives CoreEvent instances.
                     May be sync or async (returning a coroutine).

        Returns:
            A Subscription handle that can be used to cancel the subscription.

        Raises:
            RuntimeError: If no event loop is configured.
        """
        if not self._loop:
            raise RuntimeError("EventBus.set_loop() must be called before subscribing")

        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)

        async def reader():
            while True:
                try:
                    event = await queue.get()
                    result = handler(event)
                    if asyncio.iscoroutine(result):
                        await result
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in event handler: {e}")

        task = self._loop.create_task(reader())

        def cancel():
            task.cancel()
            if queue in self._subscribers:
                self._subscribers.remove(queue)

        return Subscription(cancel)

    async def events(self) -> AsyncIterator[CoreEvent]:
        """Async iterator for events.

        Yields:
            CoreEvent instances as they are emitted.
        """
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            if queue in self._subscribers:
                self._subscribers.remove(queue)

    def clear(self) -> None:
        """Clear all subscribers (used during shutdown)."""
        self._subscribers.clear()
