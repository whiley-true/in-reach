"""The quick access bar: a VSCode-style floating quick-open overlay, toggled by Ctrl+P (plain
quick-open) or Ctrl+Shift+P (command-palette-style, prefilled with a leading ``>``). Both shortcuts
just snap focus into the same text entry -- per PROMPT.md, nothing is wired up behind it yet, so
the result list stays empty and does nothing when an item is highlighted.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QLineEdit, QListWidget, QVBoxLayout, QWidget

from in_reach.ide import style

_WIDTH = 480
_TOP_MARGIN = 96


class QuickAccessBar(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(style.PANEL_BORDER_STYLE + " background-color: palette(base);")
        self.setFixedWidth(_WIDTH)
        self.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Type to search...")
        layout.addWidget(self.input)

        # Stub result list -- deliberately does nothing when an item is highlighted or activated.
        self.results = QListWidget()
        self.results.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self.results)

    def open(self, *, command_mode: bool = False) -> None:
        """Shows the bar (re-centered over the current parent size) and snaps focus into the text
        entry -- ``command_mode`` prefills the VSCode-style ``>`` command-palette prefix."""
        self.reposition()
        self.show()
        self.raise_()
        self.input.setText(">" if command_mode else "")
        self.input.setFocus()
        self.input.end(False)

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        x = (parent.width() - self.width()) // 2
        self.move(max(x, 0), _TOP_MARGIN)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)
