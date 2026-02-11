"""AgentRunner - extracted agent loop logic for SpokeCore.

Provides two implementations:
- HubAgentRunner: forwards messages to Hub, streams tool call events
- LocalAgentRunner: runs tool loop locally with TensorZero
"""

import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, List, Optional

from ..hub import HubError
from .events import (
    CoreError,
    CoreEvent,
    MessageAdded,
    StreamingDelta,
    ToolCallResult,
    ToolCallStarted,
)

if TYPE_CHECKING:
    from ..hub import HubClient
    from ..llm.tensorzero_client import TensorZeroClient
    from ..skills.service import SkillService
    from .session import ChatSession

logger = logging.getLogger(__name__)


class AgentRunner(ABC):
    """Abstract base for agent loop implementations."""

    @abstractmethod
    async def run(
        self,
        session: "ChatSession",
        max_iterations: int = 5,
    ) -> Optional[str]:
        """Run the agent loop.

        Args:
            session: The chat session to process.
            max_iterations: Max tool call iterations (local mode only).

        Returns:
            Final assistant response content, or None on error.
        """
        pass


class HubAgentRunner(AgentRunner):
    """Agent runner that forwards messages to Hub for processing.

    The Hub owns:
    - System prompt construction
    - Tool call execution on registered devices

    The Spoke only receives events and final responses.
    """

    def __init__(
        self,
        get_hub_client: Callable[[], Optional["HubClient"]],
        emit: Callable[[CoreEvent], Any],
    ) -> None:
        """Initialize HubAgentRunner.

        Args:
            get_hub_client: Callback to get the current HubClient (or None).
            emit: Async callback to emit CoreEvent instances.
        """
        self._get_hub_client = get_hub_client
        self._emit = emit

    async def _dispatch_stream_event(
        self,
        event_type: str,
        event: dict,
        session: "ChatSession",
    ) -> tuple[bool, Optional[str]]:
        """Dispatch a single Hub SSE event.

        Returns:
            (should_break, final_content_if_any)
        """
        if event_type == "tool_call_started":
            arguments = event.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {}
            await self._emit(
                ToolCallStarted(
                    session_id=session.id,
                    tool_name=str(event.get("tool_name") or ""),
                    arguments=arguments,
                )
            )
            return False, None

        if event_type == "tool_call_result":
            success = bool(event.get("success"))
            result = event.get("result")
            error = event.get("error")
            await self._emit(
                ToolCallResult(
                    session_id=session.id,
                    tool_name=str(event.get("tool_name") or ""),
                    success=success,
                    result=str(result) if (success and result is not None) else None,
                    error=str(error) if ((not success) and error is not None) else None,
                )
            )
            return False, None

        if event_type == "content_delta":
            delta = str(event.get("delta") or "")
            if delta:
                await self._emit(StreamingDelta(session_id=session.id, delta=delta))
            return False, None

        if event_type == "assistant_message":
            return False, str(event.get("content") or "")

        if event_type == "error":
            error_msg = str(event.get("error") or "Hub stream error")
            await self._emit(CoreError(error=error_msg))
            return True, None  # signal caller to return None

        return False, None

    async def run(
        self,
        session: "ChatSession",
        max_iterations: int = 5,
    ) -> Optional[str]:
        """Run agent loop via Hub (Hub executes tools on registered devices)."""
        from ..models import ChatMessage

        hub_client = self._get_hub_client()
        if not hub_client:
            await self._emit(CoreError(error="Hub client not available"))
            return None

        # Build messages for Hub (exclude system messages)
        messages: list[ChatMessage] = [
            ChatMessage(role=msg.role, content=msg.content)
            for msg in session.messages
            if msg.role != "system"
        ]

        try:
            final_content: Optional[str] = None

            stream = hub_client.chat_stream(messages=messages, enable_tools=True)
            try:
                while True:
                    event = await stream.__anext__()
                    event_type = str(event.get("type") or "")

                    if event_type == "done":
                        await asyncio.shield(stream.aclose())
                        break

                    should_abort, content = await self._dispatch_stream_event(
                        event_type,
                        event,
                        session,
                    )
                    if should_abort:
                        return None
                    if content is not None:
                        final_content = content

            except StopAsyncIteration:
                pass
            finally:
                await asyncio.shield(stream.aclose())

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
            return None

        return final_content


