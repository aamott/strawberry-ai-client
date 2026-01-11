"""HTTP client for communicating with the Strawberry AI Hub."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

try:
    import websockets
    from websockets.asyncio.client import ClientConnection
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    ClientConnection = None

from ..models import ChatMessage, ChatResponse

logger = logging.getLogger(__name__)


try:
    # Python 3.11+
    BaseExceptionGroup  # type: ignore[name-defined]
except NameError:  # pragma: no cover
    # Python <3.11
    from exceptiongroup import BaseExceptionGroup  # type: ignore[assignment]


def _normalize_hub_url(url: str) -> str:
    """Normalize Hub base URL.

    The HubClient expects a base URL at the server root (no /api suffix).
    Users often paste URLs like https://host/api or https://host/api/v1.
    Those break Hub endpoints like /health and /ws/device.
    """

    raw = (url or "").strip()
    if not raw:
        return raw

    parsed = urlparse(raw)
    path = (parsed.path or "").rstrip("/")
    if path in {"/api", "/api/v1"}:
        parsed = parsed._replace(path="")

    # Keep scheme/netloc/query/etc. Ensure no trailing slash in base.
    normalized = urlunparse(parsed).rstrip("/")
    return normalized


@dataclass
class HubConfig:
    """Configuration for Hub connection."""
    url: str
    token: str
    timeout: float = 30.0

    def __post_init__(self) -> None:
        self.url = _normalize_hub_url(self.url)

    @classmethod
    def from_settings(cls, settings) -> Optional["HubConfig"]:
        """Create config from settings if Hub is configured."""
        if not settings.hub_url or not settings.hub_token:
            return None
        return cls(
            url=settings.hub_url,
            token=settings.hub_token,
            timeout=settings.hub_timeout,
        )


# Re-export for backward compatibility
__all__ = ["ChatMessage", "ChatResponse", "HubConfig", "HubClient", "HubError"]


class HubError(Exception):
    """Error from Hub API."""
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code

    @property
    def is_retryable(self) -> bool:
        """Check if this error should be retried."""
        # Retry server errors (5xx) but not client errors (4xx)
        return self.status_code >= 500


class RetryableHubError(HubError):
    """Hub error that should be retried."""
    pass


# Retry configuration for Hub requests
_retry_config = retry(
    stop=stop_after_attempt(3),  # Max 3 attempts
    wait=wait_exponential(multiplier=1, min=1, max=10),  # 1s, 2s, 4s backoff
    retry=retry_if_exception_type((RetryableHubError, httpx.TransportError)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)


class HubClient:
    """Client for communicating with the Strawberry AI Hub.

    Provides methods for:
    - Chat completions (LLM requests)
    - Skill registration
    - Skill discovery
    - Device management
    """

    def __init__(self, config: HubConfig):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None
        # Synchronous fallback client.
        #
        # Why this exists:
        # - Some parts of the system execute LLM-generated code in a *sync* context
        #   (direct exec fallback when the Deno sandbox is unavailable).
        # - Using the async httpx client from that sync context can crash with
        #   cross-event-loop errors (async objects bound to a different loop).
        # - A dedicated sync httpx client avoids event loop coupling entirely.
        self._sync_client: Optional[httpx.Client] = None
        self._websocket: Optional[ClientConnection] = None
        self._ws_task: Optional[asyncio.Task] = None
        self._skill_callback: Optional[Callable[[str, str, list, dict], Awaitable[Any]]] = None
        self._connection_callback: Optional[Callable[[bool], Awaitable[None]]] = None
        self._reconnect_delay = 1.0  # Start with 1 second

    @property
    def client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.config.url,
                headers={"Authorization": f"Bearer {self.config.token}"},
                timeout=self.config.timeout,
            )
        return self._client

    @property
    def sync_client(self) -> httpx.Client:
        """Get or create the synchronous HTTP client."""
        if self._sync_client is None:
            self._sync_client = httpx.Client(
                base_url=self.config.url,
                headers={"Authorization": f"Bearer {self.config.token}"},
                timeout=self.config.timeout,
            )
        return self._sync_client

    async def close(self):
        """Close the HTTP client and WebSocket connection."""
        # Close WebSocket
        await self.disconnect_websocket()

        # Close HTTP client
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

        # Close sync client
        if self._sync_client:
            self._sync_client.close()
            self._sync_client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    # =========================================================================
    # Health & Info
    # =========================================================================

    async def health(self) -> bool:
        """Check if Hub is healthy."""
        try:
            response = await self.client.get("/health")
            return response.status_code == 200
        except httpx.RequestError as e:
            logger.warning(f"Hub health check request error: {e}")
            return False
        except BaseExceptionGroup as eg:
            # Some async networking stacks raise ExceptionGroup/TaskGroup wrappers.
            # Log underlying errors and treat as unhealthy.
            for sub in eg.exceptions:  # type: ignore[attr-defined]
                logger.warning(f"Hub health check error: {sub!r}")
            return False

    async def get_device_info(self) -> Dict[str, Any]:
        """Get information about the authenticated device."""
        response = await self.client.get("/auth/me")
        self._check_response(response)
        return response.json()

    # =========================================================================
    # Chat / LLM
    # =========================================================================

    @_retry_config
    async def chat(
        self,
        messages: List[ChatMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> ChatResponse:
        """Send a chat completion request to the Hub.

        Args:
            messages: List of chat messages
            model: Model to use (default: Hub's configured model)
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response

        Returns:
            ChatResponse with the assistant's reply
        """
        payload = {
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
        }

        if model:
            payload["model"] = model
        if max_tokens:
            payload["max_tokens"] = max_tokens

        response = await self.client.post("/api/v1/chat/completions", json=payload)
        self._check_response(response)

        data = response.json()
        choice = data["choices"][0]

        return ChatResponse(
            content=choice["message"]["content"],
            model=data.get("model", "unknown"),
            finish_reason=choice.get("finish_reason", "stop"),
            raw=data,
        )

    async def chat_simple(self, user_message: str) -> str:
        """Simple chat - send a message and get a reply.

        Args:
            user_message: The user's message

        Returns:
            The assistant's reply text
        """
        response = await self.chat([ChatMessage(role="user", content=user_message)])
        return response.content

    # =========================================================================
    # Skills
    # =========================================================================

    @_retry_config
    async def register_skills(self, skills: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Register local skills with the Hub.

        Args:
            skills: List of skill definitions with:
                - class_name: Skill class name
                - function_name: Function name
                - signature: Function signature string
                - docstring: Optional docstring

        Returns:
            Registration result from Hub
        """
        response = await self.client.post(
            "/skills/register",
            json={"skills": skills},
        )
        self._check_response(response)
        return response.json()

    @_retry_config
    async def heartbeat(self) -> Dict[str, Any]:
        """Send heartbeat to keep skills alive."""
        response = await self.client.post("/skills/heartbeat")
        self._check_response(response)
        return response.json()

    @_retry_config
    async def list_skills(self, include_expired: bool = False) -> List[Dict[str, Any]]:
        """List all skills visible to this device.

        Args:
            include_expired: Include skills that haven't sent heartbeat recently

        Returns:
            List of skill definitions
        """
        response = await self.client.get(
            "/skills",
            params={"include_expired": str(include_expired).lower()},
        )
        self._check_response(response)
        return response.json()["skills"]

    @_retry_config
    async def search_skills(self, query: str = "", device_limit: int = 10) -> List[Dict[str, Any]]:
        """Search for skills across all devices.

        Args:
            query: Search query (matches function name, class name, docstring)
            device_limit: Number of sample devices to return per skill (Hub-side)

        Returns:
            List of matching skills with path, signature, summary, device
        """
        response = await self.client.get(
            "/skills/search",
            params={"query": query, "device_limit": device_limit},
        )
        self._check_response(response)
        return response.json()["results"]

    @_retry_config
    def search_skills_sync(self, query: str = "", device_limit: int = 10) -> List[Dict[str, Any]]:
        """Synchronous version of search_skills.

        This is used by the non-sandbox (direct exec) fallback path.
        """
        response = self.sync_client.get(
            "/skills/search",
            params={"query": query, "device_limit": device_limit},
        )
        self._check_response(response)
        return response.json()["results"]

    # =========================================================================
    # Remote Skill Execution
    # =========================================================================

    @_retry_config
    async def execute_remote_skill(
        self,
        device_name: str,
        skill_name: str,
        method_name: str,
        args: List[Any] = None,
        kwargs: Dict[str, Any] = None,
    ) -> Any:
        """Execute a skill on a remote device via Hub.

        Args:
            device_name: Target device name
            skill_name: Skill class name
            method_name: Method name to call
            args: Positional arguments
            kwargs: Keyword arguments

        Returns:
            Result from remote skill execution

        Raises:
            HubError: If remote execution fails
        """
        payload = {
            "device_name": device_name,
            "skill_name": skill_name,
            "method_name": method_name,
            "args": args or [],
            "kwargs": kwargs or {},
        }

        response = await self.client.post(
            "/skills/execute",
            json=payload,
            timeout=60.0,  # Longer timeout for remote execution
        )
        self._check_response(response)

        result = response.json()
        if not result.get("success"):
            raise HubError(result.get("error", "Remote execution failed"))

        return result.get("result")

    @_retry_config
    def execute_remote_skill_sync(
        self,
        device_name: str,
        skill_name: str,
        method_name: str,
        args: List[Any] = None,
        kwargs: Dict[str, Any] = None,
    ) -> Any:
        """Synchronous version of execute_remote_skill.

        This is used by the non-sandbox (direct exec) fallback path.
        """
        payload = {
            "device_name": device_name,
            "skill_name": skill_name,
            "method_name": method_name,
            "args": args or [],
            "kwargs": kwargs or {},
        }

        response = self.sync_client.post(
            "/skills/execute",
            json=payload,
            timeout=60.0,
        )
        self._check_response(response)

        result = response.json()
        if not result.get("success"):
            raise HubError(result.get("error", "Remote execution failed"))

        return result.get("result")

    # =========================================================================
    # Devices
    # =========================================================================

    async def list_devices(self) -> List[Dict[str, Any]]:
        """List all devices for the current user."""
        response = await self.client.get("/devices")
        self._check_response(response)
        return response.json()["devices"]

    # =========================================================================
    # Sessions (Chat History)
    # =========================================================================

    async def create_session(self) -> Dict[str, Any]:
        """Create a new chat session.

        Returns:
            Session info with id, created_at, etc.
        """
        response = await self.client.post("/api/sessions", json={})
        self._check_response(response)
        return response.json()

    async def list_sessions(
        self, limit: int = 50, days: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """List chat sessions for the current user.

        Args:
            limit: Maximum number of sessions to return
            days: If provided, only return sessions from the last N days

        Returns:
            List of session info dicts
        """
        params: Dict[str, Any] = {"limit": limit}
        if days is not None:
            params["days"] = days
        response = await self.client.get("/api/sessions", params=params)
        self._check_response(response)
        return response.json()["sessions"]

    async def get_session(self, session_id: str) -> Dict[str, Any]:
        """Get a specific session.

        Args:
            session_id: Session ID

        Returns:
            Session info dict
        """
        response = await self.client.get(f"/api/sessions/{session_id}")
        self._check_response(response)
        return response.json()

    async def get_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all messages for a session.

        Args:
            session_id: Session ID

        Returns:
            List of message dicts
        """
        response = await self.client.get(f"/api/sessions/{session_id}/messages")
        self._check_response(response)
        return response.json()["messages"]

    async def add_session_message(
        self, session_id: str, role: str, content: str
    ) -> Dict[str, Any]:
        """Add a message to a session.

        Args:
            session_id: Session ID
            role: Message role
            content: Message content

        Returns:
            Created message info dict
        """
        response = await self.client.post(
            f"/api/sessions/{session_id}/messages",
            json={"role": role, "content": content},
        )
        self._check_response(response)
        return response.json()

    async def delete_session(self, session_id: str) -> None:
        """Delete a session and all its messages.

        Args:
            session_id: Session ID to delete
        """
        response = await self.client.delete(f"/api/sessions/{session_id}")
        self._check_response(response)

    async def update_session(self, session_id: str, title: str) -> Dict[str, Any]:
        """Update a session's title.

        Args:
            session_id: Session ID to update
            title: New title for the session

        Returns:
            Updated session info
        """
        response = await self.client.patch(
            f"/api/sessions/{session_id}",
            json={"title": title},
        )
        self._check_response(response)
        return response.json()

    # =========================================================================
    # Helpers
    # =========================================================================

    def _check_response(self, response: httpx.Response):
        """Check response for errors and raise HubError if needed.

        Raises RetryableHubError for 5xx errors (server errors).
        Raises HubError for 4xx errors (client errors).
        """
        if response.status_code >= 500:
            # Server error - should retry
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise RetryableHubError(f"Hub server error: {detail}", response.status_code)
        elif response.status_code >= 400:
            # Client error - don't retry
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise HubError(f"Hub API error: {detail}", response.status_code)

    # =========================================================================
    # WebSocket Connection
    # =========================================================================

    def set_connection_callback(
        self,
        callback: Callable[[bool], Awaitable[None]]
    ):
        """Set callback for connection status changes.

        Args:
            callback: Async function(connected: bool)
        """
        self._connection_callback = callback

    def set_skill_callback(
        self,
        callback: Callable[[str, str, list, dict], Awaitable[Any]]
    ):
        """Set callback for handling incoming skill execution requests.

        Args:
            callback: Async function(skill_name, method_name, args, kwargs) -> result
        """
        self._skill_callback = callback

    async def connect_websocket(self):
        """Connect to Hub via WebSocket for receiving skill requests."""
        if not WEBSOCKETS_AVAILABLE:
            logger.warning("websockets library not available, WebSocket disabled")
            return

        if self._ws_task and not self._ws_task.done():
            logger.debug("WebSocket already connected")
            return

        # Start WebSocket connection task
        self._ws_task = asyncio.create_task(self._websocket_loop())
        logger.info("WebSocket connection task started")

    async def disconnect_websocket(self):
        """Disconnect WebSocket connection."""
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
            self._ws_task = None

        if self._websocket:
            await self._websocket.close()
            self._websocket = None

    async def _websocket_loop(self):
        """Main WebSocket connection loop with reconnection."""
        while True:
            try:
                # Build WebSocket URL
                ws_url = self.config.url.replace("http://", "ws://").replace("https://", "wss://")
                ws_url = f"{ws_url}/ws/device?token={self.config.token}"

                logger.info(f"Connecting to WebSocket: {ws_url}")

                async with websockets.connect(ws_url) as websocket:
                    self._websocket = websocket
                    self._reconnect_delay = 1.0  # Reset delay on successful connection
                    logger.info("WebSocket connected")

                    # Notify connected
                    if self._connection_callback:
                        try:
                            await self._connection_callback(True)
                        except Exception as e:
                            logger.error(f"Error in connection callback: {e}")

                    # Handle incoming messages
                    async for message in websocket:
                        try:
                            import json
                            data = json.loads(message)
                            await self._handle_websocket_message(data)
                        except Exception as e:
                            logger.error(f"Error handling WebSocket message: {e}")

            except asyncio.CancelledError:
                logger.info("WebSocket connection cancelled")
                break

            except Exception as e:
                logger.error(f"WebSocket connection error: {e}")
                self._websocket = None

                # Notify disconnected
                if self._connection_callback:
                    try:
                        await self._connection_callback(False)
                    except Exception as e:
                        logger.error(f"Error in connection callback: {e}")

                # Exponential backoff for reconnection
                logger.info(f"Reconnecting in {self._reconnect_delay}s...")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 60.0)  # Max 60s

    async def _handle_websocket_message(self, message: dict):
        """Handle incoming WebSocket message from Hub.

        Args:
            message: Parsed JSON message
        """
        msg_type = message.get("type")

        if msg_type == "skill_request":
            await self._handle_skill_request(message)

        elif msg_type == "pong":
            # Heartbeat response
            pass

        else:
            logger.warning(f"Unknown WebSocket message type: {msg_type}")

    async def _handle_skill_request(self, request: dict):
        """Handle skill execution request from Hub.

        Args:
            request: Skill request with request_id, skill_name, method_name, args, kwargs
        """
        request_id = request.get("request_id")
        skill_name = request.get("skill_name")
        method_name = request.get("method_name")
        args = request.get("args", [])
        kwargs = request.get("kwargs", {})

        logger.info(f"Received skill request {request_id}: {skill_name}.{method_name}")

        # Execute skill via callback
        try:
            if not self._skill_callback:
                raise RuntimeError("No skill callback registered")

            result = await self._skill_callback(skill_name, method_name, args, kwargs)

            # Send success response
            response = {
                "type": "skill_response",
                "request_id": request_id,
                "success": True,
                "result": result,
            }

        except Exception as e:
            logger.error(f"Skill execution error: {e}")
            # Send error response
            response = {
                "type": "skill_response",
                "request_id": request_id,
                "success": False,
                "error": str(e),
            }

        # Send response back to Hub
        if self._websocket:
            import json
            await self._websocket.send(json.dumps(response))

