"""The bottom panel: stub tabs (text1, text2, ...) that can be cycled between, with no terminal or
command-bar functionality behind them.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTabWidget, QWidget

from in_reach.ide import style

_TAB_LABELS = ("text1", "text2", "text3")


class BottomPanel(QTabWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self.setStyleSheet(style.TAB_PANEL_BORDER_STYLE)
        for label in _TAB_LABELS:
            self.addTab(QWidget(), label)
