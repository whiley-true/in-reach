"""The far-left activity bar: an Explorer icon and a Search icon at the top -- exactly one of
their views is ever active, switching the primary sidebar's content, VSCode-style: clicking the
already-active one collapses the sidebar instead of switching -- a ReachVariantTool launcher icon
below them (a plain action button, not a view -- it never affects which sidebar view is active),
and a settings cog pinned at the bottom (a no-op for now).
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

DEFAULT_VIEW = "explorer"


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

    # Emitted with "explorer" or "search" when a view button switches the sidebar to that view
    # (opening it if it was closed). Emitted with no args when the already-active view's button is
    # clicked again, requesting the sidebar collapse instead.
    view_selected = pyqtSignal(str)
    view_collapsed = pyqtSignal()
    # A plain action, not a view switch -- MainWindow resolves/launches RVT itself.
    launch_rvt_requested = pyqtSignal()

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

        self._active_view: str | None = DEFAULT_VIEW

        # Checked by default -- the primary sidebar starts open on the Explorer view, matching
        # vscode's own default.
        self.explorer_button = _bar_button(
            "explorer", "Explorer (toggle primary sidebar)", checkable=True, checked=True
        )
        self.explorer_button.clicked.connect(lambda: self._handle_click("explorer"))
        layout.addWidget(self.explorer_button, 0, Qt.AlignmentFlag.AlignHCenter)

        self.search_button = _bar_button(
            "search", "Search (toggle primary sidebar)", checkable=True, checked=False
        )
        self.search_button.clicked.connect(lambda: self._handle_click("search"))
        layout.addWidget(self.search_button, 0, Qt.AlignmentFlag.AlignHCenter)

        self._buttons = {"explorer": self.explorer_button, "search": self.search_button}

        layout.addSpacing(8)

        self.rvt_button = QToolButton()
        self.rvt_button.setIcon(icons.rvt_icon())
        self.rvt_button.setIconSize(self.rvt_button.iconSize())
        self.rvt_button.setToolTip("Launch ReachVariantTool")
        self.rvt_button.setFixedSize(_BUTTON_SIZE, _BUTTON_SIZE)
        self.rvt_button.setAutoRaise(True)
        self.rvt_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rvt_button.clicked.connect(self.launch_rvt_requested.emit)
        layout.addWidget(self.rvt_button, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addStretch(1)

        # Settings intentionally does nothing yet -- see PROMPT.md's "for now settings should do
        # nothing".
        self.settings_button = _bar_button("settings", "Settings")
        layout.addWidget(self.settings_button, 0, Qt.AlignmentFlag.AlignHCenter)

    def _handle_click(self, view: str) -> None:
        if self._active_view == view:
            self._active_view = None
            self._sync_buttons()
            self.view_collapsed.emit()
        else:
            self._active_view = view
            self._sync_buttons()
            self.view_selected.emit(view)

    def _sync_buttons(self) -> None:
        for name, button in self._buttons.items():
            button.blockSignals(True)
            button.setChecked(name == self._active_view)
            button.blockSignals(False)

    def set_active_view(self, view: str | None) -> None:
        """Syncs which view button (if any) reads as active without re-emitting a signal --
        called by MainWindow when the sidebar's visibility changes via some other control (the top
        bar's own sidebar toggle)."""
        self._active_view = view
        self._sync_buttons()

    @property
    def active_view(self) -> str | None:
        return self._active_view
