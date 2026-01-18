#!/usr/bin/env python3
"""CLI UI main entrypoint."""

# Suppress TensorZero Rust logs before any imports
import os

os.environ.setdefault("RUST_LOG", "error")

import asyncio
import sys

from ...core import (
    CoreError,
    CoreEvent,
    CoreReady,
    MessageAdded,
    SpokeCore,
    ToolCallResult,
    ToolCallStarted,
    VoiceStatusChanged,
)
from . import renderer as r

# Track voice state for status bar
_voice_state = "OFF"


def _render_status_bar(voice_state: str) -> None:
    """Render the bottom status bar with voice state."""
    # Move cursor to bottom, print status bar, move back
    width = r.get_width()
    bar = r.status_bar(voice_state, width)
    sys.stdout.write(f"\r{bar}\n")
    sys.stdout.flush()


async def run_cli() -> None:
    """Run the CLI event loop."""
    global _voice_state

    core = SpokeCore()

    # Print header
    cwd = os.getcwd()
    status = "online" if core.is_online() else "offline"
    print(r.header("strawberry-cli", status, core.get_model_info(), cwd))
    print()

    # Start core
    try:
        await core.start()
    except Exception as e:
        print(r.error_message(f"Failed to start: {e}"))
        return

    # Create session
    session = core.new_session()

    # Track last online state for mode notice
    last_online_state = core.is_online()

    # Event handler
    def handle_event(event: CoreEvent) -> None:
        global _voice_state
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
        elif isinstance(event, VoiceStatusChanged):
            _voice_state = event.state

    subscription = core.subscribe(handle_event)

    # Print initial status bar
    _render_status_bar(_voice_state)

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
            elif user_input == "/voice":
                # Toggle voice
                if _voice_state == "OFF" or _voice_state == "STOPPED":
                    success = await core.start_voice()
                    if success:
                        print(r.info_message("Voice started"))
                    else:
                        print(r.error_message("Failed to start voice"))
                else:
                    await core.stop_voice()
                    print(r.info_message("Voice stopped"))
                _render_status_bar(_voice_state)
                continue

            # Check if online state changed - inject mode notice
            current_online = core.is_online()
            if current_online != last_online_state:
                if current_online:
                    print(r.info_message(
                        "Runtime mode: ONLINE (Hub). "
                        "Remote devices are available via devices.<Device>.<Skill>.<method>()."
                    ))
                else:
                    print(r.info_message(
                        "Runtime mode: OFFLINE/LOCAL. "
                        "Use device.<Skill>.<method>() for local skills only."
                    ))
                last_online_state = current_online

            # Send message
            print(r.separator())
            await core.send_message(session.id, user_input)
            await asyncio.sleep(0)  # Yield to process pending events

            # Render status bar after response
            _render_status_bar(_voice_state)

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
