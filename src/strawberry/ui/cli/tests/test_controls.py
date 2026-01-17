"""Tests for CLI prompt controls."""

from __future__ import annotations

from strawberry.ui.cli import controls
from strawberry.ui.cli.controls import PromptController, ShortcutAction


def test_prompt_controller_without_prompt_toolkit(monkeypatch) -> None:
    """Fallback to plain input when prompt_toolkit is unavailable."""
    monkeypatch.setattr(controls, "PromptSession", None)
    monkeypatch.setattr(controls, "KeyBindings", None)

    actions: list[ShortcutAction] = []

    def _on_shortcut(action: ShortcutAction) -> None:
        actions.append(action)

    controller = PromptController(_on_shortcut)
    assert controller.supports_shortcuts() is False
    controller._dispatch_shortcut(ShortcutAction.TOGGLE_TOOL_RESULT)
    assert actions == [ShortcutAction.TOGGLE_TOOL_RESULT]
