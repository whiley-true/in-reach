"""Stub primary-sidebar view behind the activity bar's book icon (PROMPT.md: "move documentation to
be its own panel. it should have a symbol of a book ... make it a stub entry that should come
before locations") -- replaces the Dashboard's old Documentation section (see
:mod:`in_reach.ide.explorer`'s own history). No real content yet -- same placeholder-only treatment
as :mod:`in_reach.ide.scripts_panel`.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

_PLACEHOLDER_TEXT = "Documentation -- coming soon."


class DocumentationPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        label = QLabel(_PLACEHOLDER_TEXT)
        label.setWordWrap(True)
        label.setEnabled(False)
        layout.addWidget(label)
        layout.addStretch(1)
