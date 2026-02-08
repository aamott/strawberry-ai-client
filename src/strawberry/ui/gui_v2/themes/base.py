"""Base theme class for GUI V2."""

from dataclasses import dataclass


@dataclass
class Theme:
    """Theme definition with color palette and styling.

    All colors are hex strings (e.g., "#1a1a2e").
    """
    # Identification
    name: str

    # Background colors
    bg_primary: str
    bg_secondary: str
    bg_tertiary: str
    bg_input: str
    bg_hover: str
    bg_selected: str

    # Text colors
    text_primary: str
    text_secondary: str
    text_muted: str
    text_link: str

    # Accent colors
    accent_primary: str
    accent_secondary: str

    # Status colors
    success: str
    warning: str
    error: str
    info: str

    # Border colors
    border: str
    border_light: str

    # Component-specific
    message_user_bg: str
    message_assistant_bg: str
    tool_call_bg: str
    sidebar_bg: str
    titlebar_bg: str
    statusbar_bg: str

    # Shadows (optional)
    shadow_color: str = "rgba(0, 0, 0, 0.3)"

    def get_stylesheet(self) -> str:
        """Generate minimal QSS stylesheet for this theme.

        Provides only essential styling:
        - Basic shading between main areas (chat, input, sidebar)
        - Font sizes
        - Pointer cursor on buttons
        - Rounded corners
        """
        return f"""
            /* Global - minimal base */
            QWidget {{
                background-color: {self.bg_primary};
                color: {self.text_primary};
                font-size: 14px;
            }}

            /* Button styling with hover/press animations */
            QPushButton, QToolButton {{
                border: none;
                border-radius: 6px;
                padding: 4px 8px;
                background-color: transparent;
            }}

            QPushButton:hover, QToolButton:hover {{
                background-color: {self.bg_hover};
            }}

            QPushButton:pressed, QToolButton:pressed {{
                background-color: {self.bg_selected};
            }}

            QPushButton:disabled, QToolButton:disabled {{
                opacity: 0.5;
                color: {self.text_muted};
            }}

            /* Sidebar - distinct shading with border */
            #SidebarRail {{
                background-color: {self.sidebar_bg};
                border-right: 1px solid {self.border};
            }}

            #SidebarRail QPushButton, #SidebarRail QToolButton {{
                border-radius: 8px;
            }}

            /* Nav button labels */
            #SidebarRail QLabel {{
                color: {self.text_primary};
                font-size: 14px;
            }}

            /* Input area - distinct from chat */
            #InputArea {{
                background-color: {self.bg_secondary};
            }}

            #InputArea QTextEdit {{
                background-color: {self.bg_input};
                border: 1px solid {self.border};
                border-radius: 20px;
                padding: 8px 12px;
            }}

            /* Input container buttons */
            #InputContainer QToolButton {{
                border-radius: 8px;
                padding: 6px;
                min-width: 32px;
                min-height: 32px;
            }}

            /* Send button accent color on hover */
            #SendButton:hover {{
                background-color: {self.accent_primary};
                color: white;
            }}

            /* Checked state for voice mode toggle */
            #VoiceModeButton:checked {{
                background-color: {self.accent_primary};
                color: white;
            }}

            /* Recording state for record button */
            #RecordButton[recording="true"] {{
                background-color: {self.error};
                color: white;
            }}

            /* Loading state for buttons (pulsing) */
            #RecordButton[loading="true"],
            #VoiceModeButton[loading="true"],
            #ReadAloudButton[loading="true"] {{
                background-color: {self.bg_selected};
                color: {self.text_muted};
            }}

            /* Session items hover */
            #SessionItem {{
                border-radius: 8px;
                padding: 4px;
            }}

            #SessionItem:hover {{
                background-color: {self.bg_hover};
            }}

            #SessionItem[selected="true"] {{
                background-color: {self.bg_selected};
            }}

            /* Message cards - rounded */
            #MessageCard {{
                background-color: {self.message_assistant_bg};
                border-radius: 12px;
                padding: 12px;
                margin: 4px 8px;
            }}

            #MessageCard[role="user"] {{
                background-color: {self.message_user_bg};
            }}

            /* Tool calls - subtle background */
            #ToolCallWidget {{
                background-color: {self.tool_call_bg};
                border-radius: 6px;
                padding: 6px 10px;
            }}

            /* Status bar - smaller text */
            #StatusBar QLabel {{
                font-size: 12px;
                color: {self.text_secondary};
            }}

            /* Scrollbar - minimal */
            QScrollBar:vertical {{
                width: 8px;
                background: transparent;
            }}

            QScrollBar::handle:vertical {{
                background-color: {self.border};
                border-radius: 4px;
                min-height: 30px;
            }}

            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}

            /* Offline banner */
            #OfflineBanner {{
                background-color: {self.warning};
                border-radius: 8px;
                padding: 8px;
            }}
        """
