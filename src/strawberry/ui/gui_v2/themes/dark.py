"""Dark theme for GUI V2."""

from .base import Theme

DARK_THEME = Theme(
    name="dark",

    # Background colors
    bg_primary="#1a1a2e",
    bg_secondary="#16213e",
    bg_tertiary="#0f3460",
    bg_input="#1e1e3f",
    bg_hover="#2a2a4a",
    bg_selected="#3a3a5a",

    # Text colors
    text_primary="#ffffff",
    text_secondary="#a0a0a0",
    text_muted="#666666",
    text_link="#6ea8fe",

    # Accent colors
    accent_primary="#e94560",
    accent_secondary="#533483",

    # Status colors
    success="#4ade80",
    warning="#fbbf24",
    error="#ef4444",
    info="#3b82f6",

    # Border colors
    border="#2a2a4a",
    border_light="#3a3a5a",

    # Component-specific
    message_user_bg="#2a2a4a",
    message_assistant_bg="#1e1e3f",
    tool_call_bg="#252545",
    sidebar_bg="#16213e",
    titlebar_bg="#16213e",
    statusbar_bg="#16213e",

    # Shadows
    shadow_color="rgba(0, 0, 0, 0.4)",
)
