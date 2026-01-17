"""SpokeCore - single entrypoint for all UIs."""

import asyncio
import logging
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from ..config import get_settings
from ..llm.tensorzero_client import TensorZeroClient
from ..models import ChatMessage
from ..skills.service import SkillService
from .events import (
    CoreError,
    CoreEvent,
    CoreReady,
    MessageAdded,
    ToolCallResult,
    ToolCallStarted,
)
from .session import ChatSession

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
        self._settings = get_settings()
        self._llm: Optional[TensorZeroClient] = None
        self._skills: Optional[SkillService] = None
        self._sessions: Dict[str, ChatSession] = {}
        self._subscribers: List[asyncio.Queue] = []
        self._started = False

        # Paths from settings
        skills_path = Path(self._settings.skills.path)
        if not skills_path.is_absolute():
            # Relative to ai-pc-spoke root
            skills_path = Path(__file__).parent.parent.parent.parent / skills_path

        self._skills_path = skills_path

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
        """Run the agent loop with tool execution."""
        if not self._llm or not self._skills:
            await self._emit(CoreError(error="Core not started"))
            return

        system_prompt = self._skills.get_system_prompt()

        for iteration in range(max_iterations):
            # Build messages for LLM
            messages = [ChatMessage(role="system", content=system_prompt)]
            messages.extend(session.messages)

            # Get LLM response
            response = await self._llm.chat(messages)

            # Check for tool calls
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

    def get_system_prompt(self) -> str:
        """Get the current system prompt."""
        if self._skills:
            return self._skills.get_system_prompt()
        return "You are a helpful assistant."

    def is_online(self) -> bool:
        """Check if connected to Hub."""
        # TODO: Implement Hub connection check
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
