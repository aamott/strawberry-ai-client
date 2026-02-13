"""SpokeCore - single entrypoint for all UIs."""

import asyncio
import logging
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from ..hub import HubClient
from ..llm.tensorzero_client import TensorZeroClient
from ..shared.settings import ActionResult, SettingsManager
from .agent_runner import HubAgentRunner, LocalAgentRunner
from .event_bus import EventBus, Subscription
from .events import (
    CoreError,
    CoreEvent,
    CoreReady,
    MessageAdded,
)
from .hub_connection_manager import HubConnectionManager
from .session import ChatSession
from .settings_schema import (
    SPOKE_CORE_SCHEMA,
    register_skills_config_schema,
    register_spoke_core_schema,
)
from .skill_manager import SkillManager

logger = logging.getLogger(__name__)


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
        self._skill_mgr: Optional[SkillManager] = None
        self._sessions: Dict[str, ChatSession] = {}
        self._event_bus = EventBus()
        self._started = False

        # Hub connection management (delegate to HubConnectionManager)
        self._hub_manager = HubConnectionManager(
            get_setting=self._get_setting,
            emit=self._emit,
            get_loop=lambda: self._event_bus.loop,
        )

        # Agent runners (initialized in start())
        self._hub_runner: Optional[HubAgentRunner] = None
        self._local_runner: Optional[LocalAgentRunner] = None

        # Cache for available models (avoids repeated sync network calls)
        self._models_cache: Optional[List[str]] = None
        self._models_cache_time: float = 0.0
        self._models_cache_ttl: float = 60.0  # seconds

        # Register with SettingsManager
        self._register_with_settings_manager()

        # Get skills path from settings (lives in skills_config namespace)
        skills_path_str = self._settings_manager.get(
            "skills_config", "path", "skills",
        )
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

        # Register namespace (with migrations) if not already registered
        register_spoke_core_schema(self._settings_manager)

        # Register TensorZero provider settings
        from ..llm.tensorzero_settings import register_tensorzero_schema

        register_tensorzero_schema(self._settings_manager)

        # Register skills config on Skills tab
        register_skills_config_schema(self._settings_manager)

        # Register GUI appearance settings (themes, font size, etc.)
        from ..ui.gui_v2.settings_schema import register_gui_schema

        register_gui_schema(self._settings_manager)

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

    def _on_settings_changed(
        self, namespace: str, key: str, value: Any,
    ) -> None:
        """Handle settings changes from the SettingsManager."""
        logger.debug("Setting changed: %s.%s", namespace, key)

        # TensorZero provider settings changed → regenerate TOML + restart
        if namespace == "tensorzero":
            self._schedule_tensorzero_restart()
            return

        if namespace != "spoke_core":
            return

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
                    self._settings_manager.set_env(
                        "HUB_DEVICE_TOKEN", str_value,
                    )
                    self._settings_manager.set_env("HUB_TOKEN", str_value)
                    logger.debug("Persisted HUB_DEVICE_TOKEN to .env")
                except Exception as e:
                    logger.warning(f"Failed to persist hub token: {e}")

            # Trigger hub reconnection when hub settings change
            if section == "hub" and field in ("url", "token"):
                logger.info(
                    "Hub setting changed (%s), triggering reconnection",
                    field,
                )
                self._schedule_hub_reconnection()
                # Hub URL/token also affect TensorZero config
                self._schedule_tensorzero_restart()

            # Update system prompt at runtime when setting changes
            if section == "llm" and field == "system_prompt" and self._skill_mgr:
                self._skill_mgr.set_custom_system_prompt(value or None)
                logger.info("Updated custom system prompt from settings")

    def _schedule_hub_reconnection(self) -> None:
        """Schedule hub reconnection after settings change."""
        self._hub_manager.schedule_reconnection()

    def _schedule_tensorzero_restart(self) -> None:
        """Regenerate TensorZero TOML and restart the gateway."""
        if not self._llm or not self._settings_manager:
            return

        try:
            from ..llm.tensorzero_config import write_generated_config

            config_path = write_generated_config(self._settings_manager)
            logger.info("Regenerated TensorZero config: %s", config_path)

            # Schedule async restart on the event loop
            loop = self._event_bus._loop
            if loop and loop.is_running():
                loop.create_task(self._restart_tensorzero(config_path))
        except Exception as e:
            logger.error("Failed to regenerate TensorZero config: %s", e)

    async def _restart_tensorzero(self, config_path: str) -> None:
        """Restart the TensorZero gateway with a new config.

        Args:
            config_path: Path to the new TOML config file.
        """
        try:
            await self._llm.restart(config_path)
            logger.info("TensorZero gateway restarted successfully")
        except Exception as e:
            logger.error("TensorZero gateway restart failed: %s", e)

    def _get_available_models(self) -> List[str]:
        """Get available Ollama models for dynamic options.

        Uses a 60-second cache to avoid repeated synchronous network calls
        that could freeze UI threads.
        """
        import time

        # Check cache first
        now = time.time()
        if (
            self._models_cache
            and (now - self._models_cache_time) < self._models_cache_ttl
        ):
            return self._models_cache

        try:
            import httpx

            # Read Ollama URL from tensorzero namespace
            url = self._settings_manager.get(
                "tensorzero", "ollama.url", "http://localhost:11434/v1",
            )
            url = url.replace("/v1", "")
            response = httpx.get(f"{url}/api/tags", timeout=5.0)
            if response.status_code == 200:
                models = response.json().get("models", [])
                self._models_cache = [m["name"] for m in models]
                self._models_cache_time = now
                return self._models_cache
        except Exception as e:
            logger.warning(f"Failed to fetch Ollama models: {e}")

        # Fallback to common models (also cached)
        fallback = ["llama3.2:3b", "llama3.2:1b", "gemma:7b", "mistral:7b"]
        self._models_cache = fallback
        self._models_cache_time = now
        return fallback

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
    def skill_service(self):
        """Get the SkillService if core has been started."""
        return self._skill_mgr.service if self._skill_mgr else None

    async def start(
        self,
        on_skill_loaded: Optional[Callable] = None,
        on_skill_failed: Optional[Callable] = None,
    ) -> None:
        """Initialize core services.

        Args:
            on_skill_loaded: Optional callback invoked per skill during
                loading.  Signature: ``(name, source, elapsed_ms)``.
                Useful for verbose CLI output without coupling SpokeCore
                to any particular UI.
            on_skill_failed: Optional callback invoked per failed skill.
                Signature: ``(source, error, skill_name_if_known)``.
        """
        if self._started:
            return

        try:
            self._event_bus.set_loop(asyncio.get_running_loop())

            # Generate TensorZero config from settings before starting
            if self._settings_manager:
                try:
                    from ..llm.tensorzero_config import write_generated_config

                    config_path = write_generated_config(
                        self._settings_manager,
                    )
                    logger.info(
                        "Generated TensorZero config: %s", config_path,
                    )
                except Exception as e:
                    logger.warning(
                        "Could not generate TensorZero config, "
                        "using static fallback: %s", e,
                    )

            # Initialize LLM client (picks up generated TOML if available)
            self._llm = TensorZeroClient()
            await self._llm.start()

            # Initialize skills via SkillManager facade
            use_sandbox = self._get_setting("skills.sandbox.enabled", True)
            device_name = self._get_setting("device.name", "Strawberry Spoke")
            allow_unsafe = self._get_setting("skills.allow_unsafe_exec", False)
            custom_prompt = self._get_setting("llm.system_prompt", None)

            self._skill_mgr = SkillManager(
                skills_path=self._skills_path,
                use_sandbox=use_sandbox,
                device_name=device_name,
                allow_unsafe_exec=allow_unsafe,
                custom_system_prompt=custom_prompt or None,
                emit=self._emit,
                settings_manager=self._settings_manager,
            )
            await self._skill_mgr.load_and_emit(
                on_skill_loaded=on_skill_loaded,
                on_skill_failed=on_skill_failed,
            )

            # Initialize agent runners
            self._hub_runner = HubAgentRunner(
                get_hub_client=lambda: self._hub_manager.client,
                emit=self._emit,
            )
            self._local_runner = LocalAgentRunner(
                llm=self._llm,
                skills=self._skill_mgr.service,
                emit=self._emit,
            )

            self._started = True
            await self._emit(CoreReady())
            logger.info("SpokeCore started")

        except Exception as e:
            logger.error(f"SpokeCore start failed: {e}")
            await self._emit(CoreError(error=str(e), exception=e))
            raise

    async def stop(self) -> None:
        """Shutdown core services."""
        await self.disconnect_hub()

        if self._llm:
            await self._llm.close()
            self._llm = None

        if self._skill_mgr:
            await self._skill_mgr.shutdown()
            self._skill_mgr = None

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

    async def send_message(self, session_id: str, text: str) -> Optional[str]:
        """Send a user message and run the agent loop.

        Args:
            session_id: Session identifier to target.
            text: User message content.

        Returns:
            The final assistant response content, if any.
        """
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        if session.busy:
            await self._emit(CoreError(error="Session is busy"))
            return

        session.busy = True

        result_content: Optional[str] = None
        try:
            # Check for mode switch BEFORE adding the user message so
            # the LLM sees the context change first, then the question.
            current_online = self.is_online()
            current_mode = "online" if current_online else "offline"
            if (
                session.last_mode is not None
                and current_mode != session.last_mode
            ):
                from ..skills.prompt import build_mode_switch_message

                notice = build_mode_switch_message(current_mode)
                session.add_message("user", notice)
                logger.info(
                    "Injected mode-switch message (%s -> %s) into session %s",
                    session.last_mode,
                    current_mode,
                    session.id,
                )
            session.last_mode = current_mode

            # Add user message
            session.add_message("user", text)
            await self._emit(
                MessageAdded(session_id=session_id, role="user", content=text)
            )

            # Deterministic tool execution hooks (testing only).
            # When online, the Hub owns the agent loop, so skip local hooks.
            deterministic_hooks = self._get_setting(
                "testing.deterministic_tool_hooks", False
            )
            if deterministic_hooks and (not self.is_online()) and self._skill_mgr:
                hook_result = await self._skill_mgr.run_deterministic_hooks(
                    session, text
                )
                if hook_result is not None:
                    return hook_result

            # Run agent loop
            result_content = await self._agent_loop(session)
            return result_content

        except Exception as e:
            logger.error(f"Agent loop error: {e}")
            await self._emit(CoreError(error=str(e), exception=e))
        finally:
            session.busy = False
        return result_content

    async def _agent_loop(
        self, session: ChatSession, max_iterations: int = 5
    ) -> Optional[str]:
        """Run the agent loop with tool execution.

        When online (connected to Hub), routes chat through Hub with
        enable_tools=True so the Hub runs the agent loop and executes
        skills on registered devices.

        When offline, runs the agent loop locally using TensorZeroClient.

        Delegates to HubAgentRunner or LocalAgentRunner based on
        connection state.  Mode-switch messages are injected earlier
        in :meth:`send_message` so the LLM sees the context change
        before the user's question.
        """
        if not self._skill_mgr:
            await self._emit(CoreError(error="Core not started"))
            return None

        # Route based on online/offline mode (delegate to agent runners)
        if self.is_online() and self._hub_runner:
            return await self._hub_runner.run(session, max_iterations)

        if self._local_runner:
            return await self._local_runner.run(session, max_iterations)

        await self._emit(CoreError(error="No agent runner available"))
        return None

    def get_skill_summaries(self) -> List[Dict[str, Any]]:
        """Get plain-dict summaries of all loaded skills.

        Returns:
            List of dicts with keys: name, method_count, enabled, source, methods.
        """
        return self._skill_mgr.get_summaries() if self._skill_mgr else []

    def get_skill_load_failures(self) -> List[Dict[str, str]]:
        """Get plain-dict list of skills that failed to load.

        Returns:
            List of dicts with keys: source, error.
        """
        return self._skill_mgr.get_load_failures() if self._skill_mgr else []

    async def set_skill_enabled(self, name: str, enabled: bool) -> bool:
        """Enable or disable a skill and emit a status change event.

        Args:
            name: Skill class name.
            enabled: True to enable, False to disable.

        Returns:
            True if the skill was found and status changed.
        """
        if not self._skill_mgr:
            return False
        return await self._skill_mgr.set_enabled(name, enabled)

    def get_system_prompt(self) -> str:
        """Get the current system prompt."""
        if self._skill_mgr:
            return self._skill_mgr.get_system_prompt()
        return "You are a helpful assistant."

    def is_online(self) -> bool:
        """Check if connected to Hub."""
        return self._hub_manager.is_connected

    @property
    def hub_client(self) -> Optional[HubClient]:
        """Get the hub client if connected."""
        return self._hub_manager.client

    async def connect_hub(self) -> bool:
        """Connect to the Hub using settings.

        Returns:
            True if connection succeeded, False otherwise.
        """
        return await self._hub_manager.connect(
            skill_service=self._skill_mgr.service if self._skill_mgr else None
        )

    async def disconnect_hub(self) -> None:
        """Disconnect from the Hub."""
        await self._hub_manager.disconnect()

    def get_model_info(self) -> str:
        """Get current model name."""
        return self._settings_manager.get(
            "tensorzero", "ollama.model", "llama3.2:3b",
        )

    # Event system (delegates to EventBus)
    async def _emit(self, event: CoreEvent) -> None:
        """Emit an event to all subscribers."""
        await self._event_bus.emit(event)

    def subscribe(self, handler: Callable[[CoreEvent], Any]) -> Subscription:
        """Subscribe to events with a callback handler."""
        return self._event_bus.subscribe(handler)

    async def events(self) -> AsyncIterator[CoreEvent]:
        """Async iterator for events."""
        async for event in self._event_bus.events():
            yield event

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
