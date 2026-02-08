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
        """Generate the QSS stylesheet for this theme.

        Covers all component areas: title bar, sidebar, chat area,
        input area, message cards, tool calls, status bar, and
        interactive states (hover, pressed, disabled, checked, loading).
        """
        return f"""
            /* ───────────────────── Global ───────────────────── */
            QWidget {{
                background-color: {self.bg_primary};
                color: {self.text_primary};
                font-family: "Segoe UI", "SF Pro Text", "Helvetica Neue", Arial, sans-serif;
                font-size: 14px;
            }}

            /* ───────────────────── Buttons (base) ───────────── */
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
                color: {self.text_muted};
            }}

            /* ───────────────────── Title bar ────────────────── */
            #TitleBar {{
                background-color: {self.titlebar_bg};
                border-bottom: 1px solid {self.border};
            }}

            #AppTitle {{
                font-size: 15px;
                font-weight: bold;
                color: {self.accent_primary};
            }}

            /* Close button red highlight on hover */
            #CloseButton:hover {{
                background-color: {self.error};
                color: white;
            }}

            /* ───────────────────── Sidebar ──────────────────── */
            #SidebarRail {{
                background-color: {self.sidebar_bg};
                border-right: 1px solid {self.border};
            }}

            #SidebarRail QToolButton {{
                border-radius: 8px;
                min-width: 32px;
                min-height: 32px;
                font-size: 16px;
            }}

            /* Nav button labels (shown when expanded) */
            #SidebarRail QLabel {{
                color: {self.text_primary};
                font-size: 13px;
            }}

            /* Session items */
            #SessionItem {{
                border-radius: 8px;
                padding: 6px 8px;
                margin: 1px 0px;
            }}

            #SessionItem:hover {{
                background-color: {self.bg_hover};
            }}

            #SessionItem[selected="true"] {{
                background-color: {self.bg_selected};
                border-left: 3px solid {self.accent_primary};
            }}

            #SessionTitle {{
                font-size: 13px;
                color: {self.text_secondary};
            }}

            #SessionItem[selected="true"] #SessionTitle {{
                color: {self.text_primary};
                font-weight: bold;
            }}

            /* ───────────────────── Input area ───────────────── */
            #InputArea {{
                background-color: {self.bg_secondary};
                border-top: 1px solid {self.border};
            }}

            #InputContainer {{
                background-color: {self.bg_input};
                border: 1px solid {self.border};
                border-radius: 22px;
            }}

            #InputContainer QTextEdit {{
                background-color: transparent;
                border: none;
                padding: 6px 4px;
                font-size: 14px;
                color: {self.text_primary};
            }}

            /* Input action buttons — circular, subtle */
            #InputContainer QToolButton {{
                border-radius: 16px;
                padding: 4px;
                min-width: 32px;
                min-height: 32px;
                max-width: 32px;
                max-height: 32px;
                font-size: 15px;
                color: {self.text_secondary};
            }}

            #InputContainer QToolButton:hover {{
                background-color: {self.bg_hover};
                color: {self.text_primary};
            }}

            /* Send button — accent on hover */
            #SendButton {{
                color: {self.accent_primary};
            }}

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

            /* Loading state for buttons */
            #RecordButton[loading="true"],
            #VoiceModeButton[loading="true"],
            #ReadAloudButton[loading="true"] {{
                background-color: {self.bg_selected};
                color: {self.text_muted};
            }}

            /* ───────────────────── Message cards ────────────── */
            #MessageCard {{
                background-color: {self.message_assistant_bg};
                border: 1px solid {self.border};
                border-radius: 12px;
                padding: 12px 16px;
                margin: 4px 12px;
            }}

            #MessageCard[role="user"] {{
                background-color: {self.message_user_bg};
            }}

            #RoleLabel {{
                font-size: 13px;
                font-weight: bold;
                color: {self.text_secondary};
            }}

            #TimestampLabel {{
                font-size: 11px;
                color: {self.text_muted};
            }}

            #MessageSeparator {{
                color: {self.border};
            }}

            /* Read-aloud button in message header — small, subtle */
            #ReadAloudButton {{
                font-size: 13px;
                min-width: 26px;
                min-height: 26px;
                max-width: 26px;
                max-height: 26px;
                border-radius: 13px;
                color: {self.text_muted};
            }}

            #ReadAloudButton:hover {{
                color: {self.text_primary};
                background-color: {self.bg_hover};
            }}

            /* ───────────────────── Tool calls ───────────────── */
            #ToolCallWidget {{
                background-color: {self.tool_call_bg};
                border: 1px solid {self.border};
                border-radius: 8px;
                padding: 8px 12px;
            }}

            /* ───────────────────── Status bar ───────────────── */
            #StatusBar {{
                background-color: {self.statusbar_bg};
                border-top: 1px solid {self.border};
            }}

            #StatusBar QLabel {{
                font-size: 11px;
                color: {self.text_muted};
            }}

            #FlashMessage {{
                color: {self.warning};
                font-weight: bold;
            }}

            /* ───────────────────── Scrollbar ────────────────── */
            QScrollBar:vertical {{
                width: 6px;
                background: transparent;
            }}

            QScrollBar::handle:vertical {{
                background-color: {self.border};
                border-radius: 3px;
                min-height: 30px;
            }}

            QScrollBar::handle:vertical:hover {{
                background-color: {self.border_light};
            }}

            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}

            /* ───────────────────── Offline banner ───────────── */
            #OfflineBanner {{
                background-color: {self.warning};
                border-radius: 8px;
                padding: 8px;
                color: {self.bg_primary};
            }}
        """
