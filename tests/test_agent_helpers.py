"""Unit tests for UI agent loop helpers.

These helpers are used by the Hub and TensorZero agent loops.
"""

from __future__ import annotations

from strawberry.models import ChatMessage
from strawberry.ui.qt.agent_helpers import append_in_band_tool_feedback


def test_append_in_band_tool_feedback_appends_assistant_then_user() -> None:
    messages: list[ChatMessage] = []

    append_in_band_tool_feedback(
        messages,
        assistant_content="tool call content",
        outputs=["pong"],
    )

    assert [m.role for m in messages] == ["assistant", "user"]
    assert messages[0].content == "tool call content"
    assert "[Code executed. Output:]" in messages[1].content
    assert "pong" in messages[1].content
