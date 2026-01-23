"""SpokeCore - single entrypoint for all UIs."""

import asyncio
import logging
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from ..config import get_settings
from ..config.loader import load_config, reset_settings
from ..hub import HubClient, HubConfig, HubError
from ..llm.tensorzero_client import TensorZeroClient
from ..skills.service import SkillService
from .events import (
    ConnectionChanged,
    CoreError,
    CoreEvent,
    CoreReady,
    MessageAdded,
    ModeChanged,
    ToolCallResult,
    ToolCallStarted,
)
from .session import ChatSession
from .settings_schema import ActionResult

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


class SpokeCore:
    """Primary entrypoint for Spoke UIs.

    Responsibilities:
    - Loading settings + config
    - Wiring skills + tool schemas
    - Exposing chat session abstraction
    - Managing agent loop (online/offline)
    """

    def __init__(self, settings_path: Optional[str] = None) -> None:
        """Initialize SpokeCore.

        Args:
            settings_path: Optional path to a config.yaml to load instead of the
                default project config.
        """
        self._settings = self._load_settings(settings_path)
        self._llm: Optional[TensorZeroClient] = None
        self._skills: Optional[SkillService] = None
        self._hub_client: Optional[HubClient] = None
        self._sessions: Dict[str, ChatSession] = {}
        self._subscribers: List[asyncio.Queue] = []
        self._started = False
        self._hub_connected = False

        # Track mode state for mode notices (like QT UI)
        self._last_online_state: Optional[bool] = None
        self._pending_mode_notice: Optional[str] = None

        # Paths from settings
        skills_path = Path(self._settings.skills.path)
        if not skills_path.is_absolute():
            # Relative to ai-pc-spoke root
            from ..utils.paths import get_project_root
            skills_path = get_project_root() / skills_path

        self._skills_path = skills_path

    def _load_settings(self, settings_path: Optional[str]) -> Any:
        """Load settings with optional config path override.

        Args:
            settings_path: Optional path to a config.yaml to load.

        Returns:
            Loaded Settings instance.
        """
        if not settings_path:
            return get_settings()

        config_path = Path(settings_path)
        if not config_path.is_absolute():
            from ..utils.paths import get_project_root
            config_path = get_project_root() / config_path

        reset_settings()
        logger.info("Loading settings override from %s", config_path)
        return load_config(config_path=config_path)

    async def start(self) -> None:
        """Initialize core services."""
        if self._started:
            return

        try:
            # Initialize LLM client
            self._llm = TensorZeroClient()
            await self._llm._get_gateway()

            # Initialize skills
            self._skills = SkillService(
                skills_path=self._skills_path,
                use_sandbox=self._settings.skills.sandbox.enabled,
                device_name=self._settings.device.name,
                allow_unsafe_exec=self._settings.skills.allow_unsafe_exec,
            )
            self._skills.load_skills()

            self._started = True
            await self._emit(CoreReady())
            logger.info("SpokeCore started")

        except Exception as e:
            logger.error(f"SpokeCore start failed: {e}")
            await self._emit(CoreError(error=str(e), exception=e))
            raise

    async def stop(self) -> None:
        """Shutdown core services."""
        # Close hub connection
        if self._hub_client:
            await self._hub_client.close()
            self._hub_client = None
            self._hub_connected = False

        if self._llm:
            await self._llm.close()
            self._llm = None

        if self._skills:
            await self._skills.shutdown()
            self._skills = None

        self._started = False
        logger.info("SpokeCore stopped")

    def new_session(self) -> ChatSession:
        """Create a new chat session."""
        session = ChatSession()
        self._sessions[session.id] = session
        return session


    def get_session(self, session_id: str) -> Optional[ChatSession]:
        """Get session by ID."""
        return self._sessions.get(session_id)

    async def send_message(self, session_id: str, text: str) -> None:
        """Send a user message and run the agent loop."""
        session = self._sessions.get(session_id)
        if not session:
            await self._emit(CoreError(error=f"Session not found: {session_id}"))
            return

        if session.busy:
            await self._emit(CoreError(error="Session is busy"))
            return

        session.busy = True

        try:
            # Add user message
            session.add_message("user", text)
            await self._emit(MessageAdded(session_id=session_id, role="user", content=text))

            # Run agent loop
            await self._agent_loop(session)

        except Exception as e:
            logger.error(f"Agent loop error: {e}")
            await self._emit(CoreError(error=str(e), exception=e))
        finally:
            session.busy = False

    async def _agent_loop(self, session: ChatSession, max_iterations: int = 5) -> None:
        """Run the agent loop with tool execution.

        When online (connected to Hub), routes chat through Hub with enable_tools=True
        so the Hub runs the agent loop and executes skills on registered devices.

        When offline, runs the agent loop locally using TensorZeroClient.
        """
        if not self._skills:
            await self._emit(CoreError(error="Core not started"))
            return

        # Check if online state changed and update mode notice
        current_online = self.is_online()
        if self._last_online_state is not None and current_online != self._last_online_state:
            if current_online:
                self._pending_mode_notice = (
                    "Runtime mode switched to ONLINE (Hub). "
                    "Remote devices API is available. "
                    "Use devices.<Device>.<SkillName>.<method>(...)."
                )
            else:
                self._pending_mode_notice = (
                    "Runtime mode switched to OFFLINE/LOCAL. "
                    "The Hub/remote devices API is unavailable. "
                    "Use only device.<SkillName>.<method>(...)."
                )
        self._last_online_state = current_online

        # Route based on online/offline mode
        if current_online and self._hub_client:
            await self._agent_loop_hub(session)
        else:
            await self._agent_loop_local(session, max_iterations)

    async def _agent_loop_hub(self, session: ChatSession) -> None:
        """Run agent loop via Hub (Hub executes tools on registered devices)."""
        from ..models import ChatMessage

        # Build system prompt with mode notice
        system_prompt = self._skills.get_system_prompt(mode_notice=self._pending_mode_notice)
        self._pending_mode_notice = None

        # Build messages for Hub
        messages = [ChatMessage(role="system", content=system_prompt)]
        for msg in session.messages:
            if msg.role != "system":
                messages.append(ChatMessage(role=msg.role, content=msg.content))

        # Send to Hub with enable_tools=True - Hub runs the agent loop
        try:
            response = await self._hub_client.chat(
                messages=messages,
                enable_tools=True,  # Hub executes skills
            )

            # Add response to session
            if response.content:
                session.add_message("assistant", response.content)
                await self._emit(
                    MessageAdded(
                        session_id=session.id,
                        role="assistant",
                        content=response.content,
                    )
                )

        except HubError as e:
            logger.error(f"Hub chat failed: {e}")
            await self._emit(CoreError(error=f"Hub error: {e}"))

    async def _agent_loop_local(
        self, session: ChatSession, max_iterations: int = 5
    ) -> None:
        """Run agent loop locally (for offline mode)."""
        if not self._llm:
            await self._emit(CoreError(error="Local LLM not available"))
            return

        # Build system prompt with mode notice
        system_prompt = self._skills.get_system_prompt(mode_notice=self._pending_mode_notice)
        self._pending_mode_notice = None

        for iteration in range(max_iterations):
            # Build messages for LLM (skip system messages, use system_prompt param)
            messages = []
            for msg in session.messages:
                if msg.role != "system":
                    messages.append(msg)

            # Get LLM response with system prompt passed explicitly
            response = await self._llm.chat(messages, system_prompt=system_prompt)

            # Check for native tool calls first
            if response.tool_calls:
                for tool_call in response.tool_calls:
                    await self._emit(
                        ToolCallStarted(
                            session_id=session.id,
                            tool_name=tool_call.name,
                            arguments=tool_call.arguments,
                        )
                    )

                    # Execute tool
                    result = await self._skills.execute_tool_async(
                        tool_call.name, tool_call.arguments
                    )

                    success = "error" not in result
                    result_text = result.get("result", result.get("error", ""))

                    await self._emit(
                        ToolCallResult(
                            session_id=session.id,
                            tool_name=tool_call.name,
                            success=success,
                            result=result_text if success else None,
                            error=result_text if not success else None,
                        )
                    )

                    # Add tool result to session for next iteration
                    tool_msg = f"[Tool: {tool_call.name}]\n{result_text}"
                    session.add_message("user", tool_msg)

                # Continue loop for more tool calls
                continue

            # Check for legacy code blocks (models that don't use native tool calls)
            legacy_code_blocks = self._extract_legacy_code_blocks(response.content or "")
            if legacy_code_blocks:
                for code in legacy_code_blocks:
                    await self._emit(
                        ToolCallStarted(
                            session_id=session.id,
                            tool_name="python_exec",
                            arguments={"code": code},
                        )
                    )

                    # Execute via python_exec tool
                    result = await self._skills.execute_tool_async(
                        "python_exec", {"code": code}
                    )

                    success = "error" not in result
                    result_text = result.get("result", result.get("error", ""))

                    await self._emit(
                        ToolCallResult(
                            session_id=session.id,
                            tool_name="python_exec",
                            success=success,
                            result=result_text if success else None,
                            error=result_text if not success else None,
                        )
                    )

                    # Add tool result to session for next iteration
                    tool_msg = f"[Tool: python_exec]\n{result_text}"
                    session.add_message("user", tool_msg)

                # Continue loop for more iterations
                continue

            # No tool calls - final response
            if response.content:
                session.add_message("assistant", response.content)
                await self._emit(
                    MessageAdded(
                        session_id=session.id,
                        role="assistant",
                        content=response.content,
                    )
                )
            break

    def _extract_legacy_code_blocks(self, content: str) -> List[str]:
        """Extract executable code blocks from LLM response.

        Handles models that return code in fenced blocks instead of
        using native tool calls. Looks for:
        - ```tool_code ... ``` blocks
        - ```python ... ``` blocks containing device.* calls
        - Bare device.*/devices.* lines

        Args:
            content: LLM response text

        Returns:
            List of code strings to execute
        """
        import re

        code_blocks = []

        # Extract fenced code blocks
        # Match ```tool_code, ```python, or just ``` with device calls
        # Allow optional newline after opening fence
        pattern = r"```(?:tool_code|python|py)?\s*\n?(.*?)```"
        matches = re.findall(pattern, content, re.DOTALL | re.IGNORECASE)

        for match in matches:
            code = match.strip()
            # Only include if it looks like a skill call
            if any(prefix in code for prefix in [
                "device.", "devices.", "device_manager.",
                "print(device.", "print(devices."
            ]):
                code_blocks.append(code)

        # Also check for bare device calls not in code blocks
        if not code_blocks:
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith((
                    "device.", "devices.", "device_manager.",
                    "print(device.", "print(devices.", "print(device_manager."
                )):
                    code_blocks.append(stripped)

        return code_blocks

    def get_system_prompt(self) -> str:
        """Get the current system prompt."""
        if self._skills:
            return self._skills.get_system_prompt()
        return "You are a helpful assistant."

    def is_online(self) -> bool:
        """Check if connected to Hub."""
        return self._hub_connected and self._hub_client is not None

    @property
    def hub_client(self) -> Optional[HubClient]:
        """Get the hub client if connected."""
        return self._hub_client if self._hub_connected else None

    async def connect_hub(self) -> bool:
        """Connect to the Hub using settings.

        Returns:
            True if connection succeeded, False otherwise.
        """
        hub_settings = self._settings.hub
        if not hub_settings.token:
            logger.warning("Hub token not configured - skipping hub connection")
            await self._emit(ConnectionChanged(
                connected=False,
                error="Hub token not configured",
            ))
            return False

        try:
            config = HubConfig(
                url=hub_settings.url,
                token=hub_settings.token,
                timeout=hub_settings.timeout_seconds,
            )
            self._hub_client = HubClient(config)

            # Check health
            healthy = await asyncio.wait_for(
                self._hub_client.health(),
                timeout=hub_settings.timeout_seconds,
            )
            if not healthy:
                await self._emit(ConnectionChanged(
                    connected=False,
                    url=hub_settings.url,
                    error="Hub is not responding",
                ))
                return False

            # Verify auth
            try:
                await asyncio.wait_for(
                    self._hub_client.get_device_info(),
                    timeout=hub_settings.timeout_seconds,
                )
            except HubError as e:
                await self._emit(ConnectionChanged(
                    connected=False,
                    url=hub_settings.url,
                    error=f"Hub authentication failed: {e}",
                ))
                return False

            self._hub_connected = True
            await self._emit(ConnectionChanged(
                connected=True,
                url=hub_settings.url,
            ))
            logger.info(f"Connected to Hub at {hub_settings.url}")

            # Register skills with hub
            await self._register_skills_with_hub()

            # Connect WebSocket for skill execution requests
            asyncio.create_task(self._hub_client.connect_websocket())

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
                url=hub_settings.url,
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

    async def disconnect_hub(self) -> None:
        """Disconnect from the Hub."""
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

    async def _register_skills_with_hub(self) -> bool:
        """Register skills with Hub and start heartbeat.

        Returns:
            True if registration succeeded.
        """
        if not self._hub_client or not self._skills:
            return False

        # Attach hub client to skill service (enables remote device mode)
        self._skills.set_hub_client(self._hub_client)

        # Set up skill callback for Hub -> Spoke skill execution
        async def _ws_skill_callback(
            skill_name: str,
            method_name: str,
            args: list,
            kwargs: dict,
        ):
            return await self._skills.execute_skill_by_name(
                skill_name, method_name, args, kwargs
            )

        self._hub_client.set_skill_callback(_ws_skill_callback)

        # Register skills
        try:
            success = await self._skills.register_with_hub()
            if success:
                skills = self._skills.get_all_skills()
                logger.info(f"Registered {len(skills)} skill(s) with Hub")
                # Start heartbeat
                await self._skills.start_heartbeat()
                return True
            else:
                logger.warning("Failed to register skills with Hub")
                return False
        except HubError as e:
            logger.error(f"Failed to register skills with Hub: {e}")
            return False

    def get_model_info(self) -> str:
        """Get current model name."""
        return self._settings.local_llm.model if self._settings.local_llm.enabled else "hub"

    # Event system
    async def _emit(self, event: CoreEvent) -> None:
        """Emit an event to all subscribers."""
        for queue in self._subscribers:
            await queue.put(event)

    def subscribe(self, handler: Callable[[CoreEvent], Any]) -> Subscription:
        """Subscribe to events with a callback handler."""
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

        task = asyncio.create_task(reader())

        def cancel():
            task.cancel()
            if queue in self._subscribers:
                self._subscribers.remove(queue)

        return Subscription(cancel)

    async def events(self) -> AsyncIterator[CoreEvent]:
        """Async iterator for events."""
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            self._subscribers.remove(queue)

    # Settings API
    def get_settings_schema(self) -> List[Any]:
        """Get the core settings schema for UI rendering.

        Returns:
            List of SettingField objects defining configurable options
        """
        from .settings_schema import CORE_SETTINGS_SCHEMA
        return CORE_SETTINGS_SCHEMA

    def get_settings(self) -> Dict[str, Any]:
        """Get current settings values as a flat dictionary.

        Returns:
            Dictionary mapping dot-separated keys to values.
            Example: {"device.name": "My PC", "hub.url": "http://..."}
        """
        settings = self._settings
        result = {}

        # Flatten Pydantic model to dot-separated keys
        result["device.name"] = settings.device.name
        result["device.id"] = settings.device.id
        result["hub.url"] = settings.hub.url
        result["hub.token"] = settings.hub.token or ""
        result["hub.timeout_seconds"] = settings.hub.timeout_seconds
        result["local_llm.enabled"] = settings.local_llm.enabled
        result["local_llm.model"] = settings.local_llm.model
        result["local_llm.url"] = settings.local_llm.url
        result["stt.backend"] = settings.stt.backend
        result["tts.backend"] = settings.tts.backend
        result["voice.audio_feedback_enabled"] = settings.voice.audio_feedback_enabled
        result["ui.theme"] = settings.ui.theme

        return result

    async def update_settings(self, patch: Dict[str, Any]) -> None:
        """Update settings with a partial update.

        Args:
            patch: Dictionary of dot-separated keys to new values.
                   Example: {"device.name": "New Name", "hub.url": "http://..."}

        Raises:
            ValueError: If a key is not recognized
        """
        from ..config.persistence import save_settings

        # Apply patch to settings object
        for key, value in patch.items():
            parts = key.split(".")
            if len(parts) == 2:
                section, field = parts
                section_obj = getattr(self._settings, section, None)
                if section_obj and hasattr(section_obj, field):
                    setattr(section_obj, field, value)
                else:
                    raise ValueError(f"Unknown setting: {key}")
            else:
                raise ValueError(f"Invalid key format: {key}")

        # Persist to disk
        await asyncio.to_thread(save_settings, self._settings)

        # Emit settings changed event
        from .events import SettingsChanged
        await self._emit(SettingsChanged(changed_keys=list(patch.keys())))

        logger.info(f"Settings updated: {list(patch.keys())}")

    def get_settings_options(self, provider: str) -> List[str]:
        """Get dynamic options for a DYNAMIC_SELECT field.

        Args:
            provider: The options_provider name from the SettingField

        Returns:
            List of available options
        """
        if provider == "get_available_models":
            # Try to get models from Ollama
            try:
                import httpx
                url = self._settings.local_llm.url.replace("/v1", "")
                response = httpx.get(f"{url}/api/tags", timeout=5.0)
                if response.status_code == 200:
                    models = response.json().get("models", [])
                    return [m["name"] for m in models]
            except Exception as e:
                logger.warning(f"Failed to fetch Ollama models: {e}")

            # Fallback to common models
            return ["llama3.2:3b", "llama3.2:1b", "gemma:7b", "mistral:7b"]

        raise ValueError(f"Unknown options provider: {provider}")

    async def execute_settings_action(self, action: str) -> "ActionResult":
        """Execute a settings action (e.g., hub OAuth flow).

        Args:
            action: Action name from SettingField.action

        Returns:
            ActionResult with instructions for the UI
        """
        from .settings_schema import ActionResult

        if action == "hub_oauth":
            return ActionResult(
                type="open_browser",
                url=f"{self._settings.hub.url}/auth/device",
                message="Opening browser to connect to Hub...",
                pending=True,
            )

        raise ValueError(f"Unknown action: {action}")

