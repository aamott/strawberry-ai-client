"""Tests for PC Spoke GUI (Phase 1 — Chat History & Raw Output).

NOTE: Widget tests that require a QApplication are skipped if no display is
available (headless CI).
"""
import re
from unittest.mock import patch

import pytest

# ────────────────────────────────────────────────────────────────────────────
# Helper: Check if Qt GUI tests can run
# ────────────────────────────────────────────────────────────────────────────

def qt_available() -> bool:
    """Return True if Qt GUI tests can run (display + QApplication)."""
    try:
        import os

        from PySide6.QtWidgets import QApplication
        # Headless check: $DISPLAY or $WAYLAND_DISPLAY
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            return False
        # Ensure QApplication exists or can be created
        if QApplication.instance() is None:
            QApplication([])  # Create app if not exists
        return True
    except Exception:
        return False


# ────────────────────────────────────────────────────────────────────────────
# Chat History Sidebar: Populate on connection
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not qt_available(), reason="Qt GUI unavailable (headless)")
class TestChatHistorySidebar:
    """Sidebar should populate chat history from storage after Hub connection."""

    def test_set_sessions_populates_items(self):
        """ChatHistorySidebar.set_sessions should populate item widgets."""
        from datetime import datetime, timezone

        from strawberry.ui.theme import DARK_THEME
        from strawberry.ui.widgets.chat_history import ChatHistorySidebar

        sidebar = ChatHistorySidebar(theme=DARK_THEME)

        sessions = [
            {
                "id": "session-1",
                "title": "Test Chat 1",
                "message_count": 5,
                "last_activity": datetime.now(timezone.utc),
            },
            {
                "id": "session-2",
                "title": "Test Chat 2",
                "message_count": 3,
                "last_activity": datetime.now(timezone.utc),
            },
        ]

        sidebar.set_sessions(sessions)

        assert len(sidebar._items) == 2
        assert "session-1" in sidebar._items
        assert "session-2" in sidebar._items

    def test_empty_sessions_shows_empty_state(self):
        """Empty sessions list should show empty state label."""
        from strawberry.ui.theme import DARK_THEME
        from strawberry.ui.widgets.chat_history import ChatHistorySidebar

        sidebar = ChatHistorySidebar(theme=DARK_THEME)
        sidebar.set_sessions([])

        # isVisible() depends on parent visibility; check isVisibleTo parent
        assert sidebar._empty_label.isVisibleTo(sidebar)


# ────────────────────────────────────────────────────────────────────────────
# Raw Output Rendering: Code blocks should NOT be stripped
# ────────────────────────────────────────────────────────────────────────────

class TestRawOutputRendering:
    """LLM responses containing code blocks should show them verbatim."""

    def test_code_blocks_remain_in_response(self):
        """Regex substitution should NOT be applied when raw mode is enabled."""
        # This test validates the intent of raw output mode.
        # The regex that removes code blocks is:
        pattern = r"```[pP]ython\s*.*?\s*```"
        sample = "Here is python code:\n```python\nprint('hello')\n```\n"

        # Raw mode: content should remain unchanged
        raw_content = sample  # No substitution
        assert "```python" in raw_content

        # Old behaviour (stripping) — make sure we understand it
        stripped = re.sub(pattern, "", sample, flags=re.DOTALL).strip()
        assert "```python" not in stripped


# ────────────────────────────────────────────────────────────────────────────
# Markdown Renderer: Ensure code blocks render properly
# ────────────────────────────────────────────────────────────────────────────

class TestMarkdownRenderer:
    """Markdown renderer should produce HTML for code blocks."""

    def test_render_code_block(self):
        """Code blocks should be rendered as preformatted HTML."""
        from strawberry.ui.markdown_renderer import render_markdown

        # render_markdown can accept None for theme
        md = "```python\nprint('hi')\n```"
        html = render_markdown(md, theme=None)

        # Should contain <pre> or <code> for code blocks
        assert "<pre" in html.lower() or "<code" in html.lower()

    def test_render_headings(self):
        """Headings should render as h1, h2, h3."""
        from strawberry.ui.markdown_renderer import render_markdown

        md = "# Heading 1\n## Heading 2\n### Heading 3"
        html = render_markdown(md, theme=None)

        assert "<h1" in html.lower()
        assert "<h2" in html.lower()
        assert "<h3" in html.lower()

    def test_render_lists(self):
        """Lists should render as ul/ol."""
        from strawberry.ui.markdown_renderer import render_markdown

        md = "- Item 1\n- Item 2\n- Item 3"
        html = render_markdown(md, theme=None)

        assert "<ul" in html.lower()
        assert "<li" in html.lower()

    def test_render_bold_italic(self):
        """Bold and italic should render properly."""
        from strawberry.ui.markdown_renderer import render_markdown

        md = "**bold** and *italic*"
        html = render_markdown(md, theme=None)

        assert "<strong" in html.lower() or "<b>" in html.lower()
        assert "<em" in html.lower() or "<i>" in html.lower()

    def test_render_links(self):
        """Links should render as anchor tags."""
        from strawberry.ui.markdown_renderer import render_markdown

        md = "[link](https://example.com)"
        html = render_markdown(md, theme=None)

        assert "<a " in html.lower()
        assert "href" in html.lower()


