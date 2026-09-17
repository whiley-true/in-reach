"""Stub primary-sidebar view behind the activity bar's robot icon (PROMPT.md: "beneath the map a
stubbed entry for LLM (using a Robot)"). No real content yet -- same placeholder-only treatment as
:mod:`in_reach.ide.scripts_panel`.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

_PLACEHOLDER_TEXT = "LLM -- coming soon."


class LlmPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        label = QLabel(_PLACEHOLDER_TEXT)
        label.setWordWrap(True)
        label.setEnabled(False)
        layout.addWidget(label)
        layout.addStretch(1)
