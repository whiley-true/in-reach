"""Stub primary-sidebar view behind the activity bar's sprinting-man icon (PROMPT.md: "please add an
icon under testing for playtest which should be the icon of a sprinting man (please add entry under
view too)"). No real content yet -- same placeholder-only treatment as
:mod:`in_reach.ide.testing_panel`.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

_PLACEHOLDER_TEXT = "Playtest -- coming soon."


class PlaytestPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        label = QLabel(_PLACEHOLDER_TEXT)
        label.setWordWrap(True)
        label.setEnabled(False)
        layout.addWidget(label)
        layout.addStretch(1)
