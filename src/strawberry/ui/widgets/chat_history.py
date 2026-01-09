"""Chat history sidebar widget for displaying past sessions."""

from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ChatHistoryItem(QFrame):
    """Individual chat history item."""

    clicked = Signal(str)  # session_id
    delete_requested = Signal(str)  # session_id

    def __init__(
        self,
        session_id: str,
        title: str,
        message_count: int,
        last_activity: datetime,
        theme,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.session_id = session_id
        self._theme = theme
        self._selected = False

        self.setObjectName("chatHistoryItem")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._setup_ui(title, message_count, last_activity)

    def _setup_ui(self, title: str, message_count: int, last_activity: datetime):
        """Set up the item UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        # Title row
        title_row = QHBoxLayout()
        title_label = QLabel(title or "New Chat")
        title_label.setObjectName("chatTitle")
        title_font = QFont()
        title_font.setWeight(QFont.Weight.Medium)
        title_label.setFont(title_font)
        title_label.setWordWrap(True)
        title_row.addWidget(title_label, 1)

        # Delete button (hidden by default)
        self._delete_btn = QPushButton("×")
        self._delete_btn.setObjectName("deleteBtn")
        self._delete_btn.setFixedSize(20, 20)
        self._delete_btn.setVisible(False)
        self._delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.session_id))
        title_row.addWidget(self._delete_btn)

        layout.addLayout(title_row)

        # Meta row
        meta_row = QHBoxLayout()

        # Message count
        count_label = QLabel(f"{message_count} messages")
        count_label.setObjectName("chatMeta")
        meta_row.addWidget(count_label)

        meta_row.addStretch()

        # Time
        time_str = self._format_time(last_activity)
        time_label = QLabel(time_str)
        time_label.setObjectName("chatMeta")
        meta_row.addWidget(time_label)

        layout.addLayout(meta_row)

    def _format_time(self, dt: datetime) -> str:
        """Format datetime for display."""
        now = datetime.utcnow()
        delta = now - dt

        if delta.days == 0:
            return dt.strftime("%I:%M %p")
        elif delta.days == 1:
            return "Yesterday"
        elif delta.days < 7:
            return dt.strftime("%A")
        else:
            return dt.strftime("%b %d")

    def set_selected(self, selected: bool):
        """Set selection state."""
        self._selected = selected
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def enterEvent(self, event):
        """Show delete button on hover."""
        self._delete_btn.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Hide delete button when not hovering."""
        self._delete_btn.setVisible(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        """Handle click."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.session_id)
        super().mousePressEvent(event)


class ChatHistorySidebar(QFrame):
    """Sidebar showing chat history."""

    session_selected = Signal(str)  # session_id
    new_chat_requested = Signal()
    session_deleted = Signal(str)  # session_id

    def __init__(self, theme, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._theme = theme
        self._items: dict[str, ChatHistoryItem] = {}
        self._current_session: Optional[str] = None

        self.setObjectName("chatHistorySidebar")
        self.setFixedWidth(260)
        self._setup_ui()
        self._apply_style()

    def _setup_ui(self):
        """Set up sidebar UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setObjectName("sidebarHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 12, 12, 12)

        title = QLabel("Chat History")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setWeight(QFont.Weight.Bold)
        title.setFont(title_font)
        header_layout.addWidget(title)

        header_layout.addStretch()

        # New chat button
        new_btn = QPushButton("+")
        new_btn.setObjectName("newChatBtn")
        new_btn.setFixedSize(28, 28)
        new_btn.setToolTip("New Chat")
        new_btn.clicked.connect(self.new_chat_requested.emit)
        header_layout.addWidget(new_btn)

        layout.addWidget(header)

        # Sessions list container
        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(8, 8, 8, 8)
        self._list_layout.setSpacing(4)
        self._list_layout.addStretch()

        # Scroll area would be better but keeping simple for now
        layout.addWidget(self._list_container, 1)

        # Empty state
        self._empty_label = QLabel("No chat history yet.\nStart a new chat!")
        self._empty_label.setObjectName("emptyState")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._list_layout.insertWidget(0, self._empty_label)

    def _apply_style(self):
        """Apply theme-based styling."""
        bg = self._theme.bg_secondary
        border = self._theme.border
        text = self._theme.text_primary
        muted = self._theme.text_muted
        accent = self._theme.accent
        hover = self._theme.accent_hover

        self.setStyleSheet(f"""
            #chatHistorySidebar {{
                background-color: {bg};
                border-right: 1px solid {border};
            }}
            #sidebarHeader {{
                background-color: {bg};
                border-bottom: 1px solid {border};
            }}
            #sidebarHeader QLabel {{
                color: {text};
            }}
            #newChatBtn {{
                background-color: {accent};
                color: {self._theme.accent_text};
                border: none;
                border-radius: 4px;
                padding: 0px;
                font-size: 18px;
                font-weight: bold;
            }}
            #newChatBtn:hover {{
                background-color: {hover};
            }}
            #chatHistoryItem {{
                background-color: transparent;
                border-radius: 8px;
                border: 1px solid transparent;
            }}
            #chatHistoryItem:hover {{
                background-color: {self._theme.bg_tertiary};
            }}
            #chatHistoryItem[selected="true"] {{
                background-color: {self._theme.bg_tertiary};
                border: 1px solid {accent};
            }}
            #chatTitle {{
                color: {text};
            }}
            #chatMeta {{
                color: {muted};
                font-size: 11px;
            }}
            #deleteBtn {{
                background-color: transparent;
                color: {muted};
                border: none;
                font-size: 14px;
            }}
            #deleteBtn:hover {{
                color: #ff5555;
            }}
            #emptyState {{
                color: {muted};
            }}
        """)

    def set_sessions(self, sessions: List[dict]):
        """Update the session list.

        Args:
            sessions: List of session dicts with id, title, message_count, last_activity
        """
        # Clear existing items
        for item in self._items.values():
            self._list_layout.removeWidget(item)
            item.deleteLater()
        self._items.clear()

        # Show/hide empty state
        self._empty_label.setVisible(len(sessions) == 0)

        # Add new items
        for i, session in enumerate(sessions):
            # Parse datetime if string
            last_activity = session.get("last_activity")
            if isinstance(last_activity, str):
                last_activity = datetime.fromisoformat(last_activity.replace("Z", "+00:00"))
            elif last_activity is None:
                last_activity = datetime.utcnow()

            item = ChatHistoryItem(
                session_id=session["id"],
                title=session.get("title"),
                message_count=session.get("message_count", 0),
                last_activity=last_activity,
                theme=self._theme,
            )
            item.clicked.connect(self._on_item_clicked)
            item.delete_requested.connect(self._on_delete_requested)

            self._items[session["id"]] = item
            self._list_layout.insertWidget(i, item)

            # Select current session
            if session["id"] == self._current_session:
                item.set_selected(True)

    def select_session(self, session_id: Optional[str]):
        """Select a session by ID."""
        # Deselect previous
        if self._current_session and self._current_session in self._items:
            self._items[self._current_session].set_selected(False)

        self._current_session = session_id

        # Select new
        if session_id and session_id in self._items:
            self._items[session_id].set_selected(True)

    def _on_item_clicked(self, session_id: str):
        """Handle item click."""
        self.select_session(session_id)
        self.session_selected.emit(session_id)

    def _on_delete_requested(self, session_id: str):
        """Handle delete request."""
        self.session_deleted.emit(session_id)

    def update_theme(self, theme):
        """Update the theme."""
        self._theme = theme
        self._apply_style()
        for item in self._items.values():
            item._theme = theme
