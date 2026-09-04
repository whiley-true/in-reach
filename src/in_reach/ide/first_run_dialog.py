"""The first-time-run welcome popup: placeholder text, a row of three theme buttons (Light/Dark/
Whiley) that live-apply the chosen theme, and an Exit button that closes the popup.
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from in_reach.ide import theme as theme_module

_PLACEHOLDER_TEXT = (
    "Welcome to in-reach! This is your first time running the IDE.\n\n"
    "Pick a theme below to see it applied live -- you can always change it again later."
)

_THEME_BUTTONS = ("Light", "Dark", "Whiley")


class FirstRunDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        on_theme_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_theme_changed = on_theme_changed
        self.setWindowTitle("Welcome to in-reach")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        label = QLabel(_PLACEHOLDER_TEXT)
        label.setWordWrap(True)
        layout.addWidget(label)

        theme_row = QHBoxLayout()
        theme_row.setSpacing(8)
        for name in _THEME_BUTTONS:
            button = QPushButton(name)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, n=name: self._apply_theme(n))
            theme_row.addWidget(button)
        layout.addLayout(theme_row)

        exit_button = QPushButton("Exit")
        exit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        exit_button.clicked.connect(self.accept)
        layout.addWidget(exit_button, 0, Qt.AlignmentFlag.AlignRight)

    def _apply_theme(self, name: str) -> None:
        app = QApplication.instance()
        if app is not None:
            theme_module.apply_theme(app, name)
        if self._on_theme_changed is not None:
            self._on_theme_changed()
