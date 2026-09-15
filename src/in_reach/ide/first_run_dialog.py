"""The first-time-run welcome popup: placeholder text, a row of three theme toggle buttons (Light/
Dark/Whiley) that live-apply the chosen theme, and an Exit button that closes the popup.
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QShowEvent
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from in_reach.ide.theme import Theme
from in_reach.ide.theme_picker import ThemePickerRow

_PLACEHOLDER_TEXT = (
    "Welcome to in-reach! This is your first time running the IDE.\n\n"
    "Pick a theme below to see it applied live -- you can always change it again later."
)


class FirstRunDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        on_theme_changed: Callable[[Theme], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Welcome to in-reach")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        label = QLabel(_PLACEHOLDER_TEXT)
        label.setWordWrap(True)
        layout.addWidget(label)

        self._theme_picker = ThemePickerRow(on_theme_changed=on_theme_changed)
        layout.addWidget(self._theme_picker)

        exit_button = QPushButton("Exit")
        exit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        exit_button.clicked.connect(self.accept)
        layout.addWidget(exit_button, 0, Qt.AlignmentFlag.AlignRight)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        # BUG (PROMPT.md): centering on QApplication.primaryScreen() unconditionally put this
        # dialog on the primary monitor even when the IDE's own main window lives on a different
        # one -- prefer the parent window's current screen (where the IDE actually is), falling
        # back to the primary screen only when there's no parent to ask (e.g. shown standalone).
        parent = self.parentWidget()
        screen = (parent.window().screen() if parent is not None else None) or QApplication.primaryScreen()
        if screen is not None:
            frame = self.frameGeometry()
            frame.moveCenter(screen.availableGeometry().center())
            self.move(frame.topLeft())

    @property
    def _theme_buttons(self) -> dict[str, QPushButton]:
        """Kept as a passthrough purely so existing callers/tests can keep reaching the theme
        row's own buttons through this dialog directly, without caring that the row itself now
        lives in :class:`~in_reach.ide.theme_picker.ThemePickerRow`."""
        return self._theme_picker.buttons

    def _apply_theme(self, name: str) -> None:
        self._theme_picker.apply_theme(name)
