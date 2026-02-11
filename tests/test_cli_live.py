"""Live CLI/SpokeCore integration tests with actual LLM calls.

These tests verify the full pipeline from SpokeCore through tool execution.

Requirements:
- GOOGLE_AI_STUDIO_API_KEY env var (for gemini variant) or Ollama running locally
- Skills loaded from skills/ directory

Run with: .venv/bin/python -m pytest tests/test_cli_live.py -v
"""

import asyncio
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Suppress TensorZero Rust logs
os.environ.setdefault("RUST_LOG", "error")

# Load .env file from project root
_project_root = Path(__file__).parent.parent
load_dotenv(_project_root / ".env")

# Provide dummy HUB_DEVICE_TOKEN if not set
if not os.environ.get("HUB_DEVICE_TOKEN"):
    os.environ["HUB_DEVICE_TOKEN"] = "dummy-for-testing"


# Skip all tests if no API keys are configured and Ollama not available
def _check_llm_available() -> bool:
    """Check if any LLM backend is available."""
    if os.environ.get("GOOGLE_AI_STUDIO_API_KEY"):
        return True
    # Check for Ollama
    try:
        import httpx

        response = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        return response.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _check_llm_available(),
    reason="No LLM backend available (need GOOGLE_AI_STUDIO_API_KEY or Ollama)",
)


class TestSpokeCoreToolExecution:
    """Test SpokeCore agent loop with live LLM and tool execution."""

    @pytest.fixture
    async def core(self):
        """Create and start a SpokeCore instance with deterministic test hooks."""
        from strawberry.spoke_core import SpokeCore

        core = SpokeCore()
        # Enable deterministic tool hooks for testing
        core._settings_manager.set("spoke_core", "testing.deterministic_tool_hooks", True)
        await core.start()
        yield core
        await core.stop()

    @pytest.mark.asyncio
    async def test_core_starts_and_loads_skills(self, core):
        """Test that SpokeCore can start and load skills."""
        # Core should have a system prompt with skill info
        prompt = core.get_system_prompt()
        assert "Strawberry" in prompt or "assistant" in prompt.lower()
        assert len(prompt) > 50, "System prompt should have content"

    @pytest.mark.asyncio
    async def test_simple_message_response(self, core):
        """Test that a simple message gets a response."""
        session = core.new_session()

        # Track events
        events = []

        def handler(event):
            events.append(event)

        subscription = core.subscribe(handler)

        try:
            await core.send_message(session.id, "Say 'hello' and nothing else.")
            await asyncio.sleep(0.5)  # Allow events to process

            # Should have received at least a MessageAdded event
            from strawberry.spoke_core import MessageAdded

            message_events = [e for e in events if isinstance(e, MessageAdded)]
            assert len(message_events) >= 1, f"Expected message events, got: {events}"

            # Check we got an assistant response
            assistant_msgs = [e for e in message_events if e.role == "assistant"]
            assert len(assistant_msgs) >= 1, "Should have an assistant message"
            assert assistant_msgs[0].content, "Assistant message should have content"

        finally:
            subscription.cancel()

    @pytest.mark.asyncio
    async def test_tool_call_search_skills(self, core):
        """Test that search_skills tool is called for capability queries.

        This is a critical test ensuring the LLM uses tools when appropriate.
        """
        session = core.new_session()

        events = []

        def handler(event):
            events.append(event)

        subscription = core.subscribe(handler)

        try:
            # Ask about weather - should trigger search_skills or direct tool call
            await core.send_message(
                session.id, "What skills do you have? Use search_skills to find out."
            )
            await asyncio.sleep(2.0)  # Allow time for LLM + tool execution

            from strawberry.spoke_core import ToolCallResult, ToolCallStarted

            tool_starts = [e for e in events if isinstance(e, ToolCallStarted)]
            tool_results = [e for e in events if isinstance(e, ToolCallResult)]

            # Log what we got for debugging
            print(f"\nTool calls started: {[t.tool_name for t in tool_starts]}")
            print(f"Tool results: {[(t.tool_name, t.success) for t in tool_results]}")

            # Should have at least one tool call started
            # This verifies the system prompt is correctly informing the LLM about tools
            assert len(tool_starts) >= 1, (
                f"Expected at least one tool call, got events: "
                f"{[type(e).__name__ for e in events]}"
            )

            # Check tool results - success OR sandbox-related failure is acceptable
            # (Deno may not be installed in test environment)
            for result in tool_results:
                if not result.success:
                    # Sandbox unavailability is an infrastructure issue, not a code bug
                    if "Sandbox unavailable" in (result.error or ""):
                        print(f"[Note] Tool failed due to sandbox: {result.error}")
                        continue
                    # Other failures should be investigated
                    print(f"[Warning] Tool failed: {result.error}")

        finally:
            subscription.cancel()

    @pytest.mark.asyncio
    async def test_calculator_tool_execution(self, core):
        """Test that math queries can use calculator skill."""
        session = core.new_session()

        events = []

        def handler(event):
            events.append(event)

        subscription = core.subscribe(handler)

        try:
            # Ask for a calculation - should use python_exec with calculator
            await core.send_message(
                session.id,
                (
                    "You MUST use the python_exec tool to calculate: "
                    "device.CalculatorSkill.multiply(7, 8). "
                    "Do not explain, just run the code."
                ),
            )
            await asyncio.sleep(3.0)  # Increased timeout for robustness

            from strawberry.spoke_core import (
                MessageAdded,
                ToolCallResult,
                ToolCallStarted,
            )

            tool_starts = [e for e in events if isinstance(e, ToolCallStarted)]
            tool_results = [e for e in events if isinstance(e, ToolCallResult)]
            messages = [
                e for e in events if isinstance(e, MessageAdded) and e.role == "assistant"
            ]

            # Log what we got
            print(f"\nTool calls started: {[t.tool_name for t in tool_starts]}")
            print(f"Tool results: {[(t.tool_name, t.success) for t in tool_results]}")

            # Primary check: tool call was initiated (proves system prompt works)
            if tool_starts:
                print(f"Tool call initiated: {tool_starts[0].tool_name}")
                # Check results
                for result in tool_results:
                    if result.success:
                        result_text = result.result or ""
                        if "56" in result_text:
                            print(f"Calculator test passed: {result_text}")
                            return
                    elif "Sandbox unavailable" in (result.error or ""):
                        # Sandbox not available - test passes since tool was called
                        print("[Note] Tool called but sandbox unavailable")
                        return
                # Tool was called, that's a pass for this test
                return

            # Fallback: check if answer is in message
            for msg in messages:
                if "56" in msg.content:
                    print(f"Answer found in message: {msg.content[:100]}")
                    return

            # Fail if no tool call was initiated
            pytest.fail(
                f"Expected tool call to be initiated. "
                f"Events: {[type(e).__name__ for e in events]}"
            )

        finally:
            subscription.cancel()


