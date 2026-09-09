"""The far-left activity bar: an Explorer icon and a Search icon at the top -- exactly one of
their views is ever active, switching the primary sidebar's content, VSCode-style: clicking the
already-active one collapses the sidebar instead of switching -- a ReachVariantTool launcher icon
below them (a plain action button, not a view -- it never affects which sidebar view is active),
an "Apply" icon below that (PROMPT.md: compiles a project's hand-edited ``settings/*.json`` +
``script/output.txt`` into a real gametype ``.bin`` -- see
``MainWindow.apply_settings_changes()``), and a settings cog pinned at the bottom (a no-op for
now).
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import QToolButton, QVBoxLayout, QWidget

from in_reach.ide import icons
from in_reach.ide.style import PANEL_RADIUS

# PROMPT.md, across two passes: +15% on the icons alone, then +10% on "the sidebar and its icons"
# together -- 22 -> 25 -> 28 (icons), 40 -> 44 (buttons), 48 -> 53 (the bar's own width). These are
# the 100%-zoom baseline sizes -- see refresh_icon_scale() for how zoom scales them live.
WIDTH = 53
_BUTTON_SIZE = 44
_ICON_SIZE = 28

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
    # Recorded on the button itself (same trick MainWindow's own _TopBar._toolbutton() uses) --
    # refresh_icon_scale() re-renders this icon at a new size on every zoom change, and needs the
    # real icon name to do that, which isn't always the same as this button's own _buttons dict key
    # (the Explorer/Dashboard button's icon is "dashboard", but its view key stays "explorer" --
    # see MainWindow's own internal-vs-user-facing naming note).
    button.setProperty("_icon_name", icon_name)
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
    # Ditto -- MainWindow owns what "apply" actually does.
    apply_requested = pyqtSignal()

    #: Tracked purely so set_rvt_enabled() can re-render the RVT icon at the *current* scale
    #: without needing its own scale argument threaded through every caller.
    _icon_scale = 1.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rvt_enabled = True
        self._apply_enabled = False
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
        # PROMPT.md: "file explorer is renamed to dashboard (and the icon is changed to be a svg
        # of a dashboard)" -- the icon/tooltip only; the "explorer" view key and this button's own
        # Python identifier stay as they are, purely internal implementation detail invisible to
        # the user.
        self.explorer_button = _bar_button(
            "dashboard", "Dashboard (toggle primary sidebar)", checkable=True, checked=True
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

        # A full-color PNG (the real RVT icon, see icons.rvt_icon()'s own docstring), not one of
        # this bar's other monochrome codicon-derived glyphs -- built directly rather than via
        # _bar_button(), which always renders through icons.icon()'s SVG glyph path.
        self.rvt_button = QToolButton()
        self.rvt_button.setIcon(icons.rvt_icon())
        self.rvt_button.setIconSize(QSize(_ICON_SIZE, _ICON_SIZE))
        self.rvt_button.setToolTip("Launch ReachVariantTool")
        self.rvt_button.setFixedSize(_BUTTON_SIZE, _BUTTON_SIZE)
        self.rvt_button.setAutoRaise(True)
        self.rvt_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rvt_button.clicked.connect(self.launch_rvt_requested.emit)
        layout.addWidget(self.rvt_button, 0, Qt.AlignmentFlag.AlignHCenter)

        # PROMPT.md: "below the rvt icon we want another icon for 'Apply'" -- only enabled once
        # there's something in settings/ to push into edit/build (see set_apply_enabled()).
        self.apply_button = _bar_button("apply", "Apply settings changes")
        self.apply_button.setIcon(icons.apply_icon(_ICON_COLOR, _ICON_SIZE, enabled=False))
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply_requested.emit)
        layout.addWidget(self.apply_button, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addStretch(1)

        # Settings intentionally does nothing yet -- see PROMPT.md's "for now settings should do
        # nothing".
        self.settings_button = _bar_button("settings", "Settings")
        layout.addWidget(self.settings_button, 0, Qt.AlignmentFlag.AlignHCenter)

        self.set_rvt_enabled(False)

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

    # -- RVT / Apply enablement ---------------------------------------------------------------------

    def set_rvt_enabled(self, enabled: bool) -> None:
        """PROMPT.md: "rvt should not be launchable if no project is open (the icon should have a
        dash in front of it)" -- disables the button (Qt already dims a disabled QToolButton's icon
        on its own) and swaps in :func:`~in_reach.ide.icons.rvt_icon`'s own "blocked" badge on top
        of that, since this icon's own artwork is already fairly muted/grey and doesn't read as
        clearly disabled from Qt's automatic dimming alone."""
        self._rvt_enabled = enabled
        self.rvt_button.setEnabled(enabled)
        self.rvt_button.setIcon(icons.rvt_icon(enabled=enabled))
        self.rvt_button.setIconSize(QSize(round(_ICON_SIZE * self._icon_scale), round(_ICON_SIZE * self._icon_scale)))

    def set_apply_enabled(self, enabled: bool) -> None:
        """Whether ``settings/`` currently has changes worth applying -- see
        ``MainWindow._refresh_apply_enabled()``. PROMPT.md: "please also use the red no entry icon
        (like you do for rvt) when the apply button can not be pressed" -- same "no entry" badge
        treatment as :meth:`set_rvt_enabled`, for the same reason (Qt's automatic disabled-dimming
        alone doesn't read clearly enough on its own)."""
        self._apply_enabled = enabled
        self.apply_button.setEnabled(enabled)
        self.apply_button.setIcon(icons.apply_icon(_ICON_COLOR, round(_ICON_SIZE * self._icon_scale), enabled=enabled))

    # -- zoom ---------------------------------------------------------------------------------------

    def refresh_icon_scale(self, scale: float = 1.0) -> None:
        """(Re-)sizes the bar itself and every one of its buttons/icons for ``scale`` (PROMPT.md:
        "when zooming in and out the quicklaunch panel and its icons are not resizing") -- the same
        live-rescale MainWindow already does for the top bar's own icons via
        ``refresh_icon_colors()``, just applied to this bar's fixed pixel constants instead.
        """
        self._icon_scale = scale
        button_size = round(_BUTTON_SIZE * scale)
        icon_size = round(_ICON_SIZE * scale)

        self.setFixedWidth(round(WIDTH * scale))

        for button in self._buttons.values():
            button.setIcon(icons.icon(button.property("_icon_name"), color=_ICON_COLOR, size=icon_size))
            button.setIconSize(QSize(icon_size, icon_size))
            button.setFixedSize(button_size, button_size)

        self.rvt_button.setIcon(icons.rvt_icon(enabled=self._rvt_enabled))
        self.rvt_button.setIconSize(QSize(icon_size, icon_size))
        self.rvt_button.setFixedSize(button_size, button_size)

        self.apply_button.setIcon(icons.apply_icon(_ICON_COLOR, icon_size, enabled=self._apply_enabled))
        self.apply_button.setIconSize(QSize(icon_size, icon_size))
        self.apply_button.setFixedSize(button_size, button_size)

        self.settings_button.setIcon(icons.icon("settings", color=_ICON_COLOR, size=icon_size))
        self.settings_button.setIconSize(QSize(icon_size, icon_size))
        self.settings_button.setFixedSize(button_size, button_size)
