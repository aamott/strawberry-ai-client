"""TensorZero embedded gateway client with Hub/Ollama fallback.

Uses TensorZero's embedded gateway (in-process) instead of a separate HTTP server.
This eliminates the need for a separate gateway process while still providing
automatic fallback between Hub and local Ollama providers.
"""

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
__all__ = ["ChatMessage", "ChatResponse", "ToolCall", "TensorZeroClient", "TensorZeroError"]


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

        logger.info(f"Initializing TensorZero embedded gateway from {self.config_path}")
        self._gateway = await AsyncTensorZeroGateway.build_embedded(
            config_file=self.config_path,
            async_setup=True,
        )
        self._initialized = True
        return self._gateway

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

    async def chat(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> ChatResponse:
        """Send chat request to TensorZero embedded gateway.

        Args:
            messages: List of chat messages
            system_prompt: Optional system prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response

        Returns:
            ChatResponse with content and metadata about which variant was used
        """
        gateway = await self._get_gateway()

        # Build input for TensorZero
        tz_messages = []

        # Add conversation messages (system role not allowed in messages)
        for msg in messages:
            if msg.role == "system":
                continue
            tz_messages.append({"role": msg.role, "content": msg.content})

        try:
            # Call embedded gateway inference
            # System prompt passed via input.system (per TensorZero docs)
            tz_input: dict = {"messages": tz_messages}
            if system_prompt:
                tz_input["system"] = system_prompt

            inference_params = {
                "function_name": "chat",
                "input": tz_input,
            }

            response = await gateway.inference(**inference_params)

            # Log full response structure for debugging
            logger.debug(f"Full response type: {type(response)}")
            logger.debug(f"Response attributes: {dir(response)}")
            if hasattr(response, "__dict__"):
                logger.debug(f"Response __dict__: {response.__dict__}")

            # Extract response content and tool calls
            content = ""
            tool_calls: List[ToolCall] = []

            # Handle TensorZero response object
            if hasattr(response, "content"):
                logger.debug(f"Response content type: {type(response.content)}")
                logger.debug(f"Response content length: {len(response.content)}")

                for i, block in enumerate(response.content):
                    logger.debug(
                        f"Block {i}: type={type(block).__name__}, "
                        f"attrs={[a for a in dir(block) if not a.startswith('_')]}"
                    )

                    if hasattr(block, "text"):
                        content += block.text
                    elif hasattr(block, "type") and block.type == "tool_call":
                        # TensorZero may have name/arguments OR raw_name/raw_arguments
                        # Use parsed versions if available, fall back to raw
                        name = getattr(block, "name", None)
                        if not name:
                            name = getattr(block, "raw_name", None)

                        arguments = getattr(block, "arguments", None)
                        if not isinstance(arguments, dict):
                            # Try parsing raw_arguments JSON string
                            raw_args_str = getattr(block, "raw_arguments", None)
                            if raw_args_str and isinstance(raw_args_str, str):
                                try:
                                    import json
                                    arguments = json.loads(raw_args_str)
                                except json.JSONDecodeError:
                                    arguments = {}
                            else:
                                arguments = {}

                        logger.debug(
                            f"Tool call block: name={name!r}, arguments={arguments!r}"
                        )

                        if not name:
                            logger.warning(
                                f"Tool call has empty name! block={block}, "
                                f"block.__dict__={getattr(block, '__dict__', {})}"
                            )

                        tool_calls.append(
                            ToolCall(
                                id=str(getattr(block, "id", "") or ""),
                                name=str(name) if name else "unknown_tool",
                                arguments=arguments,
                            )
                        )

            # Extract variant information
            variant_used = getattr(response, "variant_name", "unknown")
            is_fallback = variant_used == "local_ollama"
            inference_id = getattr(response, "inference_id", "")

            # Build raw dict for debugging
            raw = {}
            if hasattr(response, "__dict__"):
                raw = {k: str(v) for k, v in response.__dict__.items()}

            return ChatResponse(
                content=content,
                model=getattr(response, "model", "unknown"),
                variant=variant_used,
                is_fallback=is_fallback,
                inference_id=str(inference_id) if inference_id else "",
                tool_calls=tool_calls,
                raw=raw,
            )

        except Exception as e:
            logger.error(f"TensorZero inference failed: {e}")
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
            messages: Previous chat messages including assistant's tool call response
            tool_results: List of tool results, each with {"id": str, "name": str, "result": str}
            system_prompt: Optional system prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response

        Returns:
            ChatResponse with content and/or more tool calls
        """
        gateway = await self._get_gateway()

        # Build messages for TensorZero
        tz_messages = []

        # Add conversation messages (system role not allowed in messages)
        for msg in messages:
            if msg.role == "system":
                continue
            tz_messages.append({"role": msg.role, "content": msg.content})

        # Add tool results as user message with tool_result content blocks
        tool_result_content = []
        for result in tool_results:
            tool_result_content.append({
                "type": "tool_result",
                "id": result.get("id", ""),
                "name": result.get("name", ""),
                "result": result.get("result", ""),
            })

        tz_messages.append({"role": "user", "content": tool_result_content})

        try:
            # System prompt passed via input.system (per TensorZero docs)
            inference_input: Dict[str, Any] = {"messages": tz_messages}
            if system_prompt:
                inference_input["system"] = system_prompt

            response = await gateway.inference(
                function_name="chat",
                input=inference_input,
            )

            # Extract response content and tool calls
            content = ""
            tool_calls: List[ToolCall] = []

            if hasattr(response, "content"):
                logger.debug(f"[chat_with_tool_results] content type: {type(response.content)}")
                logger.debug(f"[chat_with_tool_results] content len: {len(response.content)}")

                for i, block in enumerate(response.content):
                    logger.debug(
                        f"[chat_with_tool_results] Block {i}: type={type(block).__name__}, "
                        f"attrs={[a for a in dir(block) if not a.startswith('_')]}"
                    )

                    if hasattr(block, "text"):
                        content += block.text
                    elif hasattr(block, "type") and block.type == "tool_call":
                        # TensorZero may have name/arguments OR raw_name/raw_arguments
                        name = getattr(block, "name", None)
                        if not name:
                            name = getattr(block, "raw_name", None)

                        arguments = getattr(block, "arguments", None)
                        if not isinstance(arguments, dict):
                            raw_args_str = getattr(block, "raw_arguments", None)
                            if raw_args_str and isinstance(raw_args_str, str):
                                try:
                                    import json
                                    arguments = json.loads(raw_args_str)
                                except json.JSONDecodeError:
                                    arguments = {}
                            else:
                                arguments = {}

                        logger.debug(
                            f"[chat_with_tool_results] Tool call: name={name!r}, "
                            f"arguments={arguments!r}"
                        )

                        if not name:
                            logger.warning(
                                f"Tool call has empty name! block={block}, "
                                f"block.__dict__={getattr(block, '__dict__', {})}"
                            )

                        tool_calls.append(
                            ToolCall(
                                id=str(getattr(block, "id", "") or ""),
                                name=str(name) if name else "unknown_tool",
                                arguments=arguments,
                            )
                        )

            variant_used = getattr(response, "variant_name", "unknown")
            is_fallback = variant_used == "local_ollama"
            inference_id = getattr(response, "inference_id", "")

            raw = {}
            if hasattr(response, "__dict__"):
                raw = {k: str(v) for k, v in response.__dict__.items()}

            return ChatResponse(
                content=content,
                model=getattr(response, "model", "unknown"),
                variant=variant_used,
                is_fallback=is_fallback,
                inference_id=str(inference_id) if inference_id else "",
                tool_calls=tool_calls,
                raw=raw,
            )

        except Exception as e:
            logger.error(f"TensorZero inference failed: {e}")
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
