"""The bottom panel: a live "Logs" tab (PROMPT.md: "in the bottom panel please make the first tab
logs ... please make this a fully fledged logs feature and have all actions log here" -- see
:mod:`in_reach.ide.logs_panel`), first, followed by stub tabs (text1, text2, ...) with no
functionality behind them yet.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTabWidget, QWidget

from in_reach.ide import style
from in_reach.ide.logs_panel import LogsPanel

_STUB_TAB_LABELS = ("text2", "text3")


class BottomPanel(QTabWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self.setStyleSheet(style.BOTTOM_TAB_STYLE)
        self.logs_panel = LogsPanel()
        self.addTab(self.logs_panel, "Logs")
        for label in _STUB_TAB_LABELS:
            self.addTab(QWidget(), label)

    def show_logs(self) -> None:
        """"View Logs" (the View menu, PROMPT.md) -- switches straight to the Logs tab."""
        self.setCurrentWidget(self.logs_panel)
