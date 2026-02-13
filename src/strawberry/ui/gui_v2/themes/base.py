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

/* Tooltips */
QToolTip {{
    background-color: {self.bg_secondary};
    color: {fg};
    border: 1px solid {bdr};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
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
#NavButton[selected="true"] {{ background-color: {sel}; }}
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

/* Toast notifications */
#ToastCard {{
    background-color: {self.bg_secondary};
    border: 1px solid {self.border_light};
    border-radius: 10px;
    color: {fg};
}}
#ToastCard[level="warning"] {{ border-left: 3px solid {self.warning}; }}
#ToastCard[level="error"] {{ border-left: 3px solid {self.error}; }}
#ToastCard[level="success"] {{ border-left: 3px solid {self.success}; }}
#ToastCard[level="info"] {{ border-left: 3px solid {self.info}; }}
#ToastCard QLabel {{ background-color: transparent; }}
#ToastIcon {{ font-size: 15px; }}
#ToastText {{ font-size: 13px; color: {fg}; }}

/* Skills panel */
#SkillsPanel {{
    background-color: {bg};
}}
#SkillsPanelHeader {{
    font-size: 18px; font-weight: bold; color: {fg};
}}
#SkillsPanelSummary {{
    font-size: 12px; color: {muted};
}}
#SkillsSectionHeader {{
    font-size: 13px; font-weight: bold; color: {sec};
    padding: 6px 0 2px 0;
}}
#SkillCard {{
    background-color: {self.bg_secondary};
    border: 1px solid {bdr}; border-radius: 8px;
}}
#SkillCard:hover {{ border-color: {self.border_light}; }}
#SkillCard[disabled_skill="true"] {{ opacity: 0.5; }}
#SkillCardIcon {{ font-size: 18px; }}
#SkillCardName {{ font-size: 14px; font-weight: bold; }}
#SkillCardDetail {{ font-size: 12px; color: {muted}; }}
#SkillCardHealthWarning {{ font-size: 12px; color: {self.warning}; }}
#SkillFailureCard {{
    background-color: {self.bg_secondary};
    border: 1px solid {self.error}; border-radius: 8px;
}}
#SkillFailureName {{ font-size: 14px; font-weight: bold; color: {self.error}; }}
#SkillFailureError {{ font-size: 12px; color: {muted}; }}

/* Offline banner */
#OfflineBanner {{
    background-color: {self.warning}; border-radius: 8px;
    padding: 8px; color: {bg};
}}
        """

    def get_settings_stylesheet(self) -> str:  # noqa: E501
        """Generate the QSS stylesheet for the settings dialog.

        Covers: settings window chrome, tab bar, section frames,
        buttons, field inputs, checkboxes, sliders, lists, and scrollbar.
        """
        bg = self.bg_primary
        fg = self.text_primary
        hover = self.bg_hover
        sel = self.bg_selected
        bdr = self.border
        bdr_lt = self.border_light
        muted = self.text_muted
        sec = self.text_secondary
        acc = self.accent_primary
        inp = self.bg_input
        panel = self.bg_secondary
        section = (
            self.bg_tertiary
            if self.bg_tertiary != self.bg_secondary
            else self.bg_input
        )

        return f"""
/* Settings dialog */
QDialog#SettingsWindow {{
    background-color: {bg};
    color: {fg};
}}

/* Tab bar */
QTabWidget::pane {{
    border: 1px solid {bdr};
    border-radius: 8px;
    background-color: {panel};
    top: -1px;
}}
QTabBar::tab {{
    background-color: {bg};
    color: {sec};
    border: 1px solid {bdr};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 20px;
    margin-right: 2px;
    font-size: 13px;
}}
QTabBar::tab:selected {{
    background-color: {panel};
    color: {fg};
    border-bottom: 2px solid {acc};
}}
QTabBar::tab:hover:!selected {{
    background-color: {hover};
    color: {fg};
}}

/* Scroll area */
QScrollArea {{
    background-color: transparent;
    border: none;
}}

/* Section frames */
QFrame#NamespaceSection {{
    background-color: {section};
    border: 1px solid {bdr};
    border-radius: 8px;
    padding: 4px;
}}

/* Group labels */
QLabel#GroupLabel {{
    color: {muted};
    font-size: 11px;
    font-style: italic;
}}

/* Section header */
QLabel#SectionHeader {{
    color: {fg};
    font-size: 14px;
    font-weight: bold;
}}

/* Status label */
QLabel#StatusLabel {{
    color: {muted};
    font-size: 12px;
}}

