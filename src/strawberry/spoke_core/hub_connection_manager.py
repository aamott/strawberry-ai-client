"""HubConnectionManager - manages Hub connection lifecycle for SpokeCore."""

import asyncio
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from ..hub import HubClient, HubConfig, HubError
from .events import ConnectionChanged, CoreEvent, ModeChanged

if TYPE_CHECKING:
    from ..skills.service import SkillService

logger = logging.getLogger(__name__)

# File where we persist the Hub-assigned device ID between runs.
_DEVICE_ID_FILENAME = ".device_id"


def _config_dir() -> Path:
    """Resolve the Spoke config directory.

    Checks STRAWBERRY_CONFIG_DIR env var then falls back to
    ``ai-pc-spoke/config`` relative to the repo root.
    """
    env = os.environ.get("STRAWBERRY_CONFIG_DIR")
    if env:
        return Path(env)
    # Fall back: assume repo-root/ai-pc-spoke/config
    return Path(__file__).resolve().parents[3] / "config"


def read_persisted_device_id() -> Optional[str]:
    """Read the persisted device ID from disk, if any."""
    path = _config_dir() / _DEVICE_ID_FILENAME
    if path.exists():
        device_id = path.read_text().strip()
        if device_id:
            return device_id
    return None


def write_persisted_device_id(device_id: str) -> None:
    """Write the Hub-assigned device ID to disk."""
    path = _config_dir() / _DEVICE_ID_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(device_id)
    logger.info("Persisted device_id to %s", path)


class HubConnectionManager:
    """Manages Hub connection lifecycle.

    Responsibilities:
    - Connect/disconnect from Hub
    - Health checks and authentication
    - Device registration (Hub-assigned device ID)
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
        if skill_service is not None:
            self._skill_service = skill_service

        hub_url = self._get_setting("hub.url", "http://localhost:8000")
        hub_token = self._get_setting("hub.token", "")
        hub_timeout = self._get_setting("hub.timeout_seconds", 30)

        if not hub_token:
            logger.warning("Hub token not configured - skipping hub connection")
            await self._emit(
                ConnectionChanged(
                    connected=False,
                    error="Hub token not configured",
                )
            )
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
                await self._emit(
                    ConnectionChanged(
                        connected=False,
                        url=hub_url,
                        error="Hub is not responding",
                    )
                )
                return False

            # Verify auth
            try:
                await asyncio.wait_for(
                    self._hub_client.get_device_info(),
                    timeout=hub_timeout,
                )
            except HubError as e:
                await self._emit(
                    ConnectionChanged(
                        connected=False,
                        url=hub_url,
                        error=f"Hub authentication failed: {e}",
                    )
                )
                return False

            # --- Device registration ---
            device_name = self._get_setting("device.name", "Strawberry Spoke")
            persisted_id = read_persisted_device_id()

            try:
                reg_result = await asyncio.wait_for(
                    self._hub_client.register_device(
                        device_name=device_name,
                        device_id=persisted_id,
                    ),
                    timeout=hub_timeout,
                )
                assigned_id = reg_result["device_id"]
                display_name = reg_result["display_name"]
                write_persisted_device_id(assigned_id)
                logger.info(
                    "Device registered: id=%s display_name=%s",
                    assigned_id,
                    display_name,
                )
            except Exception as e:
                logger.warning("Device registration failed: %s (continuing)", e)
                # Non-fatal: the hub still accepted our auth.

            self._hub_connected = True
            await self._emit(
                ConnectionChanged(
                    connected=True,
                    url=hub_url,
                )
            )
            logger.info(f"Connected to Hub at {hub_url}")

            # Register skills with hub
            if self._skill_service:
                await self._register_skills(self._skill_service)

            # Set up WebSocket connection callback so we detect
            # when the hub goes offline (WebSocket drops) and can
            # emit ConnectionChanged / ModeChanged events + auto-reconnect.
            self._hub_client.set_connection_callback(self._on_ws_connection_changed)

            # Connect WebSocket for skill execution requests
            self._hub_websocket_task = asyncio.create_task(
                self._hub_client.connect_websocket()
            )

            # Emit mode change
            await self._emit(
                ModeChanged(
                    online=True,
                    message="Connected to Hub. Remote devices API is available.",
                )
            )

            return True

        except asyncio.TimeoutError:
            logger.warning("Hub connection timed out")
            await self._emit(
                ConnectionChanged(
                    connected=False,
                    url=hub_url,
                    error="Connection timed out",
                )
            )
            return False
        except Exception as e:
            logger.exception("Failed to connect to Hub")
            await self._emit(
                ConnectionChanged(
                    connected=False,
                    error=str(e),
                )
            )
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
            await self._emit(
                ModeChanged(
                    online=False,
                    message="Disconnected from Hub. Running in local mode.",
                )
            )
            logger.info("Disconnected from Hub")

    def schedule_reconnection(
        self,
        skill_service: Optional["SkillService"] = None,
    ) -> None:
        """Schedule hub reconnection after settings change.

        Uses asyncio to run the reconnection in the background.

        Args:
            skill_service: Optional SkillService to retain for reconnect-time
                skill registration.
        """

        if skill_service is not None:
            self._skill_service = skill_service

        async def reconnect():
            try:
                await self.disconnect()
                await self.connect(skill_service=self._skill_service)
            except Exception as e:
                logger.error(f"Hub reconnection failed: {e}")

        loop = self._get_loop()
        if loop and loop.is_running():
            loop.create_task(reconnect())
            return

        logger.warning("No running event loop available for hub reconnection; skipping.")

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

    async def _on_ws_connection_changed(self, connected: bool) -> None:
        """Handle WebSocket connection state changes from HubClient.

        Called by the HubClient's _websocket_loop when the WebSocket
        connects or disconnects. Emits ConnectionChanged and ModeChanged
        events so the UI can react (toast notifications, status bar).

        Args:
            connected: True if WebSocket reconnected, False if it dropped.
        """
        if connected:
            # WebSocket reconnected after a drop
            if not self._hub_connected:
                self._hub_connected = True
                logger.info("Hub WebSocket reconnected")
                await self._emit(ConnectionChanged(connected=True))
                await self._emit(
                    ModeChanged(
                        online=True,
                        message="Reconnected to Hub.",
                    )
                )
                # Re-register skills after reconnection
                if self._skill_service:
                    # Hub may still be starting up; retry a few times before giving up
                    for attempt in range(3):
                        success = await self._register_skills(self._skill_service)
                        if success:
                            break
                        logger.warning(
                            "Skill re-registration failed on reconnect (attempt %d/3)",
                            attempt + 1,
                        )
                        await asyncio.sleep(2)
                    else:
                        logger.error("Skill re-registration failed after hub reconnect")
        else:
            # WebSocket dropped — hub went offline
            if self._hub_connected:
                self._hub_connected = False
                logger.warning("Hub WebSocket disconnected")
                await self._emit(
                    ConnectionChanged(
                        connected=False,
                        error="Hub connection lost",
                    )
                )
                await self._emit(
                    ModeChanged(
                        online=False,
                        message="Lost connection to Hub. Running in local mode.",
                    )
                )
