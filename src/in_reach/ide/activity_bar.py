"""The far-left activity bar: ten reorderable icons at the top -- a compile/"Apply" action, a
ReachVariantTool launcher action, and eight sidebar-view toggles (Git, Dashboard, Scripts,
Locations, Testing, Map Files, LLM, Search), exactly one of whose views is ever active, switching
the primary sidebar's content, VSCode-style: clicking the already-active one collapses the sidebar
instead of switching -- then, pinned at the bottom: a flame status indicator (see
:meth:`ActivityBar.set_halo_status`), a help icon (still a no-op), and a settings cog, which opens
the Settings popout (see :class:`~in_reach.ide.settings_dialog.SettingsDialog`; MainWindow owns
actually building/showing it, this bar just emits :attr:`ActivityBar.settings_requested`).

PROMPT.md: "please move the panel ordering so it goes compile, dashboard, then a git symbol
(stubbed empty panel for now (where we will implement a dulwich gui)), then a bookshelf with the
label Scripts (also stubbed for now), then rvt, then locations, then search" -- the top icons live
in a dedicated :class:`_IconStrip` that supports a real mouse-drag reorder
(:class:`~in_reach.ide.tabs._DragTabBar`'s own pattern, adapted to a vertical icon list instead of
a horizontal tab strip) and persists the result to the project's own ``.env``
(``ACTIVITY_BAR_ORDER``), read back on the next launch. A later pass (PROMPT.md: "please move vcs
up by default (so it comes below compile) and above search please add a map icon for 'Map Files'
(stubbed for now)") moved git directly under compile and added the Map Files toggle (also stubbed,
same placeholder-only treatment as Scripts/Locations) just above Search, and a further pass
(PROMPT.md: "above maps icon, please add a stubbed entrance for Testing ... and beneath the map a
stubbed entry for LLM") added Testing/LLM either side of it -- see :data:`_DEFAULT_ORDER`.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QEvent, QMimeData, QObject, QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QDrag, QMouseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QLayout,
    QMenu,
    QSizePolicy,
    QSpacerItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

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

#: Tooltip text for each of the flame status indicator's states -- see
#: :meth:`ActivityBar.set_halo_status`.
_STATUS_TOOLTIPS = {
    icons.STATUS_UNVERIFIED: "Halo install not verified yet -- Verify System Settings from the Welcome tab",
    icons.STATUS_VERIFIED: "Halo: MCC install verified",
    icons.STATUS_RUNNING: "Halo: MCC is running",
}

#: PROMPT.md: "please move the panel ordering so it goes compile, dashboard, then a git symbol
#: ..., then a bookshelf ... Scripts ..., then rvt, then locations, then search" -- the
#: reorderable group's default top-to-bottom order, keyed the same way
#: :data:`_buttons`/:meth:`ActivityBar._handle_click` already key the view-toggle buttons
#: ("explorer" being the Dashboard button's own long-established internal name, see
#: :data:`DEFAULT_VIEW`). PROMPT.md: "move vcs up by default (so it comes below compile) and
#: above search please add a map icon for 'Map Files'" -- git moved directly under compile, and
#: "maps" (Map Files, stubbed) inserted just above search. PROMPT.md: "above maps icon, please add
#: a stubbed entrance for Testing (using a testube) and beneath the map a stubbed entry for LLM
#: (using a Robot)" -- "testing" inserted just above "maps", "llm" just below it.
_DEFAULT_ORDER = (
    "compile",
    "git",
    "explorer",
    "scripts",
    "rvt",
    "locations",
    "testing",
    "maps",
    "llm",
    "search",
)
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


def _effective_height(button: QToolButton) -> int:
    """The height a button actually occupies once laid out -- ``sizeHint()`` alone ignores an
    explicit ``setFixedSize()`` (every real bar button has one, see :func:`_bar_button`), so a
    button clamped to e.g. 44px would otherwise be measured at its unclamped natural hint instead.
    Used by :meth:`_IconStrip._relayout` to decide how many buttons actually fit."""
    height = button.sizeHint().height()
    height = max(height, button.minimumSizeHint().height(), button.minimumHeight())
    max_height = button.maximumHeight()
    if max_height < 16_777_215:  # QWIDGETSIZE_MAX -- Qt's "no explicit maximum" sentinel
        height = min(height, max_height)
    return height or _BUTTON_SIZE


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

    A button can be added ``pinned=True`` (see :meth:`add_button`) -- PROMPT.md: "the compile icon
    should be stuck to the top". A pinned button can never be dragged, and nothing can ever be
    dropped ahead of it -- :meth:`_apply_order` re-sorts pinned keys (in their own existing
    relative order) to the front of every order this strip ever applies, whatever order was
    requested, so a pinned button stays first even across a stale/hand-edited persisted order.

    When the strip is too short to show every button at once, the extras collapse behind a single
    trailing "..." button rather than overlapping (PROMPT.md: "the side panel icons are overlaying
    on each other becoming unreadable ... instead we want ... icons ... collapsed into a ... icon
    which opens a popout window") -- see :meth:`_relayout`/:meth:`_show_overflow_menu`.
    """

    order_changed = pyqtSignal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        # A QVBoxLayout otherwise forces this widget's own minimumSize up to fit every button it
        # currently holds (even hidden ones don't help until *after* that minimum is computed),
        # which would silently override any resize down to less than that and defeat the whole
        # overflow mechanism below -- see _relayout()'s own docstring.
        self._layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._buttons: dict[str, QToolButton] = {}
        self._order: list[str] = []
        self._pinned: set[str] = set()
        self._hidden_keys: list[str] = []
        self._drag_start: QPoint | None = None
        self._drag_key: str | None = None
        self._drag_source: QToolButton | None = None
        self.setAcceptDrops(True)

        # Absorbs any leftover height *within* this widget once every button (and the overflow
        # button, if shown) is laid out -- without it, a QVBoxLayout with no stretchable item
        # spreads its fixed-size children out evenly to fill whatever height this widget has been
        # given (rather than leaving the extra space after the last one), which is exactly what
        # made the icons drift apart once ActivityBar started handing this widget more room than
        # its buttons actually need (see ActivityBar.__init__'s own comment on why *it* must be the
        # sole stretchable item one level up). Re-appended to the end of the layout by
        # _apply_order()/_relayout() below every time they re-add widgets, since QBoxLayout.
        # addWidget() moves an already-present item to the end -- leaving this spacer in place
        # would otherwise get pushed ahead of whatever's re-added next.
        self._trailing_stretch = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        self._layout.addItem(self._trailing_stretch)

        self._overflow_button = QToolButton(self)
        self._overflow_button.setToolTip("More")
        self._overflow_button.setAutoRaise(True)
        self._overflow_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._overflow_button.hide()
        self._overflow_button.clicked.connect(self._show_overflow_menu)
        self.set_overflow_icon(icons.icon("more", color=_ICON_COLOR, size=_ICON_SIZE))

    def add_button(self, key: str, button: QToolButton, *, pinned: bool = False) -> None:
        button.setProperty("_reorder_key", key)
        button.installEventFilter(self)
        self._buttons[key] = button
        self._order.append(key)
        if pinned:
            self._pinned.add(key)
        self._layout.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)
        self._apply_order(self._order)

    def set_overflow_icon(
        self, icon, icon_size: int = _ICON_SIZE, button_size: int = _BUTTON_SIZE
    ) -> None:  # noqa: ANN001 -- QIcon
        """Lets the owner (:class:`ActivityBar`) re-render the "..." button's icon at the current
        zoom scale, the same way it does for every other button -- see
        :meth:`ActivityBar.refresh_icon_scale`."""
        self._overflow_button.setIcon(icon)
        self._overflow_button.setIconSize(QSize(icon_size, icon_size))
        self._overflow_button.setFixedSize(button_size, button_size)
        self._relayout()

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
            key = watched.property("_reorder_key")
            # A pinned button (PROMPT.md: "the compile icon should be stuck to the top") never
            # starts tracking a drag at all -- it still gets `return False` below so a plain click
            # keeps working, it just can never become `self._drag_key`.
            if event.button() == Qt.MouseButton.LeftButton and key not in self._pinned:
                self._drag_start = event.position().toPoint()
                self._drag_key = key
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
                cursor_pos = event.position().toPoint()
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
                # PROMPT.md: "the buttons should drag under the cursor to be more visually
                # appealing" -- without an explicit pixmap/hotspot, QDrag shows no representation
                # of what's being dragged at all (just a plain cursor), so reordering gave no
                # visual feedback about which icon was moving or where. Grabbing the source
                # button's own current appearance and pinning the hotspot to where the cursor
                # already is (in the button's own local coordinates, same frame `cursor_pos` is
                # already in) makes the dragged icon track the cursor exactly, like a real drag.
                drag.setPixmap(source.grab())
                drag.setHotSpot(cursor_pos)
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

    @property
    def hidden_keys(self) -> list[str]:
        """Keys currently collapsed behind the "..." overflow button -- see :meth:`_relayout`."""
        return list(self._hidden_keys)

    def set_order(self, order: list[str]) -> None:
        """Applies a persisted order, dropping any key that no longer names a real button and
        appending (in their existing relative order) any button not mentioned -- a future new
        icon added to the default set, or a stale ``.env`` entry from before one existed, doesn't
        just vanish or crash."""
        known = [key for key in order if key in self._buttons]
        missing = [key for key in self._order if key not in known]
        self._apply_order(known + missing)

    def _apply_order(self, order: list[str]) -> None:
        # Pinned keys (in their own existing relative order) always sort to the front, regardless
        # of what order was requested -- see this class's own docstring.
        if self._pinned:
            order = [key for key in order if key in self._pinned] + [
                key for key in order if key not in self._pinned
            ]
        self._order = order
        for key in self._order:
            # Re-adding a widget already in the layout just moves it to the end -- the standard
            # Qt idiom for reordering a QBoxLayout in place.
            self._layout.addWidget(self._buttons[key], 0, Qt.AlignmentFlag.AlignHCenter)
        self._relayout()

    # -- overflow ("..." popout for icons that don't fit) ---------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: ANN001 -- QResizeEvent
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        """Shows as many buttons (top to bottom, in ``self._order``) as fit in the strip's current
        height, collapsing the rest behind a trailing "..." button -- see this class's own
        docstring. A height of 0 (not laid out/shown yet, e.g. mid-construction) shows everything;
        a real resize corrects that once it happens."""
        order = self._order
        if not order:
            self._hidden_keys = []
            self._overflow_button.hide()
            return

        available = self.height()
        spacing = self._layout.spacing()
        heights = [_effective_height(self._buttons[key]) for key in order]
        overflow_h = _effective_height(self._overflow_button)

        if available <= 0:
            visible_count = len(order)
        else:
            visible_count = len(order)
            while visible_count > 0:
                shown_h = sum(heights[:visible_count]) + spacing * max(visible_count - 1, 0)
                needs_overflow = visible_count < len(order)
                total_h = shown_h + (spacing + overflow_h if needs_overflow else 0)
                if total_h <= available or visible_count <= 1:
                    break
                visible_count -= 1

        visible = order[:visible_count]
        hidden = order[visible_count:]

        for key in visible:
            self._buttons[key].show()
        for key in hidden:
            self._buttons[key].hide()

        self._hidden_keys = hidden
        if hidden:
            self._layout.addWidget(self._overflow_button, 0, Qt.AlignmentFlag.AlignHCenter)
            self._overflow_button.show()
        else:
            self._overflow_button.hide()

        # Must stay the layout's last item -- every addWidget() above (both here and in
        # _apply_order()) moves its target to the end, which would otherwise leave this spacer
        # stranded ahead of whatever just got re-added. removeItem() is a safe no-op if it's
        # already absent (e.g. the very first call, before the constructor's own initial addItem).
        self._layout.removeItem(self._trailing_stretch)
        self._layout.addItem(self._trailing_stretch)

    def _show_overflow_menu(self) -> None:
        if not self._hidden_keys:
            return
        menu = QMenu(self)
        for key in self._hidden_keys:
            button = self._buttons[key]
            action = menu.addAction(button.icon(), button.toolTip() or key)
            action.triggered.connect(button.click)
        menu.exec(self._overflow_button.mapToGlobal(self._overflow_button.rect().bottomLeft()))

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
        if source_key not in self._buttons or source_key not in self._order or source_key in self._pinned:
            return

        # Only currently-visible buttons have a meaningful (non-stale) geometry to target a drop
        # position against -- an overflowed one is hidden, so its last layout position is whatever
        # it was before it collapsed into "...".
        visible = [key for key in self._order if key not in self._hidden_keys]
        drop_y = event.position().toPoint().y()
        target_key: str | None = None
        for key in visible:
            # Skip pinned buttons as possible drop targets -- nothing may ever land ahead of one
            # (a pinned key is always order[0], so matching it here would insert the drag source
            # at index 0, ahead of it).
            if key in self._pinned:
                continue
            if drop_y < self._buttons[key].geometry().center().y():
                target_key = key
                break

        order = [key for key in self._order if key != source_key]
        target_index = order.index(target_key) if target_key is not None else len(order)
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

        # PROMPT.md: "a git symbol (stubbed empty panel for now (where we will implement a dulwich
        # gui))" -- a real sidebar-view toggle (like Explorer/Search), just with a placeholder
        # view behind it (see MainWindow's own GitPanel wiring).
        self.git_button = _bar_button("git", "Git (toggle primary sidebar)", checkable=True, checked=False)
        self.git_button.clicked.connect(lambda: self._handle_click("git"))

        # PROMPT.md: "a bookshelf with the label Scripts (also stubbed for now)".
        self.scripts_button = _bar_button(
            "bookshelf", "Scripts (toggle primary sidebar)", checkable=True, checked=False
        )
        self.scripts_button.clicked.connect(lambda: self._handle_click("scripts"))

        # PROMPT.md: "please also add a side icon of a bookshelf (titled Locations) stub the panel
        # expanded view for now" (later: "for locations please use a compass icon") -- a real
        # sidebar-view toggle (like Explorer/Search), just with a placeholder view behind it (see
        # MainWindow's own LocationsPanel wiring).
        self.locations_button = _bar_button(
            "compass", "Locations (toggle primary sidebar)", checkable=True, checked=False
        )
        self.locations_button.clicked.connect(lambda: self._handle_click("locations"))

        # PROMPT.md: "above maps icon, please add a stubbed entrance for Testing (using a testube)"
        # -- a real sidebar-view toggle (like Explorer/Search), just with a placeholder view behind
        # it (see MainWindow's own TestingPanel wiring), same treatment as Git/Scripts/Locations.
        self.testing_button = _bar_button(
            "testtube", "Testing (toggle primary sidebar)", checkable=True, checked=False
        )
        self.testing_button.clicked.connect(lambda: self._handle_click("testing"))

        # PROMPT.md: "above search please add a map icon for 'Map Files' (stubbed for now)" -- a
        # real sidebar-view toggle (like Explorer/Search), just with a placeholder view behind it
        # (see MainWindow's own MapsPanel wiring), same treatment as Git/Scripts/Locations above.
        self.maps_button = _bar_button(
            "map", "Map Files (toggle primary sidebar)", checkable=True, checked=False
        )
        self.maps_button.clicked.connect(lambda: self._handle_click("maps"))

        # PROMPT.md: "beneath the map a stubbed entry for LLM (using a Robot)" -- a real
        # sidebar-view toggle (like Explorer/Search), just with a placeholder view behind it (see
        # MainWindow's own LlmPanel wiring), same treatment as Git/Scripts/Locations above.
        self.llm_button = _bar_button("robot", "LLM (toggle primary sidebar)", checkable=True, checked=False)
        self.llm_button.clicked.connect(lambda: self._handle_click("llm"))

        self.search_button = _bar_button(
            "search", "Search (toggle primary sidebar)", checkable=True, checked=False
        )
        self.search_button.clicked.connect(lambda: self._handle_click("search"))

        self._buttons = {
            "explorer": self.explorer_button,
            "git": self.git_button,
            "scripts": self.scripts_button,
            "locations": self.locations_button,
            "testing": self.testing_button,
            "maps": self.maps_button,
            "llm": self.llm_button,
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
                    "git": self.git_button,
                    "scripts": self.scripts_button,
                    "locations": self.locations_button,
                    "testing": self.testing_button,
                    "maps": self.maps_button,
                    "llm": self.llm_button,
                    "search": self.search_button,
                }[key],
                # PROMPT.md: "the compile icon should be stuck to the top" -- never draggable,
                # never a drop target's predecessor, always sorted first. See _IconStrip's own
                # docstring.
                pinned=(key == "compile"),
            )
        saved_order = _load_order(self._env_path)
        if saved_order is not None:
            self._icon_strip.set_order(saved_order)
        self._icon_strip.order_changed.connect(lambda order: _save_order(self._env_path, order))
        # Stretch factor 1, not the default 0 -- a stretch of 0 caps the strip at its own
        # sizeHint() forever (which, once any button has gone into the "..." overflow, reflects
        # only the *currently visible* buttons -- a hidden QWidgetItem contributes nothing to a
        # layout's sizeHint()). Without a stretch factor here, the strip could shrink to collapse
        # icons into overflow but could never grow back past that reduced sizeHint even once the
        # window had room again (e.g. re-maximizing after a smaller windowed size).
        #
        # This must be the *only* stretchable item in the layout -- an equally-stretched
        # addStretch(1) here used to split any leftover room 50/50 with it (matching QBoxLayout's
        # standard equal-stretch-factor distribution), so growing the window back only ever handed
        # the strip half of what it needed to re-show everything, leaving icons permanently stuck
        # in "..." even once the window was plenty tall again. A plain (non-stretching) spacing gap
        # doesn't compete for that room, so the strip alone claims 100% of it -- resizeEvent()/
        # _relayout() (below) then uses that to re-show whatever now fits, and once every icon is
        # visible again the strip just keeps growing itself (blank space below its last button)
        # rather than handing the excess to a separate item, which still keeps the status/help/
        # settings trio pinned at the very bottom.
        layout.addWidget(self._icon_strip, 1)

        # PROMPT.md: "a flame icon which can be of different states depending on the status of
        # the players halo install and running detection" -- a pure status indicator (no click
        # behavior of its own), see set_halo_status(). Pinned above Help, per PROMPT.md.
        self._halo_status = icons.STATUS_UNVERIFIED
        self.status_button = QToolButton()
        self.status_button.setIcon(icons.status_icon(self._halo_status, _ICON_COLOR, _ICON_SIZE))
        self.status_button.setIconSize(QSize(_ICON_SIZE, _ICON_SIZE))
        self.status_button.setFixedSize(_BUTTON_SIZE, _BUTTON_SIZE)
        self.status_button.setAutoRaise(True)
        self.set_halo_status(self._halo_status)  # also sets the initial tooltip
        layout.addWidget(self.status_button, 0, Qt.AlignmentFlag.AlignHCenter)

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

    # -- Halo install/running status -----------------------------------------------------------------

    def set_halo_status(self, state: str) -> None:
        """Updates the bottom-pinned flame indicator (PROMPT.md: "a flame icon which can be of
        different states depending on the status of the players halo install and running
        detection") -- :attr:`~in_reach.ide.icons.STATUS_UNVERIFIED`/``STATUS_VERIFIED``/
        ``STATUS_RUNNING``, see :func:`~in_reach.ide.icons.status_icon`'s own docstring for what
        each looks like. MainWindow re-checks and calls this on a timer (PROMPT.md: "it should
        check every .5s") -- this method just applies whatever state it's given.
        """
        self._halo_status = state
        self.status_button.setIcon(icons.status_icon(state, _ICON_COLOR, round(_ICON_SIZE * self._icon_scale)))
        self.status_button.setToolTip(_STATUS_TOOLTIPS.get(state, _STATUS_TOOLTIPS[icons.STATUS_UNVERIFIED]))

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

        self.status_button.setIcon(icons.status_icon(self._halo_status, _ICON_COLOR, icon_size))
        self.status_button.setIconSize(QSize(icon_size, icon_size))
        self.status_button.setFixedSize(button_size, button_size)

        self._icon_strip.set_overflow_icon(
            icons.icon("more", color=_ICON_COLOR, size=icon_size), icon_size, button_size
        )
