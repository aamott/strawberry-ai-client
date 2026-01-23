"""Hub connection manager for MainWindow.

This module encapsulates Hub connection lifecycle management,
separating connection logic from UI concerns.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable, List, Optional

from PySide6.QtCore import QObject, Signal

from ...hub import HubClient, HubConfig, HubError

logger = logging.getLogger(__name__)


try:
    # Python 3.11+
    BaseExceptionGroup  # type: ignore[name-defined]
except NameError:  # pragma: no cover
    # Python <3.11
    from exceptiongroup import BaseExceptionGroup  # type: ignore[assignment]


@dataclass
class HubStatus:
    """Hub connection status."""

    connected: bool
    url: Optional[str] = None
    error: Optional[str] = None


class HubConnectionManager(QObject):
    """Manages Hub connection lifecycle.

    This class handles:
    - Creating and configuring HubClient
    - Health checks
    - WebSocket connection
    - Reconnection logic
    - Error formatting

    Signals are emitted for status changes so the UI can update accordingly.

    Signals:
        status_changed: Emitted when connection status changes (HubStatus)
        message: Emitted when a system message should be displayed (str)
    """

    # Emitted when connection status changes
    status_changed = Signal(object)  # HubStatus

    # Emitted for system messages (info, errors, etc.)
    message = Signal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

        self._client: Optional[HubClient] = None
        self._connected: bool = False
        self._url: Optional[str] = None
        self._last_error: Optional[str] = None

        # Callback for when skills should be registered
        self._on_connected_callback: Optional[Callable[[], None]] = None

    @property
    def client(self) -> Optional[HubClient]:
        """Get the current HubClient instance."""
        return self._client

    @property
    def connected(self) -> bool:
        """Check if currently connected to Hub."""
        return self._connected

    @property
    def url(self) -> Optional[str]:
        """Get the current Hub URL."""
        return self._url

    @property
    def last_error(self) -> Optional[str]:
        """Get the last connection error message."""
        return self._last_error

    def set_on_connected_callback(self, callback: Callable[[], None]) -> None:
        """Set callback to invoke when connection is established.

        This is typically used to trigger skill registration.
        """
        self._on_connected_callback = callback

    def initialize(
        self,
        url: str,
        token: str,
        timeout: float = 30.0,
    ) -> bool:
        """Initialize Hub connection.

        Args:
            url: Hub server URL
            token: Authentication token
            timeout: Connection timeout in seconds

        Returns:
            True if initialization started, False if token is missing
        """
        if not token:
            self._emit_status(False, error="Hub token not configured")
            self.message.emit(
                "Hub token not configured. Set HUB_DEVICE_TOKEN in your .env file."
            )
            return False

        self._url = url

        config = HubConfig(url=url, token=token, timeout=timeout)
        self._client = HubClient(config)

        # Set connection callback for websocket status changes
        self._client.set_connection_callback(self._on_connection_callback)

        # Check connection asynchronously
        asyncio.ensure_future(self._check_connection())
        return True

    async def _check_connection(self) -> None:
        """Check Hub connection status."""
        if not self._client:
            return

        try:
            timeout = self._client.config.timeout
            healthy = await asyncio.wait_for(self._client.health(), timeout=timeout)
            if not healthy:
                self._emit_status(
                    False, error="Hub is not responding. Check if the server is running."
                )
                self.message.emit(
                    "Hub is not responding. Check if the server is running."
                )
                return

            # Health endpoint does not validate auth. Verify token works.
            try:
                await asyncio.wait_for(self._client.get_device_info(), timeout=timeout)
            except HubError as e:
                err_summary = self._format_exception(e)
                self._last_error = err_summary
                self._emit_status(False, error=err_summary)
                self.message.emit(
                    "Hub authentication failed. Update your device token in Settings "
                    "(Environment tab)."
                )
                return

            self._connected = True
            self._emit_status(True)
            self.message.emit("Connected to Hub. Ready to chat!")

            # Connect WebSocket for skill execution requests
            asyncio.create_task(self._client.connect_websocket())

            # Trigger skill registration callback
            if self._on_connected_callback:
                self._on_connected_callback()

        except asyncio.TimeoutError:
            err_summary = "TimeoutError: Hub health check timed out"
            self._last_error = err_summary
            self._emit_status(False, error=err_summary)
            self.message.emit(f"Failed to connect to Hub: {err_summary}")
        except Exception as e:
            logger.exception("Failed to connect to Hub")
            err_summary = self._format_exception(e)
            self._last_error = err_summary

            self._emit_status(False, error=err_summary)
            self.message.emit(f"Failed to connect to Hub: {err_summary}")

    async def _on_connection_callback(self, connected: bool) -> None:
        """Handle connection status change from HubClient."""
        self._connected = connected
        self._emit_status(connected)

    def _emit_status(
        self, connected: bool, error: Optional[str] = None
    ) -> None:
        """Emit status changed signal."""
        self._connected = connected
        if error:
            self._last_error = error

        status = HubStatus(
            connected=connected,
            url=self._url if connected else None,
            error=error,
        )
        self.status_changed.emit(status)

    def reconnect(self, url: str, token: str, timeout: float = 30.0) -> None:
        """Reconnect to Hub with new settings.

        Closes existing connection and reinitializes.
        """
        # Close existing client
        if self._client:
            asyncio.ensure_future(self._client.close())
            self._client = None

        self._connected = False
        self._emit_status(False)

        # Reinitialize after a short delay
        asyncio.get_event_loop().call_later(
            0.1, lambda: self.initialize(url, token, timeout)
        )

    async def close(self) -> None:
        """Close Hub connection."""
        if self._client:
            await self._client.close()
            self._client = None
        self._connected = False

    @staticmethod
    def _format_exception(exc: BaseException) -> str:
        """Format exceptions for display.

        Python 3.11+ can wrap async errors into ExceptionGroup.
        We unwrap those so the user sees the underlying root cause.
        """
        if isinstance(exc, BaseExceptionGroup):
            parts: List[str] = []
            for sub in exc.exceptions:  # type: ignore[attr-defined]
                parts.append(HubConnectionManager._format_exception(sub))
            return "; ".join(p for p in parts if p) or repr(exc)

        msg = str(exc).strip()
        if not msg:
            msg = repr(exc)
        return f"{type(exc).__name__}: {msg}"
