"""The far-left activity bar: five reorderable icons at the top -- a compile/"Apply" action, a
ReachVariantTool launcher action, and three sidebar-view toggles (Dashboard, Locations, Search),
exactly one of whose views is ever active, switching the primary sidebar's content, VSCode-style:
clicking the already-active one collapses the sidebar instead of switching -- then a help icon
(still a no-op) and a settings cog pinned at the bottom, which opens the Settings popout (see
:class:`~in_reach.ide.settings_dialog.SettingsDialog`; MainWindow owns actually building/showing
it, this bar just emits :attr:`ActivityBar.settings_requested`).

PROMPT.md: "please also move this arrow to the top of the icons, then rvt icon, then dashboard,
then locations, then search (please also make them drag re-orderable by the user (should be saved
in .env in .inreach))" -- the five top icons live in a dedicated :class:`_IconStrip` that supports
a real mouse-drag reorder (:class:`~in_reach.ide.tabs._DragTabBar`'s own pattern, adapted to a
vertical icon list instead of a horizontal tab strip) and persists the result to the project's own
``.env`` (``ACTIVITY_BAR_ORDER``), read back on the next launch.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QEvent, QMimeData, QObject, QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QDrag, QMouseEvent
from PyQt6.QtWidgets import QApplication, QToolButton, QVBoxLayout, QWidget

from in_reach.app import env_file
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
#: PROMPT.md: "icon backgrounds are becoming pale when selected in light theme[;] this is
#: undesirable, they should have a grey boarder when selected instead" -- Fusion's own default
#: :checked QToolButton paints a palette(highlight)-based fill, which (unlike this bar's own fixed
#: dark background/icon colors) *does* follow the active theme, reading as a pale, washed-out box
#: under Light specifically. This replaces that fill outright with a plain grey border instead,
#: for every theme, not just Light -- checked should always look the same here.
_CHECKED_BORDER_COLOR = "#808080"

DEFAULT_VIEW = "explorer"

#: PROMPT.md: "move this arrow to the top of the icons, then rvt icon, then dashboard, then
#: locations, then search" -- the reorderable group's default top-to-bottom order, keyed the same
#: way :data:`_buttons`/:meth:`ActivityBar._handle_click` already key the view-toggle buttons
#: ("explorer" being the Dashboard button's own long-established internal name, see
#: :data:`DEFAULT_VIEW`).
_DEFAULT_ORDER = ("compile", "rvt", "explorer", "locations", "search")
ORDER_ENV_KEY = "ACTIVITY_BAR_ORDER"

_REORDER_MIME = "application/x-inreach-activitybar-icon"


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


def _load_order(env_path: Path | None) -> list[str] | None:
    if env_path is None:
        return None
    raw = env_file.get_env_values(env_path).get(ORDER_ENV_KEY, "")
    order = [key.strip() for key in raw.split(",") if key.strip()]
    return order or None


def _save_order(env_path: Path | None, order: list[str]) -> None:
    if env_path is None:
        return
    env_file.update_env_value(env_path, ORDER_ENV_KEY, ",".join(order))


class _IconStrip(QWidget):
    """A vertical run of :class:`QToolButton`\\ s that can be reordered by dragging one onto
    another -- the same "press, then drag once past the OS drag threshold" trigger
    :class:`~in_reach.ide.tabs._DragTabBar` uses for tab reordering, just vertical and carrying a
    plain string key (this widget doesn't care whether that key names a sidebar view or a plain
    action button) instead of a pane id/tab index pair.

    A ``QToolButton`` is itself an interactive widget that consumes its own mouse press/move/
    release events -- unlike ``_DragTabBar``, which *is* the direct recipient of every mouse event
    over the tab strip, this widget's own ``mousePressEvent``/``mouseMoveEvent`` would never
    actually fire for a press that lands on one of its button children (Qt delivers the event
    straight to that child, it never bubbles up), so drag detection is instead done via an event
    filter installed on each button (see :meth:`add_button`/:meth:`eventFilter`) -- watching every
    button's events from here without needing a dedicated draggable-button subclass.
    """

    order_changed = pyqtSignal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self._buttons: dict[str, QToolButton] = {}
        self._order: list[str] = []
        self._drag_start: QPoint | None = None
        self._drag_key: str | None = None
        self._drag_source: QToolButton | None = None
        self.setAcceptDrops(True)

    def add_button(self, key: str, button: QToolButton) -> None:
        button.setProperty("_reorder_key", key)
        button.installEventFilter(self)
        self._buttons[key] = button
        self._order.append(key)
        self._layout.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 -- Qt override
        # getattr, not self._buttons directly: PyQt can re-wrap a still-alive C++ QToolButton (one
        # of this strip's own children, kept alive a little longer than its Python `_IconStrip`
        # owner by Qt's own parent-child ownership during test teardown/deferred deletion) into a
        # *new* Python object without ever calling __init__ again -- one that's missing every
        # instance attribute __init__ would normally have set. Treating that "resurrected but
        # uninitialized" case as "not one of ours" avoids crashing the whole Qt event loop over a
        # widget that's already on its way out.
        buttons = getattr(self, "_buttons", None)
        if not buttons or not isinstance(watched, QToolButton) or watched not in buttons.values():
            return super().eventFilter(watched, event)

        event_type = event.type()
        if event_type == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
            if event.button() == Qt.MouseButton.LeftButton:
                self._drag_start = event.position().toPoint()
                self._drag_key = watched.property("_reorder_key")
                self._drag_source = watched
            return False  # let the button still see the press (so a plain click still works)

        if event_type == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
            if (
                self._drag_key is not None
                and self._drag_start is not None
                and bool(event.buttons() & Qt.MouseButton.LeftButton)
                and (event.position().toPoint() - self._drag_start).manhattanLength()
                >= QApplication.startDragDistance()
            ):
                key = self._drag_key
                source = self._drag_source
                self._drag_start = None
                self._drag_key = None
                self._drag_source = None
                # Cancels the button's own "pressed" visual state -- without this it can be left
                # looking stuck down once the drag below steals the rest of this mouse press.
                source.setDown(False)
                mime = QMimeData()
                mime.setData(_REORDER_MIME, key.encode("utf-8"))
                drag = QDrag(source)
                drag.setMimeData(mime)
                drag.exec(Qt.DropAction.MoveAction)
                return True  # swallow -- don't let the button process this move too
            return False

        if event_type == QEvent.Type.MouseButtonRelease:
            self._drag_start = None
            self._drag_key = None
            self._drag_source = None
            return False

        return super().eventFilter(watched, event)

    @property
    def order(self) -> list[str]:
        return list(self._order)

    def set_order(self, order: list[str]) -> None:
        """Applies a persisted order, dropping any key that no longer names a real button and
        appending (in their existing relative order) any button not mentioned -- a future new
        icon added to the default set, or a stale ``.env`` entry from before one existed, doesn't
        just vanish or crash."""
        known = [key for key in order if key in self._buttons]
        missing = [key for key in self._order if key not in known]
        self._apply_order(known + missing)

    def _apply_order(self, order: list[str]) -> None:
        self._order = order
        for key in self._order:
            # Re-adding a widget already in the layout just moves it to the end -- the standard
            # Qt idiom for reordering a QBoxLayout in place.
            self._layout.addWidget(self._buttons[key], 0, Qt.AlignmentFlag.AlignHCenter)

    # -- drop target (accepting a drag started from eventFilter() above) ----------------------

    def dragEnterEvent(self, event) -> None:  # noqa: ANN001 -- QDragEnterEvent
        if event.mimeData().hasFormat(_REORDER_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: ANN001 -- QDragMoveEvent
        if event.mimeData().hasFormat(_REORDER_MIME):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: ANN001 -- QDropEvent
        mime = event.mimeData()
        if not mime.hasFormat(_REORDER_MIME):
            return
        source_key = bytes(mime.data(_REORDER_MIME)).decode("utf-8")
        if source_key not in self._buttons or source_key not in self._order:
            return

        drop_y = event.position().toPoint().y()
        target_index = len(self._order)
        for index, key in enumerate(self._order):
            if drop_y < self._buttons[key].geometry().center().y():
                target_index = index
                break

        order = [key for key in self._order if key != source_key]
        current_index = self._order.index(source_key)
        if target_index > current_index:
            target_index -= 1
        order.insert(target_index, source_key)

        self._apply_order(order)
        event.acceptProposedAction()
        self.order_changed.emit(self._order)


class ActivityBar(QWidget):
    """Fixed-width vertical bar on the far left of the IDE window."""

    # Emitted with "explorer"/"locations"/"search" when a view button switches the sidebar to
    # that view (opening it if it was closed). Emitted with no args when the already-active view's
    # button is clicked again, requesting the sidebar collapse instead.
    view_selected = pyqtSignal(str)
    view_collapsed = pyqtSignal()
    # A plain action, not a view switch -- MainWindow resolves/launches RVT itself.
    launch_rvt_requested = pyqtSignal()
    # Ditto -- MainWindow owns what "apply" actually does.
    apply_requested = pyqtSignal()
    # Ditto -- MainWindow owns building/showing the settings popout itself.
    settings_requested = pyqtSignal()

    #: Tracked purely so set_rvt_enabled() can re-render the RVT icon at the *current* scale
    #: without needing its own scale argument threaded through every caller.
    _icon_scale = 1.0

    def __init__(self, parent: QWidget | None = None, *, env_path: Path | None = None) -> None:
        super().__init__(parent)
        self._env_path = env_path
        self._rvt_enabled = True
        self._apply_enabled = False
        self.setFixedWidth(WIDTH)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("activityBar")
        # A full rounded/bordered card, matching every other top-level panel -- see
        # in_reach.ide.style's module docstring. PROMPT.md: "the text help background needs to
        # have contrast to the text help colour" -- scoped to #activityBar specifically, not a
        # bare declaration, or every tooltip shown by this bar's own buttons (Dashboard, RVT,
        # Compile, ...) would render with #activityBar's own dark background instead of the
        # theme's actual tooltip colors, regardless of what theme.py's own app-level QToolTip
        # stylesheet says -- see style.TOOLTIP_STYLE's own docstring for the confirmed mechanism.
        self.setStyleSheet(
            f"QWidget#activityBar {{ background-color: {_BACKGROUND_COLOR};"
            f" border: 1px solid {_BORDER_COLOR}; border-radius: {PANEL_RADIUS}px; }}"
            # PROMPT.md: "they should have a grey boarder when selected instead" -- see
            # _CHECKED_BORDER_COLOR's own comment for why this overrides Fusion's default checked
            # fill rather than just leaving it alone.
            f"QToolButton:checked, QToolButton:checked:hover {{ background-color: transparent;"
            f" border: 1px solid {_CHECKED_BORDER_COLOR}; border-radius: 4px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(4)

        self._active_view: str | None = DEFAULT_VIEW

        # PROMPT.md: "please also make it so the tick in the side panel was instead a horizontal
        # arrow (representing compiling) ... please also move this arrow to the top of the
        # icons" -- built first so it lands first in the reorderable strip's default order.
        self.apply_button = _bar_button("apply", "Apply changes")
        self.apply_button.setIcon(icons.apply_icon(_ICON_COLOR, _ICON_SIZE, enabled=False))
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply_requested.emit)

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

        # PROMPT.md: "please also add a side icon of a bookshelf (titled Locations) stub the panel
        # expanded view for now" (later: "for locations please use a compass icon") -- a real
        # sidebar-view toggle (like Explorer/Search), just with a placeholder view behind it (see
        # MainWindow's own LocationsPanel wiring).
        self.locations_button = _bar_button(
            "compass", "Locations (toggle primary sidebar)", checkable=True, checked=False
        )
        self.locations_button.clicked.connect(lambda: self._handle_click("locations"))

        self.search_button = _bar_button(
            "search", "Search (toggle primary sidebar)", checkable=True, checked=False
        )
        self.search_button.clicked.connect(lambda: self._handle_click("search"))

        self._buttons = {
            "explorer": self.explorer_button,
            "locations": self.locations_button,
            "search": self.search_button,
        }

        self._icon_strip = _IconStrip()
        for key in _DEFAULT_ORDER:
            self._icon_strip.add_button(
                key,
                {
                    "compile": self.apply_button,
                    "rvt": self.rvt_button,
                    "explorer": self.explorer_button,
                    "locations": self.locations_button,
                    "search": self.search_button,
                }[key],
            )
        saved_order = _load_order(self._env_path)
        if saved_order is not None:
            self._icon_strip.set_order(saved_order)
        self._icon_strip.order_changed.connect(lambda order: _save_order(self._env_path, order))
        layout.addWidget(self._icon_strip)

        layout.addStretch(1)

        # PROMPT.md: "please then add a help (?) icon above the settings icon" -- stubbed, same
        # "does nothing yet" treatment as settings_button below.
        self.help_button = _bar_button("help", "Help")
        layout.addWidget(self.help_button, 0, Qt.AlignmentFlag.AlignHCenter)

        # Opens the Settings popout (System/UI/Theme tabs) -- MainWindow owns building/showing it.
        self.settings_button = _bar_button("settings", "Settings")
        self.settings_button.clicked.connect(self.settings_requested.emit)
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
        ``MainWindow._refresh_apply_enabled()``. PROMPT.md: "has small green tick ... when there
        is nothing to compile" -- see :func:`~in_reach.ide.icons.apply_icon`'s own docstring for
        the enabled/disabled badge swap this drives."""
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

        for button in (*self._buttons.values(), self.help_button, self.settings_button):
            button.setIcon(icons.icon(button.property("_icon_name"), color=_ICON_COLOR, size=icon_size))
            button.setIconSize(QSize(icon_size, icon_size))
            button.setFixedSize(button_size, button_size)

        self.rvt_button.setIcon(icons.rvt_icon(enabled=self._rvt_enabled))
        self.rvt_button.setIconSize(QSize(icon_size, icon_size))
        self.rvt_button.setFixedSize(button_size, button_size)

        self.apply_button.setIcon(icons.apply_icon(_ICON_COLOR, icon_size, enabled=self._apply_enabled))
        self.apply_button.setIconSize(QSize(icon_size, icon_size))
        self.apply_button.setFixedSize(button_size, button_size)