class LocalAgentRunner(AgentRunner):
    """Agent runner that executes tools locally with TensorZero.

    Handles:
    - Native tool calls from LLM
    - Legacy code block extraction (for models without native tool support)
    - Duplicate tool call detection
    """

    def __init__(
        self,
        llm: "TensorZeroClient",
        skills: "SkillService",
        emit: Callable[[CoreEvent], Any],
        get_mode_notice: Callable[[], Optional[str]],
        clear_mode_notice: Callable[[], None],
    ) -> None:
        """Initialize LocalAgentRunner.

        Args:
            llm: TensorZero client for LLM calls.
            skills: SkillService for tool execution.
            emit: Async callback to emit CoreEvent instances.
            get_mode_notice: Callback to get pending mode notice (or None).
            clear_mode_notice: Callback to clear pending mode notice.
        """
        self._llm = llm
        self._skills = skills
        self._emit = emit
        self._get_mode_notice = get_mode_notice
        self._clear_mode_notice = clear_mode_notice

    async def _emit_assistant_message(
        self,
        session: "ChatSession",
        content: str,
    ) -> None:
        """Add an assistant message to the session and emit the event."""
        session.add_message("assistant", content)
        await self._emit(
            MessageAdded(
                session_id=session.id,
                role="assistant",
                content=content,
            )
        )

    async def run(
        self,
        session: "ChatSession",
        max_iterations: int = 5,
    ) -> Optional[str]:
        """Run agent loop locally (for offline mode)."""
        function_name = self._select_function_name()

        # Build system prompt with mode notice
        mode_notice = self._get_mode_notice()
        system_prompt = self._skills.get_system_prompt(mode_notice=mode_notice)
        self._clear_mode_notice()

        seen_tool_calls: set[str] = set()

        final_content: Optional[str] = None
        for iteration in range(max_iterations):
            # Build messages for LLM (skip system messages)
            messages = [msg for msg in session.messages if msg.role != "system"]

            # Get LLM response with system prompt passed explicitly
            response = await self._llm.chat(
                messages,
                system_prompt=system_prompt,
                function_name=function_name,
            )

            # Check for native tool calls first
            if response.tool_calls:
                if response.content:
                    await self._emit_assistant_message(session, response.content)

                should_abort = await self._handle_tool_calls(
                    session, response.tool_calls, seen_tool_calls
                )
                if should_abort:
                    return None
                continue

            # Check for legacy code blocks (models without native tool calls)
            legacy_code_blocks = self._extract_legacy_code_blocks(response.content or "")
            if legacy_code_blocks:
                if response.content:
                    await self._emit_assistant_message(session, response.content)
                await self._handle_legacy_code_blocks(session, legacy_code_blocks)
                continue

            # No tool calls - final response
            if response.content:
                await self._emit_assistant_message(session, response.content)
                final_content = response.content
            break

        if (
            iteration + 1 >= max_iterations
            and session.messages
            and session.messages[-1].role != "assistant"
        ):
            error = "Agent loop hit max iterations without producing a final response."
            await self._emit(CoreError(error=error))
            await self._emit_assistant_message(session, error)
            final_content = error

        return final_content

    def _select_function_name(self) -> str:
        """Select TensorZero function based on available providers."""
        import os

        import httpx

        try:
            ollama_ok = False
            try:
                resp = httpx.get("http://localhost:11434/api/tags", timeout=0.5)
                ollama_ok = resp.status_code == 200
            except Exception:
                ollama_ok = False

            if not ollama_ok and os.environ.get("GOOGLE_AI_STUDIO_API_KEY"):
                return "chat_local_gemini"
        except Exception:
            pass

        return "chat_local"

    async def _handle_tool_calls(
        self,
        session: "ChatSession",
        tool_calls: List[Any],
        seen_tool_calls: set[str],
    ) -> bool:
        """Handle native tool calls from LLM response.

        Args:
            session: Chat session.
            tool_calls: List of ToolCall objects from LLM.
            seen_tool_calls: Set of seen tool call signatures (for dedup).

        Returns:
            True if loop should abort (duplicate detected), False to continue.
        """
        for tool_call in tool_calls:
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
                return True
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

        return False

    async def _handle_legacy_code_blocks(
        self,
        session: "ChatSession",
        code_blocks: List[str],
    ) -> None:
        """Handle legacy code blocks extracted from LLM response.

        Args:
            session: Chat session.
            code_blocks: List of code strings to execute.
        """
        for code in code_blocks:
            await self._emit(
                ToolCallStarted(
                    session_id=session.id,
                    tool_name="python_exec",
                    arguments={"code": code},
                )
            )

            # Execute via python_exec tool
            result = await self._skills.execute_tool_async("python_exec", {"code": code})

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
        code_blocks = []

        # Extract fenced code blocks
        # Match ```tool_code, ```python, or just ``` with device calls
        # Allow optional newline after opening fence
        pattern = r"```(?:tool_code|python|py)?\s*\n?(.*?)```"
        matches = re.findall(pattern, content, re.DOTALL | re.IGNORECASE)

        for match in matches:
            code = match.strip()
            # Only include if it looks like a skill call
            if any(
                prefix in code
                for prefix in [
                    "device.",
                    "devices.",
                    "device_manager.",
                    "print(device.",
                    "print(devices.",
                ]
            ):
                code_blocks.append(code)

        # Also check for bare device calls not in code blocks
        if not code_blocks:
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith(
                    (
                        "device.",
                        "devices.",
                        "device_manager.",
                        "print(device.",
                        "print(devices.",
                        "print(device_manager.",
                    )
                ):
                    code_blocks.append(stripped)

        return code_blocks
