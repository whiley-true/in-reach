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
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from in_reach.app import notes_settings
from in_reach.ide.theme import Theme
from in_reach.ide.theme_picker import ThemePickerRow

_SYSTEM_PLACEHOLDER_TEXT = "System settings -- coming soon."

_NOTES_FORMAT_LABELS = {notes_settings.FORMAT_TXT: "Text (.txt)", notes_settings.FORMAT_MD: "Markdown (.md)"}


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
        notes_format: str = notes_settings.DEFAULT_NOTES_FORMAT,
        on_notes_format_changed: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.tabs = QTabWidget()
        self.system_tab = _stub_tab(_SYSTEM_PLACEHOLDER_TEXT)
        self.ui_tab = _build_ui_tab(notes_format, on_notes_format_changed)
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


def _build_ui_tab(notes_format: str, on_notes_format_changed: Callable[[str], None] | None) -> QWidget:
    """PROMPT.md: the Documentation section's "Notes" button "launches editor in notes.txt OR
    notes.md (can be set in settings or command palette)" -- this is the "in settings" half; see
    ``MainWindow.build_command_palette_commands`` for the matching "Set Notes Format" palette
    entries."""
    tab = QWidget()
    layout = QVBoxLayout(tab)
    notes_row = QHBoxLayout()
    notes_row.addWidget(QLabel("Notes format"))
    combo = QComboBox()
    for value, label in _NOTES_FORMAT_LABELS.items():
        combo.addItem(label, value)
    combo.setCurrentIndex(combo.findData(notes_format))
    if on_notes_format_changed is not None:
        combo.currentIndexChanged.connect(lambda index: on_notes_format_changed(combo.itemData(index)))
    notes_row.addWidget(combo)
    notes_row.addStretch(1)
    layout.addLayout(notes_row)
    layout.addStretch(1)
    # Exposed the same way theme_tab exposes its own picker -- a test seam, not part of the
    # dialog's own public API.
    tab.notes_format_combo = combo
    return tab


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