/* Buttons */
QPushButton#ApplyBtn, QPushButton#DiscardBtn {{
    background-color: {hover};
    color: {fg};
    border: 1px solid {bdr_lt};
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 13px;
}}
QPushButton#ApplyBtn:hover, QPushButton#DiscardBtn:hover {{
    background-color: {sel};
}}
QPushButton#ApplyBtn:disabled, QPushButton#DiscardBtn:disabled {{
    color: {muted};
    background-color: {bg};
    border-color: {bdr};
}}
QPushButton#SaveBtn {{
    background-color: {acc};
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 8px 24px;
    font-size: 13px;
    font-weight: bold;
}}
QPushButton#SaveBtn:hover {{
    opacity: 0.85;
}}
QPushButton#SaveBtn:pressed {{
    opacity: 0.7;
}}
QPushButton#CancelBtn {{
    background-color: transparent;
    color: {sec};
    border: 1px solid {bdr};
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 13px;
}}
QPushButton#CancelBtn:hover {{
    color: {fg};
    border-color: {bdr_lt};
}}

/* Scrollbar */
QScrollBar:vertical {{
    width: 8px;
    background: transparent;
}}
QScrollBar::handle:vertical {{
    background-color: {bdr};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

/* ── Field widget styles ── */

/* Field labels */
.FieldLabel {{
    color: {sec};
    font-size: 12px;
}}

/* Field descriptions */
.FieldDesc {{
    color: {muted};
    font-size: 11px;
    margin-left: 158px;
}}

/* Reset button */
QPushButton#FieldResetBtn {{
    color: {sec};
    background: transparent;
    border: 1px solid {bdr};
    border-radius: 4px;
    font-size: 14px;
    padding: 0px;
}}
QPushButton#FieldResetBtn:hover {{
    color: {fg};
    border-color: {bdr_lt};
}}

/* Text inputs, spin boxes, combo boxes */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox,
QPlainTextEdit, QDateEdit, QTimeEdit, QDateTimeEdit {{
    background-color: {inp};
    color: {fg};
    border: 1px solid {bdr};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 13px;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus, QPlainTextEdit:focus,
QDateEdit:focus, QTimeEdit:focus, QDateTimeEdit:focus {{
    border-color: {acc};
}}
QComboBox::drop-down {{
    border: none;
    padding-right: 8px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid {sec};
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background-color: {inp};
    color: {fg};
    border: 1px solid {bdr};
    selection-background-color: {sel};
}}
QDateEdit::drop-down, QTimeEdit::drop-down, QDateTimeEdit::drop-down {{
    border: none;
    padding-right: 8px;
}}
QCalendarWidget {{
    background-color: {inp};
    color: {fg};
}}

/* Checkboxes */
QCheckBox {{
    color: {fg};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border: 2px solid {bdr};
    border-radius: 4px;
    background-color: {inp};
}}
QCheckBox::indicator:checked {{
    background-color: {acc};
    border-color: {acc};
}}
QCheckBox::indicator:hover {{
    border-color: {bdr_lt};
}}

/* List widgets */
QListWidget {{
    background-color: {inp};
    color: {fg};
    border: 1px solid {bdr};
    border-radius: 6px;
    padding: 4px;
    font-size: 13px;
}}
QListWidget::item {{
    padding: 4px 8px;
    border-radius: 4px;
}}
QListWidget::item:selected {{
    background-color: {sel};
}}
QListWidget::item:hover {{
    background-color: {hover};
}}

/* Generic small buttons in field widgets */
QPushButton.FieldBtn {{
    background-color: {hover};
    color: {fg};
    border: 1px solid {bdr_lt};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 13px;
}}
QPushButton.FieldBtn:hover {{
    background-color: {sel};
}}

/* API key link button */
QPushButton#ApiKeyLink {{
    color: {self.text_link};
    background: transparent;
    border: none;
    font-size: 11px;
    text-decoration: underline;
    padding: 0 4px;
}}
QPushButton#ApiKeyLink:hover {{
    opacity: 0.8;
}}

/* Eye toggle button (show/hide password) */
QPushButton#EyeToggle {{
    color: {sec};
    background: transparent;
    border: none;
    font-size: 15px;
    padding: 0 2px;
    min-width: 24px;
    max-width: 24px;
}}
QPushButton#EyeToggle:hover {{
    color: {fg};
}}

/* Slider */
QSlider::groove:horizontal {{
    height: 6px;
    background: {bdr};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {acc};
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}}
QSlider::sub-page:horizontal {{
    background: {acc};
    border-radius: 3px;
}}
        """
