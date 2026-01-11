"""Simple dialog for renaming sessions."""

from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)


class RenameDialog(QDialog):
    """Dialog for renaming a chat session."""

    def __init__(self, current_title: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Rename Chat")
        self.setModal(True)
        self.setMinimumWidth(350)

        layout = QVBoxLayout(self)

        # Label
        label = QLabel("Enter new title:")
        layout.addWidget(label)

        # Text input
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("Chat title")
        if current_title:
            self.title_input.setText(current_title)
            self.title_input.selectAll()
        layout.addWidget(self.title_input)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Focus on input
        self.title_input.setFocus()

    def get_title(self) -> str:
        """Get the entered title."""
        return self.title_input.text().strip()
