#!/usr/bin/env python3
"""CLI debugging script for TensorZero tool calls.

This script sends a prompt to TensorZero, receives tool calls, executes them,
and logs everything in detail. Use this to debug tool call parsing issues
without needing the GUI.

Usage:
    python scripts/debug_tool_calls.py [prompt]

Example:
    python scripts/debug_tool_calls.py "What day of the week is it?"
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv()

# Set up detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("debug_tool_calls.log", mode="w", encoding="utf-8"),
    ],
)
logger = logging.getLogger("debug_tool_calls")

# Reduce noise from other loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


async def run_agent_loop(prompt: str, max_iterations: int = 10) -> None:
    """Run a single agent loop with detailed logging."""
    from strawberry.llm.tensorzero_client import TensorZeroClient
    from strawberry.skills.service import SkillService

    skills_path = Path(__file__).parent.parent / "skills"
    logger.info(f"Skills path: {skills_path}")

    # Initialize skill service (no sandbox for debugging)
    skill_service = SkillService(skills_path=skills_path, use_sandbox=False)
    skill_service.load_skills()
    logger.info(f"Loaded {len(skill_service._loader.get_all_skills())} skills")

    # Build system prompt
    system_prompt = skill_service.get_system_prompt()
    logger.debug(f"System prompt:\n{system_prompt[:500]}...")

    # Initialize TensorZero client
    client = TensorZeroClient()
    logger.info("TensorZero client initialized")

    # Build initial messages
    messages = [{"role": "user", "content": prompt}]
    logger.info(f"User prompt: {prompt}")

    for iteration in range(max_iterations):
        logger.info(f"\n{'='*60}")
        logger.info(f"ITERATION {iteration + 1}/{max_iterations}")
        logger.info(f"{'='*60}")

        try:
            # Call TensorZero
            from strawberry.llm.tensorzero_client import ChatMessage

            chat_messages = [ChatMessage(role=m["role"], content=m["content"]) for m in messages]
            response = await client.chat(chat_messages, system_prompt=system_prompt)

            content_preview = response.content[:200] if response.content else "(empty)"
            logger.info(f"Response content: {content_preview}...")
            logger.info(f"Variant used: {response.variant}")
            logger.info(f"Tool calls count: {len(response.tool_calls)}")

            # Log raw response for debugging
            logger.debug(f"Raw response dict: {response.raw}")

            if not response.tool_calls:
                logger.info("No tool calls - ending loop")
                print(f"\n{'='*60}")
                print("FINAL RESPONSE:")
                print(f"{'='*60}")
                print(response.content)
                return

            # Process each tool call
            tool_results = []
            for i, tool_call in enumerate(response.tool_calls):
                logger.info(f"\n--- Tool Call {i + 1} ---")
                logger.info(f"  ID: {tool_call.id}")
                logger.info(f"  Name: {tool_call.name!r}")
                logger.info(f"  Arguments: {tool_call.arguments}")

                # Check for malformed tool call
                if not tool_call.name or tool_call.name == "unknown_tool":
                    logger.error(f"MALFORMED TOOL CALL: name={tool_call.name!r}")
                    logger.error(f"Full tool_call object: {tool_call}")
                    result = {
                        "error": (
                            "Malformed tool call (missing tool name). "
                            "Please call a valid tool."
                        )
                    }
                else:
                    # Execute the tool
                    logger.info(f"Executing tool: {tool_call.name}")
                    result = await skill_service.execute_tool_async(
                        tool_call.name,
                        tool_call.arguments or {},
                    )
                    logger.info(f"Tool result: {result}")

                    # If unknown tool, provide guidance
                    if "Unknown tool" in result.get("error", ""):
                        result["error"] += (
                            " Use python_exec to call skills. Example: "
                            "python_exec({\"code\": \"print(device.SkillName.method())\"})"
                        )

                tool_results.append({
                    "id": tool_call.id,
                    "name": tool_call.name or "unknown_tool",
                    "result": result.get("result", result.get("error", "")),
                })

            # Add assistant message and tool results to conversation
            messages.append({"role": "assistant", "content": response.content or ""})

            # Continue with tool results
            logger.info("\nCalling chat_with_tool_results...")
            response = await client.chat_with_tool_results(
                messages=chat_messages,
                tool_results=tool_results,
                system_prompt=system_prompt,
            )

            content_preview = response.content[:200] if response.content else "(empty)"
            logger.info(f"Response after tool results: {content_preview}...")
            logger.info(f"New tool calls: {len(response.tool_calls)}")

            # Update messages for next iteration
            messages.append({"role": "assistant", "content": response.content or ""})

            if not response.tool_calls:
                logger.info("No more tool calls - ending loop")
                print(f"\n{'='*60}")
                print("FINAL RESPONSE:")
                print(f"{'='*60}")
                print(response.content)
                return

        except Exception as e:
            logger.exception(f"Error in iteration {iteration + 1}: {e}")
            raise

    logger.warning("Max iterations reached")


def main() -> None:
    """Main entry point."""
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
    else:
        prompt = "What day of the week is it today?"

    print(f"Running with prompt: {prompt}")
    print("Logs will be written to: debug_tool_calls.log")
    print()

    asyncio.run(run_agent_loop(prompt))


if __name__ == "__main__":
    main()
