"""Light theme for GUI V2."""

from .base import Theme

LIGHT_THEME = Theme(
    name="light",

    # Background colors
    bg_primary="#ffffff",
    bg_secondary="#f8f9fa",
    bg_tertiary="#e9ecef",
    bg_input="#ffffff",
    bg_hover="#e9ecef",
    bg_selected="#dee2e6",

    # Text colors
    text_primary="#212529",
    text_secondary="#6c757d",
    text_muted="#adb5bd",
    text_link="#0d6efd",

    # Accent colors
    accent_primary="#e94560",
    accent_secondary="#533483",

    # Status colors
    success="#198754",
    warning="#ffc107",
    error="#dc3545",
    info="#0dcaf0",

    # Border colors
    border="#dee2e6",
    border_light="#e9ecef",

    # Component-specific
    message_user_bg="#e7f1ff",
    message_assistant_bg="#f8f9fa",
    tool_call_bg="#e9ecef",
    sidebar_bg="#f8f9fa",
    titlebar_bg="#f8f9fa",
    statusbar_bg="#f8f9fa",

    # Shadows
    shadow_color="rgba(0, 0, 0, 0.1)",
)
