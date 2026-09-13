"""A row of Light/Dark/Whiley toggle buttons that live-apply the chosen theme app-wide -- the one
"click a button, apply the theme, keep exactly one checked" mechanism shared by the first-run
dialog's own theme picker (:mod:`in_reach.ide.first_run_dialog`) and the Settings dialog's Theme
tab (:mod:`in_reach.ide.settings_dialog`), rather than each carrying its own copy of it.
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QWidget

from in_reach.ide import theme as theme_module
from in_reach.ide.theme import Theme

THEME_NAMES = ("Light", "Dark", "Whiley")


class ThemePickerRow(QWidget):
    """A plain horizontal row of theme toggle buttons -- caller supplies layout/labeling around it."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        on_theme_changed: Callable[[Theme], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_theme_changed = on_theme_changed

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.buttons: dict[str, QPushButton] = {}
        for name in THEME_NAMES:
            button = QPushButton(name)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, n=name: self.apply_theme(n))
            layout.addWidget(button)
            self.buttons[name] = button

    def apply_theme(self, name: str) -> None:
        app = QApplication.instance()
        theme = theme_module.apply_theme(app, name) if app is not None else None

        for button_name, button in self.buttons.items():
            button.setChecked(button_name == name)
            # Fusion caches a QSS "render rule" for a widget the first time it's polished, and a
            # bare palette change doesn't invalidate a checked QPushButton's cached rule -- without
            # this, this row could visibly lag a theme switch, or a previously-selected button
            # could stay stuck showing the old theme's colors.
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()

        if theme is not None and self._on_theme_changed is not None:
            self._on_theme_changed(theme)
