"""Stub primary-sidebar view behind the activity bar's new bookshelf icon (PROMPT.md: "please also
add a side icon of a bookshelf (titled Locations) stub the panel expanded view for now"). No real
content yet -- same placeholder-only treatment as the top bar's own "text1"/"text2" dropdowns and
the bottom panel's stub tabs.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

_PLACEHOLDER_TEXT = "Locations -- coming soon."


class LocationsPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        label = QLabel(_PLACEHOLDER_TEXT)
        label.setWordWrap(True)
        label.setEnabled(False)
        layout.addWidget(label)
        layout.addStretch(1)
