"""VSCode-style bottom status bar. Empty for now -- see PROMPT.md ("it can be empty for now") --
just a themed strip whose background color comes from the active theme's own ``status_bar_color``
rather than the palette, since a status bar's accent color is a deliberate per-theme brand choice
(blue for Light/Dark, red for Whiley), not a semantic QPalette role.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget

_HEIGHT = 22


class StatusBar(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(_HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def set_color(self, color_hex: str) -> None:
        self.setStyleSheet(f"background-color: {color_hex};")
