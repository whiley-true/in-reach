"""The far-left activity bar: a magnifying-glass icon at the top (toggles the primary sidebar) and
a settings cog pinned at the bottom (a no-op for now).
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QToolButton, QVBoxLayout, QWidget

from in_reach.ide import icons
from in_reach.ide.style import PANEL_RADIUS

WIDTH = 48
_BUTTON_SIZE = 40
_ICON_SIZE = 22

# Fixed regardless of the active theme -- matches real vscode, whose own activity bar stays a
# constant dark shade in both its light and dark themes, so icons never need recoloring on a
# theme switch.
_BACKGROUND_COLOR = "#2c2c2c"
_ICON_COLOR = "#cccccc"
_BORDER_COLOR = "#3f3f3f"


def _bar_button(
    icon_name: str, tooltip: str, *, checkable: bool = False, checked: bool = False
) -> QToolButton:
    button = QToolButton()
    button.setIcon(icons.icon(icon_name, color=_ICON_COLOR, size=_ICON_SIZE))
    button.setIconSize(button.iconSize())
    button.setToolTip(tooltip)
    button.setCheckable(checkable)
    button.setChecked(checked)
    button.setFixedSize(_BUTTON_SIZE, _BUTTON_SIZE)
    button.setAutoRaise(True)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


class ActivityBar(QWidget):
    """Fixed-width vertical bar on the far left of the IDE window."""

    search_toggled = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(WIDTH)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # A full rounded/bordered card, matching every other top-level panel -- see
        # in_reach.ide.style's module docstring.
        self.setStyleSheet(
            f"background-color: {_BACKGROUND_COLOR}; border: 1px solid {_BORDER_COLOR};"
            f" border-radius: {PANEL_RADIUS}px;"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(4)

        # Checked by default -- the primary sidebar starts open, and this button's checked state
        # mirrors that (see MainWindow._set_primary_sidebar_visible()).
        self.search_button = _bar_button(
            "search", "Search (toggle primary sidebar)", checkable=True, checked=True
        )
        self.search_button.toggled.connect(self.search_toggled)
        layout.addWidget(self.search_button, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addStretch(1)

        # Settings intentionally does nothing yet -- see PROMPT.md's "for now settings should do
        # nothing".
        self.settings_button = _bar_button("settings", "Settings")
        layout.addWidget(self.settings_button, 0, Qt.AlignmentFlag.AlignHCenter)

    def set_primary_sidebar_open(self, open_: bool) -> None:
        """Syncs the search button's checked state without re-emitting search_toggled."""
        self.search_button.blockSignals(True)
        self.search_button.setChecked(open_)
        self.search_button.blockSignals(False)
