"""The bottom panel: a live "Logs" tab (PROMPT.md: "in the bottom panel please make the first tab
logs ... please make this a fully fledged logs feature and have all actions log here" -- see
:mod:`in_reach.ide.logs_panel`), first, then "Problems" (what's wrong with the active script project, each line
clickable -- see :mod:`in_reach.ide.problems_panel`), followed by a stub tab with no functionality behind it yet.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTabWidget, QWidget

from in_reach.ide import style
from in_reach.ide.logs_panel import LogsPanel
from in_reach.ide.problems_panel import ProblemsPanel

_STUB_TAB_LABELS = ("text3",)
_PROBLEMS_LABEL = "Problems"


class BottomPanel(QTabWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self.setStyleSheet(style.BOTTOM_TAB_STYLE)
        self.logs_panel = LogsPanel()
        self.addTab(self.logs_panel, "Logs")
        self.problems_panel = ProblemsPanel()
        self.problems_panel.counts_changed.connect(self._on_problem_counts)
        self.addTab(self.problems_panel, _PROBLEMS_LABEL)
        for label in _STUB_TAB_LABELS:
            self.addTab(QWidget(), label)

    def _on_problem_counts(self, errors: int, warnings: int) -> None:
        """The Problems tab carries how many there are, so they're visible with another tab in front."""
        total = errors + warnings
        self.setTabText(self.indexOf(self.problems_panel), f"{_PROBLEMS_LABEL} ({total})" if total else _PROBLEMS_LABEL)

    def show_logs(self) -> None:
        """"View Logs" (the View menu, PROMPT.md) -- switches straight to the Logs tab."""
        self.setCurrentWidget(self.logs_panel)

    def show_problems(self) -> None:
        """"View Problems" -- switches straight to the Problems tab."""
        self.setCurrentWidget(self.problems_panel)
