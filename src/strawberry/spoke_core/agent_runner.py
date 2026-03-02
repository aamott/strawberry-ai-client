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

from ..llm.tensorzero_client import _build_chat_response, _parse_response_content

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
    """Executes the agent loop via the central Hub.

    Passes the conversation to the Hub, which routes to a provider,
    executes tools by calling Spoke endpoints, and returns the final
    result in a stream.
    """

    def __init__(
        self,
        get_hub_client: Callable[[], Optional["HubClient"]],
        emit: Callable[[CoreEvent], Any],
        get_tool_mode: Callable[[], str],
    ) -> None:
        """Initialize Hub runner.

        Args:
            get_hub_client: Callable returning the active HubClient
            emit: Async callback to push UI events
            get_tool_mode: Callable returning the requested tool mode
        """
        self._get_hub_client = get_hub_client
        self._emit = emit
        self._get_tool_mode = get_tool_mode

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

        if event_type == "injected_message":
            role = str(event.get("role") or "user")
            content = str(event.get("content") or "")
            if content:
                # We do not append it to `session.messages` here because the Hub maintains
                # the single source of truth for the conversation history. However, we
                # emit the event so the CLI can display it to the user.
                await self._emit(
                    MessageAdded(
                        session_id=session.id,
                        role=role,
                        content=content,
                    )
                )
            return False, None

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

            tool_mode = self._get_tool_mode()
            stream = hub_client.chat_stream(
                messages=messages,
                enable_tools=True,
                tool_mode=tool_mode,
            )
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
    ) -> None:
        """Initialize LocalAgentRunner.

        Args:
            llm: TensorZero client for LLM calls.
            skills: SkillService for tool execution.
            emit: Async callback to emit CoreEvent instances.
        """
        self._llm = llm
        self._skills = skills
        self._emit = emit
        # Cache tool_mode so guidance messages match the active mode.
        self._tool_mode: str = getattr(skills, "tool_mode", "python_exec")

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

    async def run(  # noqa: C901
        self,
        session: "ChatSession",
        max_iterations: int = 5,
    ) -> Optional[str]:
        """Run agent loop locally (for local mode)."""
        function_name = self._select_function_name()

        # Build system prompt (mode switching is handled at the session
        # level in SpokeCore._agent_loop via conversation messages).
        system_prompt = self._skills.get_system_prompt()

        seen_tool_calls: set[str] = set()

        final_content: Optional[str] = None

        # Build ephemeral tz_messages for the LLM context.
        # We start with the actual session messages.
        tz_messages = self._llm._build_tz_messages(
            [msg for msg in session.messages if msg.role != "system"]
        )

        for iteration in range(max_iterations):
            inference_input = {"messages": tz_messages}
            if system_prompt:
                inference_input["system"] = system_prompt

            gateway = await self._llm._get_gateway()
            raw_response = await gateway.inference(
                function_name=function_name,
                input=inference_input,
            )

            content, tool_calls = _parse_response_content(
                raw_response, label="[LocalAgentRunner] "
            )
            response = _build_chat_response(raw_response, content, tool_calls)

            # Check for native tool calls first
            if response.tool_calls:
                if response.content:
                    await self._emit_assistant_message(session, response.content)

                # 1. Append the assistant's request with the raw tool_calls
                tz_messages.append(
                    {"role": "assistant", "content": getattr(raw_response, "content", [])}
                )

                # 2. Handle the tool calls, returning properly formatted result blocks
                should_abort, tool_results_content = await self._handle_tool_calls(
                    session, response.tool_calls, seen_tool_calls
                )

                # 3. Append the execution results to the ephemeral context
                if tool_results_content:
                    tz_messages.append({"role": "user", "content": tool_results_content})

                if should_abort:
                    return None
                continue

            # Check for legacy code blocks (models without native tool calls)
            legacy_code_blocks = self._extract_legacy_code_blocks(response.content or "")
            if legacy_code_blocks:
                if response.content:
                    await self._emit_assistant_message(session, response.content)

                tz_messages.append({"role": "assistant", "content": response.content})

                tool_results_content = await self._handle_legacy_code_blocks(
                    session, legacy_code_blocks, seen_tool_calls
                )

                if tool_results_content:
                    tz_messages.append({"role": "user", "content": tool_results_content})
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
        """Select TensorZero function for local mode.

        The generated TOML always defines ``chat_local`` with the correct
        fallback chain (cloud providers + Ollama, no Hub). TensorZero
        handles provider failures and fallback internally, so we no
        longer need to probe Ollama or check for API keys here.
        """
        return "chat_local"

    async def _handle_tool_calls(
        self,
        session: "ChatSession",
        tool_calls: List[Any],
        seen_tool_calls: set[str],
    ) -> tuple[bool, list[dict[str, Any]]]:
        """Handle native tool calls from LLM response.

        Args:
            session: Chat session.
            tool_calls: List of ToolCall objects from LLM.
            seen_tool_calls: Set of seen tool call signatures (for dedup).

        Returns:
            (should_abort, list_of_tool_result_blocks_for_ephemeral_context)
        """
        tool_results_content: list[dict[str, Any]] = []
        is_native = self._tool_mode == "native"

        last_tcid = str(tool_calls[-1].id) if tool_calls else ""

        for tool_call in tool_calls:
            tool_key = json.dumps(
                {
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                },
                sort_keys=True,
            )
            is_duplicate = tool_key in seen_tool_calls
            if is_duplicate:
                logger.warning(
                    "Duplicate tool call detected: %s — executing anyway",
                    tool_call.name,
                )
            seen_tool_calls.add(tool_key)

            await self._emit(
                ToolCallStarted(
                    session_id=session.id,
                    tool_name=tool_call.name,
                    arguments=tool_call.arguments,
                )
            )

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

            tool_msg, guidance_str = self._format_tool_result_message(
                tool_call.name,
                success,
                result_text,
            )
            if is_duplicate:
                dup_str = (
                    "NOTICE: This is a duplicate call — you already made "
                    "this exact call earlier in this conversation. Unless you "
                    "specifically need to repeat it, respond to the user now "
                    "instead of calling tools again."
                )
                tool_msg += f"\n\n[{dup_str}]"
                guidance_str = (
                    dup_str if not guidance_str else f"{guidance_str} | {dup_str}"
                )

            # Emit for UI visibility, but do NOT append to session.messages
            # to preserve standard chat log structure without complex JSON.
            await self._emit(
                MessageAdded(
                    session_id=session.id,
                    role="user",
                    content=tool_msg,
                )
            )

            # Format block for TensorZero
            payload = {"result": result_text}

            # Use strict JSON injection on the very last block in this batch
            if is_native and guidance_str and str(tool_call.id) == last_tcid:
                payload["_system_guidance"] = guidance_str

            tool_results_content.append(
                {
                    "type": "tool_result",
                    "id": str(tool_call.id),
                    "name": tool_call.name,
                    "result": json.dumps(payload, default=str),
                }
            )

        return False, tool_results_content

    async def _handle_legacy_code_blocks(
        self,
        session: "ChatSession",
        code_blocks: List[str],
        seen_tool_calls: set[str],
    ) -> str:
        """Handle legacy code blocks extracted from LLM response.

        Args:
            session: Chat session.
            code_blocks: List of code strings to execute.
            seen_tool_calls: Set of seen tool call signatures (for dedup).

        Returns:
            String representing the text output to append back to the LLM.
        """
        combined_outputs = []
        for code in code_blocks:
            tool_key = json.dumps(
                {
                    "name": "python_exec",
                    "arguments": {"code": code},
                },
                sort_keys=True,
            )
            is_duplicate = tool_key in seen_tool_calls
            if is_duplicate:
                logger.warning(
                    "Duplicate tool call detected: python_exec — executing anyway"
                )
            seen_tool_calls.add(tool_key)

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

            tool_msg, guidance = self._format_tool_result_message(
                "python_exec",
                success,
                result_text,
            )
            if is_duplicate:
                tool_msg += (
                    "\n\n[NOTICE: This is a duplicate call — you already made "
                    "this exact call earlier in this conversation. Unless you "
                    "specifically need to repeat it, respond to the user now "
                    "instead of calling tools again.]"
                )

            await self._emit(
                MessageAdded(
                    session_id=session.id,
                    role="user",
                    content=tool_msg,
                )
            )
            combined_outputs.append(tool_msg)

        return "\n\n".join(combined_outputs)

    def _format_tool_result_message(
        self,
        tool_name: str,
        success: bool,
        result_text: str,
    ) -> tuple[str, str]:
        """Build the session message injected after a tool call.

        Args:
            tool_name: Name of the tool that was called.
            success: Whether the tool succeeded.
            result_text: Output or error text from the tool.

        Returns:
            (formatted_ui_string, guidance_string_for_llm)
        """
        if not success:
            err_guide = "Fix the error and try again with corrected arguments."
            return (
                f"[Tool Result: {tool_name} — ERROR]\n{result_text}\n\n{err_guide}"
            ), err_guide

        is_native = self._tool_mode == "native"
        exec_hint = ""

        if tool_name == "search_skills":
            if is_native:
                exec_hint = (
                    "Now call the appropriate skill tool directly by name "
                    "(e.g. SkillClass__method_name). "
                    "search_skills only finds skills — it does NOT run them."
                )
            else:
                exec_hint = (
                    "Now call python_exec to execute the skill. "
                    "search_skills only finds skills — it does NOT run them."
                )
            return (
                f"[Tool Result: search_skills — SUCCESS]\n{result_text}\n\n{exec_hint}"
            ), exec_hint

        if tool_name == "describe_function":
            if is_native:
                exec_hint = "Now call the skill tool directly by name."
            else:
                exec_hint = "Now call python_exec to execute the skill."
            return (
                f"[Tool Result: describe_function — SUCCESS]\n"
                f"{result_text}\n\n"
                f"{exec_hint}"
            ), exec_hint

        # python_exec, native skill tool, or any other tool
        exec_hint = (
            "Give the user a short, natural-language answer "
            "confirming what was done. Do NOT repeat this tool call."
        )
        return (
            f"[Tool Result: {tool_name} — SUCCESS]\n{result_text}\n\n{exec_hint}"
        ), exec_hint

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