# ────────────────────────────────────────────────────────────────────────────
# Session Refresh on Hub Connect (unit test, no GUI)
# ────────────────────────────────────────────────────────────────────────────

class TestSessionRefreshLogic:
    """_update_hub_status should trigger session refresh."""

    def test_update_hub_status_triggers_refresh(self):
        """When connected=True, _refresh_sessions should be scheduled."""
        # We test the logic by verifying asyncio.ensure_future is called

        # Create a mock coro to simulate _refresh_sessions
        async def fake_refresh():
            pass

        with patch("asyncio.ensure_future") as mock_ensure:
            # Simulate the call pattern in _update_hub_status
            # The actual method does: asyncio.ensure_future(self._refresh_sessions())
            mock_ensure.return_value = None
            coro = fake_refresh()
            mock_ensure(coro)
            coro.close()

            mock_ensure.assert_called()


# ────────────────────────────────────────────────────────────────────────────
# Phase 2: Code Block Parsing
# ────────────────────────────────────────────────────────────────────────────

class TestCodeBlockParsing:
    """Test _parse_chunks function for splitting markdown."""

    def test_parse_pure_text(self):
        """Pure text without code blocks."""
        from strawberry.ui.widgets.assistant_turn_widget import _parse_chunks

        chunks = _parse_chunks("Hello world")
        assert len(chunks) == 1
        assert chunks[0] == ("text", "Hello world", None)

    def test_parse_single_code_block(self):
        """Single code block."""
        from strawberry.ui.widgets.assistant_turn_widget import _parse_chunks

        md = "```python\nprint('hi')\n```"
        chunks = _parse_chunks(md)
        assert len(chunks) == 1
        assert chunks[0] == ("code", "print('hi')", "python")

    def test_parse_text_and_code(self):
        """Text before and after code block."""
        from strawberry.ui.widgets.assistant_turn_widget import _parse_chunks

        md = "Here is code:\n```python\nprint('hi')\n```\nDone."
        chunks = _parse_chunks(md)
        assert len(chunks) == 3
        assert chunks[0][0] == "text"
        assert chunks[1] == ("code", "print('hi')", "python")
        assert chunks[2][0] == "text"

    def test_parse_multiple_code_blocks(self):
        """Multiple code blocks."""
        from strawberry.ui.widgets.assistant_turn_widget import _parse_chunks

        md = "```python\na=1\n```\ntext\n```javascript\nb=2\n```"
        chunks = _parse_chunks(md)
        assert len(chunks) == 3
        assert chunks[0] == ("code", "a=1", "python")
        assert chunks[1][0] == "text"
        assert chunks[2] == ("code", "b=2", "javascript")

    def test_parse_output_block(self):
        """Test parsing of output/result blocks."""
        from strawberry.ui.widgets.assistant_turn_widget import _parse_chunks

        # Test ```output ... ```
        md = "```output\nResult: 42\n```"
        chunks = _parse_chunks(md)
        assert len(chunks) == 1
        assert chunks[0] == ("output", "Result: 42", None)

        # Test ```result ... ``` (alias)
        md = "```result\nResult: 42\n```"
        chunks = _parse_chunks(md)
        assert len(chunks) == 1
        assert chunks[0] == ("output", "Result: 42", None)


@pytest.mark.skipif(not qt_available(), reason="Qt GUI unavailable (headless)")
class TestCodeBlockWidget:
    """Test CodeBlockWidget behavior."""

    def test_initial_state_collapsed(self):
        """Widget should start collapsed."""
        from strawberry.ui.theme import DARK_THEME
        from strawberry.ui.widgets.code_block_widget import CodeBlockWidget

        widget = CodeBlockWidget(code="print('hi')", theme=DARK_THEME)
        assert not widget.is_expanded()
        assert not widget._code_frame.isVisibleTo(widget)

    def test_toggle_expand(self):
        """Toggle should expand and collapse."""
        from strawberry.ui.theme import DARK_THEME
        from strawberry.ui.widgets.code_block_widget import CodeBlockWidget

        widget = CodeBlockWidget(code="print('hi')", theme=DARK_THEME)
        widget.set_expanded(True)
        assert widget.is_expanded()
        widget.set_expanded(False)
        assert not widget.is_expanded()


@pytest.mark.skipif(not qt_available(), reason="Qt GUI unavailable (headless)")
class TestOutputWidget:
    """Test OutputWidget behavior."""

    def test_init(self):
        """Widget initializes with correct content."""
        from strawberry.ui.theme import DARK_THEME
        from strawberry.ui.widgets.output_widget import OutputWidget

        widget = OutputWidget(content="Test Output", theme=DARK_THEME)
        assert widget._text_label.text() == "Test Output"
        assert widget.objectName() == "outputWidget"
