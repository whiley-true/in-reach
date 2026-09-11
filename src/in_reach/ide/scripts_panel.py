"""Stub primary-sidebar view behind the activity bar's bookshelf icon (PROMPT.md: "a bookshelf
with the label Scripts (also stubbed for now)"). No real content yet -- same placeholder-only
treatment as :mod:`in_reach.ide.locations_panel`.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

_PLACEHOLDER_TEXT = "Scripts -- coming soon."


class ScriptsPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        label = QLabel(_PLACEHOLDER_TEXT)
        label.setWordWrap(True)
        label.setEnabled(False)
        layout.addWidget(label)
        layout.addStretch(1)
