"""Theme and styling for the UI."""

from dataclasses import dataclass
from typing import Dict


@dataclass
class Theme:
    """Color theme for the application."""
    name: str
    
    # Window
    bg_primary: str
    bg_secondary: str
    bg_tertiary: str
    
    # Text
    text_primary: str
    text_secondary: str
    text_muted: str
    
    # Accent
    accent: str
    accent_hover: str
    accent_text: str
    
    # Messages
    user_bubble: str
    user_text: str
    ai_bubble: str
    ai_text: str
    
    # Status
    success: str
    warning: str
    error: str
    
    # Borders
    border: str
    border_focus: str


DARK_THEME = Theme(
    name="dark",
    
    # Window - Deep charcoal with subtle blue undertones
    bg_primary="#0d1117",
    bg_secondary="#161b22",
    bg_tertiary="#21262d",
    
    # Text
    text_primary="#e6edf3",
    text_secondary="#8b949e",
    text_muted="#484f58",
    
    # Accent - Strawberry red
    accent="#ff6b6b",
    accent_hover="#ff8585",
    accent_text="#ffffff",
    
    # Messages
    user_bubble="#238636",
    user_text="#ffffff",
    ai_bubble="#30363d",
    ai_text="#e6edf3",
    
    # Status
    success="#3fb950",
    warning="#d29922",
    error="#f85149",
    
    # Borders
    border="#30363d",
    border_focus="#58a6ff",
)


LIGHT_THEME = Theme(
    name="light",
    
    # Window
    bg_primary="#ffffff",
    bg_secondary="#f6f8fa",
    bg_tertiary="#eaeef2",
    
    # Text
    text_primary="#1f2328",
    text_secondary="#656d76",
    text_muted="#8c959f",
    
    # Accent - Strawberry red
    accent="#cf222e",
    accent_hover="#a40e26",
    accent_text="#ffffff",
    
    # Messages
    user_bubble="#dafbe1",
    user_text="#1a7f37",
    ai_bubble="#f6f8fa",
    ai_text="#1f2328",
    
    # Status
    success="#1a7f37",
    warning="#9a6700",
    error="#cf222e",
    
    # Borders
    border="#d0d7de",
    border_focus="#0969da",
)


THEMES: Dict[str, Theme] = {
    "dark": DARK_THEME,
    "light": LIGHT_THEME,
}


def get_stylesheet(theme: Theme) -> str:
    """Generate Qt stylesheet from theme."""
    return f"""
        /* Main Window */
        QMainWindow {{
            background-color: {theme.bg_primary};
        }}
        
        /* Central Widget */
        QWidget {{
            background-color: {theme.bg_primary};
            color: {theme.text_primary};
            font-family: "Segoe UI", "SF Pro Display", "Ubuntu", sans-serif;
            font-size: 14px;
        }}
        
        /* Scroll Area */
        QScrollArea {{
            background-color: {theme.bg_primary};
            border: none;
        }}
        
        QScrollBar:vertical {{
            background-color: {theme.bg_secondary};
            width: 10px;
            border-radius: 5px;
        }}
        
        QScrollBar::handle:vertical {{
            background-color: {theme.bg_tertiary};
            border-radius: 5px;
            min-height: 30px;
        }}
        
        QScrollBar::handle:vertical:hover {{
            background-color: {theme.text_muted};
        }}
        
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        
        /* Text Input */
        QTextEdit, QLineEdit {{
            background-color: {theme.bg_secondary};
            color: {theme.text_primary};
            border: 1px solid {theme.border};
            border-radius: 8px;
            padding: 12px;
            selection-background-color: {theme.accent};
        }}
        
        QTextEdit:focus, QLineEdit:focus {{
            border-color: {theme.border_focus};
        }}
        
        /* Buttons */
        QPushButton {{
            background-color: {theme.accent};
            color: {theme.accent_text};
            border: none;
            border-radius: 8px;
            padding: 10px 20px;
            font-weight: 600;
        }}
        
        QPushButton:hover {{
            background-color: {theme.accent_hover};
        }}
        
        QPushButton:pressed {{
            background-color: {theme.accent};
        }}
        
        QPushButton:disabled {{
            background-color: {theme.bg_tertiary};
            color: {theme.text_muted};
        }}
        
        /* Secondary Button */
        QPushButton[secondary="true"] {{
            background-color: {theme.bg_tertiary};
            color: {theme.text_primary};
        }}
        
        QPushButton[secondary="true"]:hover {{
            background-color: {theme.border};
        }}
        
        /* Labels */
        QLabel {{
            color: {theme.text_primary};
            background-color: transparent;
        }}
        
        QLabel[muted="true"] {{
            color: {theme.text_muted};
        }}
        
        /* Menu */
        QMenu {{
            background-color: {theme.bg_secondary};
            border: 1px solid {theme.border};
            border-radius: 8px;
            padding: 4px;
        }}
        
        QMenu::item {{
            padding: 8px 24px;
            border-radius: 4px;
        }}
        
        QMenu::item:selected {{
            background-color: {theme.bg_tertiary};
        }}
        
        /* Tab Widget */
        QTabWidget::pane {{
            background-color: {theme.bg_secondary};
            border: 1px solid {theme.border};
            border-radius: 8px;
        }}
        
        QTabBar::tab {{
            background-color: {theme.bg_tertiary};
            color: {theme.text_secondary};
            padding: 10px 20px;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
        }}
        
        QTabBar::tab:selected {{
            background-color: {theme.bg_secondary};
            color: {theme.text_primary};
        }}
        
        /* Checkbox & Radio */
        QCheckBox, QRadioButton {{
            color: {theme.text_primary};
            spacing: 8px;
        }}
        
        QCheckBox::indicator, QRadioButton::indicator {{
            width: 18px;
            height: 18px;
            border: 2px solid {theme.border};
            border-radius: 4px;
            background-color: {theme.bg_secondary};
        }}
        
        QCheckBox::indicator:checked {{
            background-color: {theme.accent};
            border-color: {theme.accent};
        }}
        
        QRadioButton::indicator {{
            border-radius: 9px;
        }}
        
        /* ComboBox */
        QComboBox {{
            background-color: {theme.bg_secondary};
            color: {theme.text_primary};
            border: 1px solid {theme.border};
            border-radius: 8px;
            padding: 8px 12px;
        }}
        
        QComboBox:focus {{
            border-color: {theme.border_focus};
        }}
        
        QComboBox::drop-down {{
            border: none;
            width: 24px;
        }}
        
        QComboBox QAbstractItemView {{
            background-color: {theme.bg_secondary};
            border: 1px solid {theme.border};
            selection-background-color: {theme.bg_tertiary};
        }}
        
        /* Splitter */
        QSplitter::handle {{
            background-color: {theme.border};
        }}
        
        /* Status Bar */
        QStatusBar {{
            background-color: {theme.bg_secondary};
            color: {theme.text_secondary};
            border-top: 1px solid {theme.border};
        }}
        
        /* ToolTip */
        QToolTip {{
            background-color: {theme.bg_tertiary};
            color: {theme.text_primary};
            border: 1px solid {theme.border};
            border-radius: 4px;
            padding: 4px 8px;
        }}
    """

