"""Stub primary-sidebar view behind the activity bar's git icon (PROMPT.md: "a git symbol
(stubbed empty panel for now (where we will implement a dulwich gui))"). No real content yet --
same placeholder-only treatment as :mod:`in_reach.ide.locations_panel`.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

_PLACEHOLDER_TEXT = "Git -- coming soon."


class GitPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        label = QLabel(_PLACEHOLDER_TEXT)
        label.setWordWrap(True)
        label.setEnabled(False)
        layout.addWidget(label)
        layout.addStretch(1)
