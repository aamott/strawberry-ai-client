"""Offline mode tracking based on TensorZero response metadata."""

import logging
from datetime import datetime
from typing import Callable, List, Optional

from .tensorzero_client import ChatResponse

logger = logging.getLogger(__name__)


class OfflineModeTracker:
    """Tracks offline mode based on TensorZero responses.

    Determines if the application is in offline mode by monitoring which
    variant (hub vs local_ollama) is being used for LLM responses.
    After consecutive fallback responses, transitions to offline mode.
    """

    # Number of consecutive fallbacks before declaring offline mode
    FALLBACK_THRESHOLD = 2

    def __init__(self) -> None:
        self._consecutive_fallbacks = 0
        self._is_offline = False
        self._last_hub_success: Optional[datetime] = None
        self._last_variant: Optional[str] = None
        self._listeners: List[Callable[[bool], None]] = []
        self._pending_sync_count = 0

    def on_response(self, response: ChatResponse) -> None:
        """Update offline state based on TensorZero response.

        Args:
            response: ChatResponse from TensorZero with variant metadata
        """
        self._last_variant = response.variant

        if response.is_fallback:
            self._consecutive_fallbacks += 1
            logger.debug(
                f"Fallback response received (count: {self._consecutive_fallbacks})"
            )

            if self._consecutive_fallbacks >= self.FALLBACK_THRESHOLD:
                self._set_offline(True)
        else:
            # Hub response - we're online
            self._consecutive_fallbacks = 0
            self._last_hub_success = datetime.now()
            self._set_offline(False)

    def _set_offline(self, offline: bool) -> None:
        """Set offline state and notify listeners if changed."""
        if offline != self._is_offline:
            self._is_offline = offline
            status = "OFFLINE" if offline else "ONLINE"
            logger.info(f"Offline mode changed: {status}")

            # Notify all listeners
            for listener in self._listeners:
                try:
                    listener(offline)
                except Exception as e:
                    logger.error(f"Error in offline mode listener: {e}")

    @property
    def is_offline(self) -> bool:
        """Check if currently in offline mode."""
        return self._is_offline

    @property
    def last_hub_success(self) -> Optional[datetime]:
        """Get timestamp of last successful Hub response."""
        return self._last_hub_success

    @property
    def last_variant(self) -> Optional[str]:
        """Get the last variant used (hub or local_ollama)."""
        return self._last_variant

    @property
    def pending_sync_count(self) -> int:
        """Get count of items pending sync."""
        return self._pending_sync_count

    @pending_sync_count.setter
    def pending_sync_count(self, value: int) -> None:
        """Set count of items pending sync."""
        self._pending_sync_count = max(0, value)

    def add_listener(self, callback: Callable[[bool], None]) -> None:
        """Add a listener for offline mode changes.

        Args:
            callback: Function called with (is_offline: bool) when state changes
        """
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[bool], None]) -> None:
        """Remove a listener.

        Args:
            callback: Previously registered callback to remove
        """
        if callback in self._listeners:
            self._listeners.remove(callback)

    def force_online_check(self) -> None:
        """Reset fallback counter to allow quick recovery when Hub becomes available.

        Call this when you want to give the Hub another chance (e.g., after
        network reconnection is detected).
        """
        self._consecutive_fallbacks = 0

    def get_status_text(self, model_name: Optional[str] = None) -> str:
        """Get human-readable status text.

        Args:
            model_name: Optional model name to include in status

        Returns:
            Status string like "Online · Hub" or "Offline · Local: llama3.2:3b"
        """
        if self._is_offline:
            model_info = f"Local: {model_name}" if model_name else "Local model"
            pending = (
                f" · {self._pending_sync_count} pending"
                if self._pending_sync_count > 0
                else ""
            )
            return f"Offline · {model_info}{pending}"
        else:
            return f"Online · Hub{f': {model_name}' if model_name else ''}"
