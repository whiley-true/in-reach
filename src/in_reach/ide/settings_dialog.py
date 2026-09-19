"""The settings cog's own popout: a modal dialog, centered on screen at half its size, holding
System/UI (both stubbed -- no settings live there yet) and Theme (a live theme picker, the same
one the first-run dialog uses) tabs.
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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from in_reach.ide.theme import Theme
from in_reach.ide.theme_picker import ThemePickerRow

_SYSTEM_PLACEHOLDER_TEXT = "System settings -- coming soon."
_UI_PLACEHOLDER_TEXT = "UI settings -- coming soon."


def _stub_tab(text: str) -> QWidget:
    tab = QWidget()
    layout = QVBoxLayout(tab)
    label = QLabel(text)
    label.setWordWrap(True)
    label.setEnabled(False)
    layout.addWidget(label)
    layout.addStretch(1)
    return tab


class SettingsDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        on_theme_changed: Callable[[Theme], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.tabs = QTabWidget()
        self.system_tab = _stub_tab(_SYSTEM_PLACEHOLDER_TEXT)
        self.ui_tab = _stub_tab(_UI_PLACEHOLDER_TEXT)
        self.theme_tab = _build_theme_tab(on_theme_changed)
        self.tabs.addTab(self.system_tab, "System")
        self.tabs.addTab(self.ui_tab, "UI")
        self.tabs.addTab(self.theme_tab, "Theme")
        layout.addWidget(self.tabs, 1)

        close_button = QPushButton("Close")
        close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        screen = QApplication.primaryScreen()
        if screen is not None:
            # PROMPT.md: "a popout should open in the centre of the screen (1/2 size)".
            avail = screen.availableGeometry()
            self.resize(avail.width() // 2, avail.height() // 2)
            frame = self.frameGeometry()
            frame.moveCenter(avail.center())
            self.move(frame.topLeft())


def _build_theme_tab(on_theme_changed: Callable[[Theme], None] | None) -> QWidget:
    tab = QWidget()
    layout = QVBoxLayout(tab)
    label = QLabel("Theme")
    layout.addWidget(label)
    picker = ThemePickerRow(on_theme_changed=on_theme_changed)
    layout.addWidget(picker)
    layout.addStretch(1)
    # Exposed on the tab itself so callers/tests can reach the picker without needing their own
    # reference threaded through -- same "find it off the widget that owns it" convention as
    # SettingsDialog's own system_tab/ui_tab.
    tab.theme_picker = picker
    return tab
