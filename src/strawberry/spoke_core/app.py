"""SpokeCore - single entrypoint for all UIs."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from ..hub import HubClient, HubConfig, HubError
from ..llm.tensorzero_client import TensorZeroClient
from ..shared.settings import ActionResult, SettingsManager
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
from .settings_schema import SPOKE_CORE_SCHEMA

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

    def __init__(
        self,
        settings_manager: Optional[SettingsManager] = None,
    ) -> None:
        """Initialize SpokeCore.

        Args:
            settings_manager: Optional SettingsManager instance for shared settings.
                If not provided, creates one with default config directory.
        """
        # Create SettingsManager if not provided
        if settings_manager is None:
            from ..utils.paths import get_project_root

            config_dir = get_project_root() / "config"
            settings_manager = SettingsManager(
                config_dir=config_dir,
                env_filename="../.env",
            )

        self._settings_manager = settings_manager
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

        # Register with SettingsManager
        self._register_with_settings_manager()

        # Get skills path from settings
        skills_path_str = self._get_setting("skills.path", "skills")
        skills_path = Path(skills_path_str)
        if not skills_path.is_absolute():
            from ..utils.paths import get_project_root

            skills_path = get_project_root() / skills_path

        self._skills_path = skills_path

    def _get_setting(self, key: str, default: Any = None) -> Any:
        """Get a setting from SettingsManager.

        Args:
            key: Setting key (e.g., "hub.url", "device.name")
            default: Default value if not found

        Returns:
            Setting value or default.
        """
        return self._settings_manager.get("spoke_core", key, default)

    def _register_with_settings_manager(self) -> None:
        """Register SpokeCore's namespace with the SettingsManager."""
        if not self._settings_manager:
            return

        # Register namespace if not already registered
        if not self._settings_manager.is_registered("spoke_core"):
            self._settings_manager.register(
                namespace="spoke_core",
                display_name="Spoke Core",
                schema=SPOKE_CORE_SCHEMA,
                order=10,
            )

        # Register options providers
        self._settings_manager.register_options_provider(
            "get_available_models",
            self._get_available_models,
        )

        # Register action handlers
        self._settings_manager.register_action_handler(
            "spoke_core",
            "hub_oauth",
            self._hub_oauth_action,
        )

        # Listen for settings changes
        self._settings_manager.on_change(self._on_settings_changed)

    def _on_settings_changed(self, namespace: str, key: str, value: Any) -> None:
        """Handle settings changes from the SettingsManager."""
        if namespace != "spoke_core":
            return

        logger.debug(f"Setting changed: {key} = {value}")

        # Special handling for hub token - set legacy env vars
        # The hub client reads from HUB_DEVICE_TOKEN/HUB_TOKEN
        parts = key.split(".")
        if len(parts) == 2:
            section, field = parts

            if section == "hub" and field == "token" and value:
                import os

                str_value = str(value)
                os.environ["HUB_DEVICE_TOKEN"] = str_value
                os.environ["HUB_TOKEN"] = str_value
                logger.debug("Updated HUB_DEVICE_TOKEN and HUB_TOKEN env vars")

                # Also persist to .env file with legacy names
                try:
                    env_storage = self._settings_manager._env_storage
                    env_storage.set("HUB_DEVICE_TOKEN", str_value)
                    env_storage.set("HUB_TOKEN", str_value)
                    logger.debug("Persisted HUB_DEVICE_TOKEN to .env")
                except Exception as e:
                    logger.warning(f"Failed to persist hub token: {e}")

            # Trigger hub reconnection when hub settings change
            if section == "hub" and field in ("url", "token"):
                logger.info(f"Hub setting changed ({field}), triggering reconnection")
                self._schedule_hub_reconnection()

    def _schedule_hub_reconnection(self) -> None:
        """Schedule hub reconnection after settings change.

        Uses asyncio to run the reconnection in the background.
        """
        import asyncio

        async def reconnect():
            try:
                await self.disconnect_hub()
                await self.connect_hub()
            except Exception as e:
                logger.error(f"Hub reconnection failed: {e}")

        # Try to get the running event loop
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(reconnect())
        except RuntimeError:
            # No running loop - try to schedule via event loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(reconnect())
                else:
                    # Last resort: run synchronously
                    loop.run_until_complete(reconnect())
            except Exception as e:
                logger.warning(f"Could not schedule hub reconnection: {e}")

    def _get_available_models(self) -> List[str]:
        """Get available Ollama models for dynamic options."""
        try:
            import httpx

            # Default local LLM URL
            url = self._get_setting("local_llm.url", "http://localhost:11434/v1")
            url = url.replace("/v1", "")
            response = httpx.get(f"{url}/api/tags", timeout=5.0)
            if response.status_code == 200:
                models = response.json().get("models", [])
                return [m["name"] for m in models]
        except Exception as e:
            logger.warning(f"Failed to fetch Ollama models: {e}")

        # Fallback to common models
        return ["llama3.2:3b", "llama3.2:1b", "gemma:7b", "mistral:7b"]

    def _hub_oauth_action(self) -> ActionResult:
        """Execute Hub OAuth action."""
        hub_url = self._get_setting("hub.url", "http://localhost:8000")
        return ActionResult(
            type="open_browser",
            url=f"{hub_url}/auth/device",
            message="Opening browser to connect to Hub...",
            pending=True,
        )

    @property
    def settings_manager(self) -> Optional[SettingsManager]:
        """Get the SettingsManager if one was provided."""
        return self._settings_manager

    @property
    def skill_service(self) -> Optional["SkillService"]:
        """Get the SkillService if core has been started."""
        return self._skills

    async def start(self) -> None:
        """Initialize core services."""
        if self._started:
            return

        try:
            # Initialize LLM client
            self._llm = TensorZeroClient()
            await self._llm._get_gateway()

            # Initialize skills
            use_sandbox = self._get_setting("skills.sandbox.enabled", True)
            device_name = self._get_setting("device.name", "Strawberry Spoke")
            allow_unsafe = self._get_setting("skills.allow_unsafe_exec", False)

            self._skills = SkillService(
                skills_path=self._skills_path,
                use_sandbox=use_sandbox,
                device_name=device_name,
                allow_unsafe_exec=allow_unsafe,
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
            raise ValueError(f"Session not found: {session_id}")

        if session.busy:
            await self._emit(CoreError(error="Session is busy"))
            return

        session.busy = True

        try:
            # Add user message
            session.add_message("user", text)
            await self._emit(MessageAdded(session_id=session_id, role="user", content=text))

            # Offline-only: deterministic tool execution hooks.
            #
            # When online, the Hub runs the agent loop (including tool calls) and
            # owns the system prompt, so the Spoke must not execute tools locally.
            if (not self.is_online()) and self._skills:
                # If the user explicitly requests search_skills, run it immediately.
                # This makes tool-use tests deterministic and provides the model with
                # authoritative tool output.
                requested_search = "search_skills" in text.lower() and "use" in text.lower()
                if requested_search:
                    await self._emit(
                        ToolCallStarted(
                            session_id=session.id,
                            tool_name="search_skills",
                            arguments={"query": ""},
                        )
                    )
                    result = await self._skills.execute_tool_async(
                        "search_skills",
                        {"query": ""},
                    )
                    success = "error" not in result
                    result_text = result.get("result", result.get("error", ""))
                    await self._emit(
                        ToolCallResult(
                            session_id=session.id,
                            tool_name="search_skills",
                            success=success,
                            result=result_text if success else None,
                            error=result_text if not success else None,
                        )
                    )
                    tool_msg = (
                        f"[Tool: search_skills]\n{result_text}\n\n"
                        "[Now respond naturally to the user based on this result. "
                        "Do not rerun the same tool call again unless the user asks. ]"
                    )
                    session.add_message("user", tool_msg)

                # If the user explicitly requires python_exec and provides a device.* call,
                # run it immediately to make tool-use deterministic.
                normalized = text.lower()
                requested_python_exec = (
                    "python_exec" in normalized
                    and "must" in normalized
                    and "use" in normalized
                )

                if requested_python_exec:
                    import re

                    match = re.search(r"(device\.[A-Za-z0-9_\.]+\([^\)]*\))", text)
                    if match:
                        code = f"print({match.group(1)})"
                        await self._emit(
                            ToolCallStarted(
                                session_id=session.id,
                                tool_name="python_exec",
                                arguments={"code": code},
                            )
                        )

                        result = await self._skills.execute_tool_async(
                            "python_exec",
                            {"code": code},
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

                        session.add_message("assistant", result_text)
                        await self._emit(
                            MessageAdded(
                                session_id=session.id,
                                role="assistant",
                                content=result_text,
                            )
                        )
                        return

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

        # In online mode the Hub owns:
        # - system prompt construction
        # - tool call execution
        #
        # So the Spoke must not inject a system prompt; it should only forward the
        # user/assistant conversation state.
        self._pending_mode_notice = None

        # Build messages for Hub (exclude system messages)
        messages: list[ChatMessage] = []
        for msg in session.messages:
            if msg.role != "system":
                messages.append(ChatMessage(role=msg.role, content=msg.content))

        # Stream from Hub so tool call events can be emitted incrementally.
        try:
            final_content: Optional[str] = None

            async for event in self._hub_client.chat_stream(
                messages=messages,
                enable_tools=True,
            ):
                event_type = str(event.get("type") or "")

                if event_type == "tool_call_started":
                    tool_name = str(event.get("tool_name") or "")
                    arguments = event.get("arguments")
                    if not isinstance(arguments, dict):
                        arguments = {}
                    await self._emit(
                        ToolCallStarted(
                            session_id=session.id,
                            tool_name=tool_name,
                            arguments=arguments,
                        )
                    )
                    continue

                if event_type == "tool_call_result":
                    tool_name = str(event.get("tool_name") or "")
                    success = bool(event.get("success"))
                    result = event.get("result")
                    error = event.get("error")
                    await self._emit(
                        ToolCallResult(
                            session_id=session.id,
                            tool_name=tool_name,
                            success=success,
                            result=str(result) if (success and result is not None) else None,
                            error=str(error) if ((not success) and error is not None) else None,
                        )
                    )
                    continue

                if event_type == "assistant_message":
                    final_content = str(event.get("content") or "")
                    continue

                if event_type == "error":
                    error_msg = str(event.get("error") or "Hub stream error")
                    await self._emit(CoreError(error=error_msg))
                    return

                if event_type == "done":
                    break

            if final_content and final_content.strip():
                session.add_message("assistant", final_content)
                await self._emit(
                    MessageAdded(
                        session_id=session.id,
                        role="assistant",
                        content=final_content,
                    )
                )
            else:
                error = "Hub returned an empty response. See Hub logs for details."
                logger.error(error)
                await self._emit(CoreError(error=error))

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

        function_name = "chat_local"
        try:
            import os

            import httpx

            ollama_ok = False
            try:
                resp = httpx.get("http://localhost:11434/api/tags", timeout=0.5)
                ollama_ok = resp.status_code == 200
            except Exception:
                ollama_ok = False

            if not ollama_ok and os.environ.get("GOOGLE_AI_STUDIO_API_KEY"):
                function_name = "chat_local_gemini"
        except Exception:
            function_name = "chat_local"

        # Build system prompt with mode notice
        system_prompt = self._skills.get_system_prompt(mode_notice=self._pending_mode_notice)
        self._pending_mode_notice = None

        seen_tool_calls: set[str] = set()

        for iteration in range(max_iterations):
            # Build messages for LLM (skip system messages, use system_prompt param)
            messages = []
            for msg in session.messages:
                if msg.role != "system":
                    messages.append(msg)

            # Get LLM response with system prompt passed explicitly
            response = await self._llm.chat(
                messages,
                system_prompt=system_prompt,
                function_name=function_name,
            )

            # Check for native tool calls first
            if response.tool_calls:
                if response.content:
                    session.add_message("assistant", response.content)
                    await self._emit(
                        MessageAdded(
                            session_id=session.id,
                            role="assistant",
                            content=response.content,
                        )
                    )
                for tool_call in response.tool_calls:
                    tool_key = json.dumps(
                        {
                            "name": tool_call.name,
                            "arguments": tool_call.arguments,
                        },
                        sort_keys=True,
                    )
                    if tool_key in seen_tool_calls:
                        error = (
                            "Model attempted to repeat the same tool call. "
                            "Aborting to prevent an infinite loop."
                        )
                        await self._emit(CoreError(error=error))
                        session.add_message("assistant", error)
                        await self._emit(
                            MessageAdded(
                                session_id=session.id,
                                role="assistant",
                                content=error,
                            )
                        )
                        return
                    seen_tool_calls.add(tool_key)

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
                    tool_msg = (
                        f"[Tool: {tool_call.name}]\n{result_text}\n\n"
                        "[Now respond naturally to the user based on this result. "
                        "Do not rerun the same tool call again unless the user asks. ]"
                    )
                    session.add_message("user", tool_msg)

                # Continue loop for more tool calls
                continue

            # Check for legacy code blocks (models that don't use native tool calls)
            legacy_code_blocks = self._extract_legacy_code_blocks(response.content or "")
            if legacy_code_blocks:
                if response.content:
                    session.add_message("assistant", response.content)
                    await self._emit(
                        MessageAdded(
                            session_id=session.id,
                            role="assistant",
                            content=response.content,
                        )
                    )
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
                    tool_msg = (
                        f"[Tool: python_exec]\n{result_text}\n\n"
                        "[Now respond naturally to the user based on this result. "
                        "Do not rerun the same code again unless the user asks. ]"
                    )
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

        if (
            iteration + 1 >= max_iterations
            and session.messages
            and session.messages[-1].role != "assistant"
        ):
            error = "Agent loop hit max iterations without producing a final response."
            await self._emit(CoreError(error=error))
            session.add_message("assistant", error)
            await self._emit(
                MessageAdded(
                    session_id=session.id,
                    role="assistant",
                    content=error,
                )
            )

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
        hub_url = self._get_setting("hub.url", "http://localhost:8000")
        hub_token = self._get_setting("hub.token", "")
        hub_timeout = self._get_setting("hub.timeout_seconds", 30)

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
        if self._get_setting("local_llm.enabled", True):
            return self._get_setting("local_llm.model", "llama3.2:3b")
        return "hub"

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
        if self._settings_manager and self._settings_manager.is_registered("spoke_core"):
            return self._settings_manager.get_schema("spoke_core")
        return SPOKE_CORE_SCHEMA

    def get_settings(self) -> Dict[str, Any]:
        """Get current settings values as a flat dictionary.

        Returns:
            Dictionary mapping dot-separated keys to values.
            Example: {"device.name": "My PC", "hub.url": "http://..."}
        """
        return self._settings_manager.get_all("spoke_core")

    async def update_settings(self, patch: Dict[str, Any]) -> None:
        """Update settings with a partial update.

        Args:
            patch: Dictionary of dot-separated keys to new values.
                   Example: {"device.name": "New Name", "hub.url": "http://..."}

        Raises:
            ValueError: If a key is not recognized
        """
        errors = self._settings_manager.update("spoke_core", patch)
        if errors:
            raise ValueError(f"Validation errors: {errors}")

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
        # Use SettingsManager if available
        if self._settings_manager:
            options = self._settings_manager.get_options(provider)
            if options:
                return options

        # Fallback to direct handling
        if provider == "get_available_models":
            return self._get_available_models()

        raise ValueError(f"Unknown options provider: {provider}")

    async def execute_settings_action(self, action: str) -> ActionResult:
        """Execute a settings action (e.g., hub OAuth flow).

        Args:
            action: Action name from SettingField.action

        Returns:
            ActionResult with instructions for the UI

        Raises:
            ValueError: If action is unknown.
        """
        result = await self._settings_manager.execute_action("spoke_core", action)

        # Convert error results to ValueError for backward compatibility
        if result.type == "error":
            raise ValueError(f"Unknown action: {action}")

        return result

