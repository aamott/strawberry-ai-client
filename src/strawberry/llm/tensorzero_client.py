"""TensorZero embedded gateway client with Hub/Ollama fallback.

Uses TensorZero's embedded gateway (in-process) instead of a separate HTTP server.
This eliminates the need for a separate gateway process while still providing
automatic fallback between Hub and local Ollama providers.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from tensorzero import AsyncTensorZeroGateway

from ..models import ChatMessage, ChatResponse, ToolCall

# Load .env file from project root before TensorZero initialization
_project_root = Path(__file__).parent.parent.parent.parent
load_dotenv(_project_root / ".env")

# TensorZero validates ALL providers at startup, even unused ones.
# Set dummy HUB_DEVICE_TOKEN if not configured so validation passes.
# The Hub will return 401, triggering fallback to Gemini/Ollama.
if not os.environ.get("HUB_DEVICE_TOKEN"):
    os.environ["HUB_DEVICE_TOKEN"] = os.environ.get("HUB_TOKEN", "not-configured")

logger = logging.getLogger(__name__)


# Re-export for backward compatibility
__all__ = [
    "ChatMessage",
    "ChatResponse",
    "ToolCall",
    "TensorZeroClient",
    "TensorZeroError",
]


class TensorZeroError(Exception):
    """Error from TensorZero gateway."""

    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


def get_config_path() -> str:
    """Get the path to tensorzero.toml config file.

    Returns:
        Absolute path to the config file.
    """
    # Check for override via environment variable
    config_path = os.getenv("TENSORZERO_CONFIG_PATH")
    if config_path:
        return config_path

    # Default: config/tensorzero.toml relative to project root
    # Project root is 4 levels up from this file (src/strawberry/llm/)
    llm_dir = Path(__file__).parent
    project_root = llm_dir.parent.parent.parent
    return str(project_root / "config" / "tensorzero.toml")


# ---------------------------------------------------------------------------
# Shared helpers for parsing TensorZero responses
# ---------------------------------------------------------------------------


def _parse_tool_call_block(block: Any) -> Optional[ToolCall]:
    """Parse a single TensorZero content block into a ToolCall, if applicable.

    TensorZero may populate ``name``/``arguments`` or only the raw
    ``raw_name``/``raw_arguments`` variants.  We try the parsed versions
    first and fall back to raw.

    Args:
        block: A single content block from the gateway response.

    Returns:
        A ToolCall if the block is a tool_call, else None.
    """
    if not (hasattr(block, "type") and block.type == "tool_call"):
        return None

    # Resolve name (parsed → raw fallback)
    name = getattr(block, "name", None) or getattr(block, "raw_name", None)

    # Resolve arguments (parsed dict → raw JSON string → empty dict)
    arguments = getattr(block, "arguments", None)
    if not isinstance(arguments, dict):
        raw_args_str = getattr(block, "raw_arguments", None)
        if raw_args_str and isinstance(raw_args_str, str):
            try:
                arguments = json.loads(raw_args_str)
            except json.JSONDecodeError:
                arguments = {}
        else:
            arguments = {}

    if not name:
        logger.warning(
            "Tool call has empty name! block=%s, block.__dict__=%s",
            block,
            getattr(block, "__dict__", {}),
        )

    return ToolCall(
        id=str(getattr(block, "id", "") or ""),
        name=str(name) if name else "unknown_tool",
        arguments=arguments,
    )


def _parse_response_content(
    response: Any,
    label: str = "",
) -> tuple[str, List[ToolCall]]:
    """Extract text and tool calls from a TensorZero response.

    Args:
        response: The raw gateway inference response.
        label: Optional log prefix for debug messages.

    Returns:
        Tuple of (content_text, tool_calls).
    """
    content = ""
    tool_calls: List[ToolCall] = []

    if not hasattr(response, "content"):
        return content, tool_calls

    blocks = response.content
    logger.debug("%sResponse content length: %d", label, len(blocks))

    for i, block in enumerate(blocks):
        logger.debug(
            "%sBlock %d: type=%s, attrs=%s",
            label,
            i,
            type(block).__name__,
            [a for a in dir(block) if not a.startswith("_")],
        )

        if hasattr(block, "text"):
            block_text = getattr(block, "text", "")
            if block_text:
                content += str(block_text)
            continue

        tc = _parse_tool_call_block(block)
        if tc:
            logger.debug(
                "%sTool call: name=%r, arguments=%r",
                label,
                tc.name,
                tc.arguments,
            )
            tool_calls.append(tc)

    return content, tool_calls


def _build_chat_response(
    response: Any,
    content: str,
    tool_calls: List[ToolCall],
) -> ChatResponse:
    """Assemble a ChatResponse from parsed content and gateway metadata.

    Args:
        response: The raw gateway inference response.
        content: Extracted text content.
        tool_calls: Extracted tool calls.

    Returns:
        A fully populated ChatResponse.
    """
    variant_used = getattr(response, "variant_name", "unknown")
    inference_id = getattr(response, "inference_id", "")

    # Build raw dict for debugging
    raw: Dict[str, str] = {}
    if hasattr(response, "__dict__"):
        raw = {k: str(v) for k, v in response.__dict__.items()}

    return ChatResponse(
        content=content,
        model=getattr(response, "model", "unknown"),
        variant=variant_used,
        is_fallback=(variant_used == "local_ollama"),
        inference_id=str(inference_id) if inference_id else "",
        tool_calls=tool_calls,
        raw=raw,
    )


class TensorZeroClient:
    """Client for TensorZero embedded gateway.

    Uses in-process TensorZero gateway (no separate HTTP server needed).
    TensorZero handles fallback between Hub and local Ollama automatically.
    """

    def __init__(
        self,
        config_path: Optional[str] = None,
    ):
        """Initialize TensorZero embedded gateway client.

        Args:
            config_path: Path to tensorzero.toml config file (optional)
        """
        self.config_path = config_path or get_config_path()
        self._gateway: Optional[AsyncTensorZeroGateway] = None
        self._initialized: bool = False

    async def _get_gateway(self) -> AsyncTensorZeroGateway:
        """Get or create the embedded gateway instance."""
        if self._gateway is not None and self._initialized:
            return self._gateway

        logger.info(
            "Initializing TensorZero embedded gateway from %s",
            self.config_path,
        )
        self._gateway = await AsyncTensorZeroGateway.build_embedded(
            config_file=self.config_path,
            async_setup=True,
        )
        self._initialized = True
        return self._gateway

    async def start(self) -> None:
        """Initialize the embedded gateway.

        This is a public API for explicitly starting the gateway. Typically
        called during application startup.
        """
        await self._get_gateway()

    async def close(self) -> None:
        """Close the embedded gateway."""
        if self._gateway is not None:
            try:
                await self._gateway.__aexit__(None, None, None)
            except Exception:
                pass
            self._gateway = None
            self._initialized = False

    async def __aenter__(self) -> "TensorZeroClient":
        await self._get_gateway()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def health(self) -> bool:
        """Check if TensorZero gateway is healthy (always True for embedded)."""
        try:
            await self._get_gateway()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Core inference methods
    # ------------------------------------------------------------------

    def _build_tz_messages(
        self,
        messages: List[ChatMessage],
    ) -> list[dict[str, Any]]:
        """Convert ChatMessages to TensorZero message format.

        Strips ``system`` role messages since TensorZero passes the system
        prompt separately via ``input.system``.
        """
        return [
            {"role": msg.role, "content": msg.content}
            for msg in messages
            if msg.role != "system"
        ]

    async def chat(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        function_name: str = "chat",
    ) -> ChatResponse:
        """Send chat request to TensorZero embedded gateway.

        Args:
            messages: List of chat messages.
            system_prompt: Optional system prompt.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in response.
            function_name: TensorZero function to invoke.

        Returns:
            ChatResponse with content and metadata about which variant was used.
        """
        gateway = await self._get_gateway()
        tz_messages = self._build_tz_messages(messages)

        try:
            tz_input: dict = {"messages": tz_messages}
            if system_prompt:
                tz_input["system"] = system_prompt

            response = await gateway.inference(
                function_name=function_name,
                input=tz_input,
            )

            content, tool_calls = _parse_response_content(response)
            return _build_chat_response(response, content, tool_calls)

        except Exception as e:
            logger.error("TensorZero inference failed: %s", e)
            raise TensorZeroError(f"Inference failed: {e}")

    async def chat_with_tool_results(
        self,
        messages: List[ChatMessage],
        tool_results: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> ChatResponse:
        """Continue chat after tool execution with tool results.

        Args:
            messages: Previous chat messages including the assistant's
                tool call response.
            tool_results: List of tool results, each with
                ``{"id": str, "name": str, "result": str}``.
            system_prompt: Optional system prompt.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in response.

        Returns:
            ChatResponse with content and/or more tool calls.
        """
        gateway = await self._get_gateway()
        tz_messages = self._build_tz_messages(messages)

        # Append tool results as a user message with tool_result blocks
        tool_result_content = [
            {
                "type": "tool_result",
                "id": r.get("id", ""),
                "name": r.get("name", ""),
                "result": r.get("result", ""),
            }
            for r in tool_results
        ]
        tz_messages.append({"role": "user", "content": tool_result_content})

        try:
            inference_input: Dict[str, Any] = {"messages": tz_messages}
            if system_prompt:
                inference_input["system"] = system_prompt

            response = await gateway.inference(
                function_name="chat",
                input=inference_input,
            )

            content, tool_calls = _parse_response_content(
                response,
                label="[chat_with_tool_results] ",
            )
            return _build_chat_response(response, content, tool_calls)

        except Exception as e:
            logger.error("TensorZero inference failed: %s", e)
            raise TensorZeroError(f"Inference failed: {e}")

    async def chat_simple(self, user_message: str) -> str:
        """Simple chat - send a message and get a reply.

        Args:
            user_message: The user's message

        Returns:
            The assistant's reply text
        """
        response = await self.chat([ChatMessage(role="user", content=user_message)])
        return response.content
