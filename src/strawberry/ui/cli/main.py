#!/usr/bin/env python3
"""CLI UI main entrypoint."""

import asyncio
import os

from ...core import (
    CoreError,
    CoreEvent,
    CoreReady,
    MessageAdded,
    SpokeCore,
    ToolCallResult,
    ToolCallStarted,
)
from . import renderer as r


async def run_cli() -> None:
    """Run the CLI event loop."""
    core = SpokeCore()

    # Print header
    cwd = os.getcwd()
    print(r.header("strawberry-cli", "offline", core.get_model_info(), cwd))
    print()

    # Start core
    try:
        await core.start()
    except Exception as e:
        print(r.error_message(f"Failed to start: {e}"))
        return

    # Create session
    session = core.new_session()

    # Event handler
    def handle_event(event: CoreEvent) -> None:
        if isinstance(event, CoreReady):
            pass  # Already printed header
        elif isinstance(event, CoreError):
            print(r.error_message(event.error))
        elif isinstance(event, MessageAdded):
            if event.role == "assistant":
                print(r.assistant_message(event.content))
        elif isinstance(event, ToolCallStarted):
            args_preview = str(list(event.arguments.values())[0])[:50] if event.arguments else ""
            print(r.tool_call_started(event.tool_name, args_preview))
        elif isinstance(event, ToolCallResult):
            result_text = event.result if event.success else (event.error or "Unknown error")
            print(r.tool_call_result(event.success, result_text))

    subscription = core.subscribe(handle_event)

    try:
        while True:
            print(r.separator())

            # Get input
            try:
                user_input = input(r.user_prompt()).strip()
            except (KeyboardInterrupt, EOFError):
                break

            if not user_input:
                continue

            # Handle commands
            if user_input in ("/q", "/quit", "exit"):
                break
            elif user_input == "/clear":
                session.clear()
                print(r.info_message("Cleared conversation"))
                continue
            elif user_input == "/help":
                print(r.help_text())
                continue

            # Send message
            print(r.separator())
            await core.send_message(session.id, user_input)
            await asyncio.sleep(0)  # Yield to process pending events
            print()

    finally:
        subscription.cancel()
        await core.stop()
        print(r.info_message("Goodbye!"))


def main() -> None:
    """Entrypoint for strawberry-cli command."""
    try:
        asyncio.run(run_cli())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