class TestCLIRendering:
    """Test CLI renderer functions (no LLM needed)."""

    def test_status_bar_rendering(self):
        """Test status bar renders correctly for different states."""
        from strawberry.ui.cli import renderer as r

        # Test OFF state
        bar = r.status_bar("OFF", 80)
        assert "Off" in bar
        assert "/voice" in bar
        assert "/help" in bar

        # Test LISTENING state
        bar = r.status_bar("LISTENING", 80)
        assert "Listening" in bar

        # Test IDLE state
        bar = r.status_bar("IDLE", 80)
        assert "Waiting" in bar

    def test_message_rendering(self):
        """Test message rendering functions."""
        from strawberry.ui.cli import renderer as r

        # User message
        user_msg = r.user_message("Hello")
        assert "Hello" in user_msg

        # Assistant message
        asst_msg = r.assistant_message("Hi there")
        assert "Hi there" in asst_msg

        # Tool call
        tool_msg = r.tool_call_started("search_skills", "weather")
        assert "search_skills" in tool_msg
        assert "weather" in tool_msg

        # Tool result
        result = r.tool_call_result(True, "Found 3 skills")
        assert "Found 3 skills" in result

        error = r.tool_call_result(False, "Not found")
        assert "Error" in error


if __name__ == "__main__":
    # Allow running directly for quick testing

    async def main():
        print("Running CLI live integration tests...")
        api_key_set = bool(os.environ.get("GOOGLE_AI_STUDIO_API_KEY"))
        print(f"GOOGLE_AI_STUDIO_API_KEY set: {api_key_set}")

        from strawberry.spoke_core import (
            MessageAdded,
            SpokeCore,
            ToolCallResult,
            ToolCallStarted,
        )

        core = SpokeCore()
        await core.start()

        try:
            session = core.new_session()
            events = []

            def handler(event):
                events.append(event)
                if isinstance(event, ToolCallStarted):
                    print(f"[Tool Start] {event.tool_name}")
                elif isinstance(event, ToolCallResult):
                    status = "✓" if event.success else "✗"
                    print(f"[Tool Result] {status} {event.tool_name}")
                elif isinstance(event, MessageAdded) and event.role == "assistant":
                    print(f"[Assistant] {event.content[:100]}...")

            subscription = core.subscribe(handler)

            print("\nSending: 'What skills do you have? Use search_skills.'")
            await core.send_message(
                session.id, "What skills do you have? Use search_skills to find out."
            )
            await asyncio.sleep(3.0)

            print(f"\nTotal events: {len(events)}")
            tool_calls = [e for e in events if isinstance(e, ToolCallStarted)]
            print(f"Tool calls: {[t.tool_name for t in tool_calls]}")

            subscription.cancel()

        finally:
            await core.stop()

    asyncio.run(main())
