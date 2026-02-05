"""HubConnectionManager - manages Hub connection lifecycle for SpokeCore."""

import asyncio
import logging
from typing import TYPE_CHECKING, Callable, Optional

from ..hub import HubClient, HubConfig, HubError
from .events import ConnectionChanged, CoreEvent, ModeChanged

if TYPE_CHECKING:
    from ..skills.service import SkillService

logger = logging.getLogger(__name__)


class HubConnectionManager:
    """Manages Hub connection lifecycle.

    Responsibilities:
    - Connect/disconnect from Hub
    - Health checks and authentication
    - WebSocket task management
    - Skill registration with Hub
    - Reconnection scheduling

    This class is an internal helper for SpokeCore. External code should
    continue using SpokeCore's public interface (connect_hub, disconnect_hub,
    is_online, hub_client).
    """

    def __init__(
        self,
        get_setting: Callable[[str, any], any],
        emit: Callable[[CoreEvent], "asyncio.Future"],
        get_loop: Callable[[], Optional[asyncio.AbstractEventLoop]],
    ) -> None:
        """Initialize HubConnectionManager.

        Args:
            get_setting: Callback to retrieve settings (key, default) -> value.
            emit: Async callback to emit CoreEvent instances.
            get_loop: Callback to get the current event loop (or None).
        """
        self._get_setting = get_setting
        self._emit = emit
        self._get_loop = get_loop

        self._hub_client: Optional[HubClient] = None
        self._hub_connected = False
        self._hub_websocket_task: Optional[asyncio.Task] = None
        # Store skill_service reference for reconnection
        self._skill_service: Optional["SkillService"] = None

    @property
    def client(self) -> Optional[HubClient]:
        """Get the HubClient if connected."""
        return self._hub_client if self._hub_connected else None

    @property
    def is_connected(self) -> bool:
        """Check if connected to Hub."""
        return self._hub_connected and self._hub_client is not None

    async def connect(self, skill_service: Optional["SkillService"] = None) -> bool:
        """Connect to the Hub using settings.

        Args:
            skill_service: Optional SkillService for skill registration.

        Returns:
            True if connection succeeded, False otherwise.
        """
        hub_url = self._get_setting("hub.url", "http://localhost:8000")
        hub_token = self._get_setting("hub.token", "")
        hub_timeout = self._get_setting("hub.timeout_seconds", 30)

        self._configure_ping_pong_logging()

        if not hub_token:
            logger.warning("Hub token not configured - skipping hub connection")
            await self._emit(ConnectionChanged(
                connected=False,
                error="Hub token not configured",
            ))
            return False

        try:
            config = HubConfig(
                url=hub_url,
                token=hub_token,
                timeout=hub_timeout,
            )
            self._hub_client = HubClient(config)

            # Check health
            healthy = await asyncio.wait_for(
                self._hub_client.health(),
                timeout=hub_timeout,
            )
            if not healthy:
                await self._emit(ConnectionChanged(
                    connected=False,
                    url=hub_url,
                    error="Hub is not responding",
                ))
                return False

            # Verify auth
            try:
                await asyncio.wait_for(
                    self._hub_client.get_device_info(),
                    timeout=hub_timeout,
                )
            except HubError as e:
                await self._emit(ConnectionChanged(
                    connected=False,
                    url=hub_url,
                    error=f"Hub authentication failed: {e}",
                ))
                return False

            self._hub_connected = True
            await self._emit(ConnectionChanged(
                connected=True,
                url=hub_url,
            ))
            logger.info(f"Connected to Hub at {hub_url}")

            # Store and register skills with hub
            if skill_service:
                self._skill_service = skill_service
            if self._skill_service:
                await self._register_skills(self._skill_service)

            # Connect WebSocket for skill execution requests
            self._hub_websocket_task = asyncio.create_task(
                self._hub_client.connect_websocket()
            )

            # Emit mode change
            await self._emit(ModeChanged(
                online=True,
                message="Connected to Hub. Remote devices API is available.",
            ))

            return True

        except asyncio.TimeoutError:
            logger.warning("Hub connection timed out")
            await self._emit(ConnectionChanged(
                connected=False,
                url=hub_url,
                error="Connection timed out",
            ))
            return False
        except Exception as e:
            logger.exception("Failed to connect to Hub")
            await self._emit(ConnectionChanged(
                connected=False,
                error=str(e),
            ))
            return False

    async def disconnect(self) -> None:
        """Disconnect from the Hub."""
        if self._hub_websocket_task:
            self._hub_websocket_task.cancel()
            try:
                await self._hub_websocket_task
            except asyncio.CancelledError:
                pass
            self._hub_websocket_task = None

        if self._hub_client:
            await self._hub_client.close()
            self._hub_client = None

        was_connected = self._hub_connected
        self._hub_connected = False

        if was_connected:
            await self._emit(ConnectionChanged(connected=False))
            await self._emit(ModeChanged(
                online=False,
                message="Disconnected from Hub. Running in local mode.",
            ))
            logger.info("Disconnected from Hub")

    def schedule_reconnection(self) -> None:
        """Schedule hub reconnection after settings change.

        Uses asyncio to run the reconnection in the background.
        """
        async def reconnect():
            try:
                await self.disconnect()
                await self.connect()
            except Exception as e:
                logger.error(f"Hub reconnection failed: {e}")

        loop = self._get_loop()
        if loop and loop.is_running():
            loop.create_task(reconnect())
            return

        logger.warning(
            "No running event loop available for hub reconnection; skipping."
        )

    async def _register_skills(self, skill_service: "SkillService") -> bool:
        """Register skills with Hub and start heartbeat.

        Args:
            skill_service: The SkillService to register.

        Returns:
            True if registration succeeded.
        """
        if not self._hub_client:
            return False

        # Attach hub client to skill service (enables remote device mode)
        skill_service.set_hub_client(self._hub_client)

        # Set up skill callback for Hub -> Spoke skill execution
        async def _ws_skill_callback(
            skill_name: str,
            method_name: str,
            args: list,
            kwargs: dict,
        ):
            return await skill_service.execute_skill_by_name(
                skill_name, method_name, args, kwargs
            )

        self._hub_client.set_skill_callback(_ws_skill_callback)

        # Register skills
        try:
            success = await skill_service.register_with_hub()
            if success:
                skills = skill_service.get_all_skills()
                logger.info(f"Registered {len(skills)} skill(s) with Hub")
                # Start heartbeat
                await skill_service.start_heartbeat()
                return True
            else:
                logger.warning("Failed to register skills with Hub")
                return False
        except HubError as e:
            logger.error(f"Failed to register skills with Hub: {e}")
            return False

    def _configure_ping_pong_logging(self) -> None:
        """Configure logging level for WebSocket ping/pong frames.

        Respects the `hub.log_ping_pong` setting (bool). When disabled, both
        `websockets.protocol` and `websockets.client` loggers are raised to
        WARNING to suppress ping/pong chatter. When enabled, they are dropped
        to DEBUG to surface detailed traffic.
        """
        log_ping_pong = bool(self._get_setting("hub.log_ping_pong", False))
        desired_level = logging.DEBUG if log_ping_pong else logging.WARNING

        for name in ("websockets.protocol", "websockets.client"):
            logging.getLogger(name).setLevel(desired_level)
