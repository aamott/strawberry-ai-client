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

    def get_stylesheet(self) -> str:  # noqa: E501
        """Generate the QSS stylesheet for this theme.

        Covers: global, buttons, title bar, sidebar, input area,
        message cards, tool calls, status bar, scrollbar.
        """
        # QSS rules are intentionally compact; line length is
        # governed by the stylesheet, not Python style.
        bg = self.bg_primary
        fg = self.text_primary
        hover = self.bg_hover
        sel = self.bg_selected
        bdr = self.border
        muted = self.text_muted
        sec = self.text_secondary
        acc = self.accent_primary

        return f"""
/* Global */
QWidget {{
    background-color: {bg}; color: {fg};
    font-family: "Segoe UI", "SF Pro Text", sans-serif;
    font-size: 14px;
}}

/* Buttons */
QPushButton, QToolButton {{
    border: none; border-radius: 6px;
    padding: 4px 8px; background-color: transparent;
}}
QPushButton:hover, QToolButton:hover {{ background-color: {hover}; }}
QPushButton:pressed, QToolButton:pressed {{ background-color: {sel}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {muted}; }}

/* Title bar */
#TitleBar {{
    background-color: {self.titlebar_bg};
    border-bottom: 1px solid {bdr};
}}
#AppTitle {{ font-size: 15px; font-weight: bold; color: {acc}; }}
#CloseButton:hover {{ background-color: {self.error}; color: white; }}

/* Sidebar */
#SidebarRail {{
    background-color: {self.sidebar_bg};
    border-right: 1px solid {bdr};
}}
#SidebarRail QWidget, #SidebarRail QFrame,
#SidebarRail QLabel, #SidebarRail QScrollArea {{
    background-color: transparent;
}}
#SidebarRail QToolButton {{
    background-color: transparent;
    border-radius: 8px; padding: 4px;
    min-width: 32px; min-height: 32px;
    max-width: 32px; max-height: 32px;
    font-size: 16px;
}}
#SidebarRail QLabel {{ font-size: 13px; }}
#NavButton {{ border-radius: 8px; }}
#NavButton:hover {{ background-color: {hover}; }}
#SessionEdit {{
    background-color: {self.bg_input};
    border: 1px solid {acc}; border-radius: 4px;
    padding: 2px 4px; font-size: 13px;
}}

/* Session items */
#SessionItem {{ border-radius: 8px; padding: 6px 8px; }}
#SessionItem:hover {{ background-color: {hover}; }}
#SessionItem[selected="true"] {{
    background-color: {sel};
    border-left: 3px solid {acc};
}}
#SessionTitle {{ font-size: 13px; color: {sec}; }}

/* Input area */
#InputArea {{
    background-color: {self.bg_secondary};
    border-top: 1px solid {bdr};
}}
#InputContainer {{
    background-color: {self.bg_input};
    border: 1px solid {bdr}; border-radius: 22px;
}}
#InputContainer QTextEdit {{
    background-color: transparent;
    border: none; padding: 6px 4px;
}}
#InputContainer QToolButton {{
    border-radius: 16px; padding: 4px;
    min-width: 32px; min-height: 32px;
    max-width: 32px; max-height: 32px;
    font-size: 15px; color: {sec};
}}
#InputContainer QToolButton:hover {{ color: {fg}; }}
#SendButton {{ color: {acc}; }}
#SendButton:hover {{ background-color: {acc}; color: white; }}

/* Voice button states */
#VoiceModeButton:checked {{ background-color: {acc}; color: white; }}
#RecordButton[recording="true"] {{
    background-color: {self.error}; color: white;
}}
#RecordButton[loading="true"],
#VoiceModeButton[loading="true"],
#ReadAloudButton[loading="true"] {{
    background-color: {sel}; color: {muted};
}}

/* Message cards */
#MessageCard {{
    background-color: {self.message_assistant_bg};
    border: 1px solid {bdr}; border-radius: 12px;
    padding: 12px 16px; margin: 4px 12px;
}}
#MessageCard[role="user"] {{ background-color: {self.message_user_bg}; }}
#MessageCard QWidget, #MessageCard QLabel,
#MessageCard QFrame, #MessageCard QTextBrowser {{
    background-color: transparent;
}}
#RoleLabel {{ font-size: 13px; font-weight: bold; color: {sec}; }}
#TimestampLabel {{ font-size: 11px; color: {muted}; }}
#MessageSeparator {{ color: {bdr}; }}

/* Action buttons (read aloud, copy) */
#ReadAloudButton, #CopyButton {{
    font-size: 13px; border-radius: 13px; color: {muted};
    border: 1px solid {self.border_light};
    min-width: 26px; min-height: 26px;
    max-width: 26px; max-height: 26px;
}}
#ReadAloudButton:hover, #CopyButton:hover {{
    background-color: {hover};
    color: {fg};
}}

/* Tool calls */
#ToolCallWidget {{
    background-color: {self.tool_call_bg};
    border: 1px solid {bdr}; border-radius: 8px;
    padding: 8px 12px;
}}

/* Status bar */
#StatusBar {{
    background-color: {self.statusbar_bg};
    border-top: 1px solid {bdr};
}}
#StatusBar QWidget, #StatusBar QLabel {{
    background-color: transparent;
    font-size: 11px; color: {muted};
}}
#FlashMessage {{ color: {self.warning}; font-weight: bold; }}

/* Scrollbar */
QScrollBar:vertical {{ width: 6px; background: transparent; }}
QScrollBar::handle:vertical {{
    background-color: {bdr}; border-radius: 3px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background-color: {self.border_light}; }}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{ height: 0; }}

/* Offline banner */
#OfflineBanner {{
    background-color: {self.warning}; border-radius: 8px;
    padding: 8px; color: {bg};
}}
        """
