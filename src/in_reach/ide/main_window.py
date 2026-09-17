"""VSCode-shaped main window: a frameless custom top bar (a small mark, dropdown menus,
sidebar/panel toggles, window controls), a fixed activity bar, a toggleable primary sidebar, a
split-capable main panel above a toggleable bottom panel, and a bottom status bar. Since the window
is frameless, edge/corner dragging (to resize) and the maximize/restore button are both
hand-implemented here rather than provided by the OS chrome -- see ``in_reach.ide.window_resize``/
``toggle_maximize()``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QFileSystemWatcher, QPoint, Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QKeySequence, QMouseEvent, QPalette, QShortcut, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from in_reach.app import (
    env_file,
    halo_status,
    indent_settings,
    logging_setup,
    new_project,
    project,
    recent,
    rvt_launcher,
    system_verify,
)
from in_reach.ide import icons, style
from in_reach.ide import indent_state
from in_reach.ide import theme as theme_module
from in_reach.ide import zoom as zoom_module
from in_reach.ide.activity_bar import DEFAULT_VIEW, ActivityBar
from in_reach.ide.bottom_panel import BottomPanel
from in_reach.ide.documentation_panel import DocumentationPanel
from in_reach.ide.editor import TextEditorWidget
from in_reach.ide.explorer import ExplorerPanel
from in_reach.ide.git_panel import GitPanel
from in_reach.ide.llm_panel import LlmPanel
from in_reach.ide.maps_panel import MapsPanel
from in_reach.ide.quick_access import Command, QuickAccessBar
from in_reach.ide.scripts_panel import ScriptsPanel
from in_reach.ide.search_panel import SearchPanel
from in_reach.ide.settings_dialog import SettingsDialog
from in_reach.ide.status_bar import StatusBar
from in_reach.ide.tabs import MainPanelArea
from in_reach.ide.testing_panel import TestingPanel
from in_reach.ide.theme import Theme
from in_reach.ide.window_resize import cursor_for_edges, resize_edges

_logger = logging_setup.get_logger(__name__)

_TOP_BAR_HEIGHT = 36
_ICON_SIZE = 16
_TOPBAR_MARK_SIZE = 22  # PROMPT.md: "increase the taskbar icon size by 10%" -- 16 -> 18 -> 20 -> 22
_WINDOW_BUTTON_WIDTH = 46
#: PROMPT.md: "it should check every .5s" -- how often the activity bar's own flame status
#: indicator re-checks Halo install verification + Halo: MCC running detection.
_HALO_STATUS_POLL_MS = 500
#: PROMPT.md: "make sure file explorer panel expands by default so text is visible without
#: contracting (at the moment we see Personal G..e Variants)" -- 180 let the sidebar (and with it,
#: the "Personal Game/Map Variants" section headers) get squeezed narrow enough to middle-elide.
#: Bumped once to 220 (still not quite enough headroom at DEFAULT_ZOOM's un-reduced 150%, per a
#: later PROMPT.md: "the default file explorer panel [width] still needs to be slightly wider by
#: default") and again here to 240 -- wide enough headroom over the headers' own sizeHint() that a
#: narrow window has to shrink something else before this text does -- and once more to 300
#: (PROMPT.md: "fix the panel icon width so that trigger conditions and actions should always
#: display on the same line") for the Dashboard's Stats box, whose "Triggers: N   Conditions: N
#: Actions: N" line is wider than any section header ever was, bumped once more to 340 when
#: DEFAULT_ZOOM went from 122% to 134% (PROMPT.md: "increase the default ui scale by 10%") widened
#: that same line's own sizeHint() past the old 300 floor, and bumped again to 420 once CI actually
#: ran the width-vs-sizeHint regression guard (see test_ide_smoke.py) on Linux: that same line's
#: sizeHint() there measured 360px against the *same* zoomed point size -- a platform default-font
#: difference (Linux's own default sans-serif renders measurably wider per character than Windows'
#: Segoe UI at an equal point size), not anything zoom-related on its own. 420 leaves real headroom
#: over that 360px measurement rather than just barely clearing it, so a slightly different distro
#: default font doesn't immediately reopen this same regression.
#:
#: PROMPT.md: "this is good but the side panel needs to be resiziable to be much smaller or wider"
#: -- this used to *also* double as the hard minimum-drag floor (see git history), which on any
#: screen under ~2500px wide (i.e. almost every real monitor) collided with the fraction-of-screen
#: max below once that was introduced, flooring both to this exact same number and leaving zero
#: actual drag range at all. Split in two: this constant now only ever sets the sidebar's *initial*
#: width (still tuned so nothing wraps the moment a project first opens), and
#: :data:`_SIDEBAR_MIN_DRAG_WIDTH` below is the real, much smaller, floor a user can actually drag
#: down to -- going narrower than 420 by choice can elide the Stats/section-header text above, same
#: as dragging any real sidebar (VSCode's included) narrow does; that's expected, not the regression
#: this constant was originally tuned against (an unwantedly-narrow *default*).
_SIDEBAR_DEFAULT_WIDTH = 420

#: PROMPT.md: "the side panel needs to be resiziable to be much smaller" -- a flat floor (not
#: fraction-of-screen -- "genuinely narrow" should mean the same thing on a laptop and a 4K
#: monitor), just enough that the splitter/its children never fully degenerate.
_SIDEBAR_MIN_DRAG_WIDTH = 200

#: PROMPT.md: "the side panel needs to be resiziable to be ... wider" -- half the screen's own
#: width (revised from 1/3, then 1/4, then 1/5 -- each of which, floored at the old shared
#: _SIDEBAR_MIN_WIDTH, actually collapsed to zero drag range on most real screens, see
#: _SIDEBAR_DEFAULT_WIDTH's own comment above). Floored at _SIDEBAR_MIN_DRAG_WIDTH purely so an
#: extreme (sub-400px) screen can't still end up with max < min -- on any realistic screen this
#: never actually triggers, unlike the old floor.
_SIDEBAR_MAX_WIDTH_FRACTION = 2

#: File/Edit top bar menu shortcuts (PROMPT.md) -- named here so the menu's own QAction shortcuts
#: and the command palette's "detail" column (see build_command_palette_commands) can't drift
#: apart. "Close Project" has no shortcut of its own convention to follow (PROMPT.md left it as
#: "please fill") -- picked to sit alongside Close Editor/Close Window's own Ctrl+F4/Alt+F4 pattern
#: without colliding with either.
_SHORTCUT_NEW_WINDOW = "Ctrl+Shift+N"
_SHORTCUT_OPEN_FOLDER = "Ctrl+K"
_SHORTCUT_SAVE = "Ctrl+S"
_SHORTCUT_CLOSE_PROJECT = "Ctrl+Shift+F4"
_SHORTCUT_CLOSE_EDITOR = "Ctrl+F4"
_SHORTCUT_CLOSE_WINDOW = "Alt+F4"
_SHORTCUT_UNDO = "Ctrl+Z"
_SHORTCUT_REDO = "Ctrl+Y"
_SHORTCUT_CUT = "Ctrl+X"
_SHORTCUT_COPY = "Ctrl+C"
_SHORTCUT_PASTE = "Ctrl+V"
_SHORTCUT_FIND = "Ctrl+F"
_SHORTCUT_REPLACE = "Ctrl+R"
_SHORTCUT_SELECT_ALL = "Ctrl+A"
_SHORTCUT_COMMAND_PALETTE = "Ctrl+Shift+P"

#: The three settings/ files RVT saving a project's own .bin regenerates on every resync (see
#: :func:`~in_reach.app.rvt.decompile.resync_from_bin`) -- PROMPT.md: "when making changes to a
#: project in rvt, upon save: any open script_settings.json, settings.json, or strings.json
#: without saved changes should immediately update in place[; a]ny of the above with unsaved
#: changes should pop up ... asking whether to confirm overwrite or abort" -- see
#: :meth:`MainWindow._on_watched_bin_changed`.
_RVT_SYNCED_JSON_FILENAMES = ("settings.json", "script_settings.json", "strings.json")

#: The activity bar's own view-toggle buttons are keyed internally as "explorer"/"git"/.../
#: "search" (see activity_bar.py's own note on "explorer" being the Dashboard button's long-
#: established internal name); this is the user-facing name each one's own
#: :class:`_NoProjectSidebarPage` text should read instead.
_VIEW_DISPLAY_NAMES = {
    "explorer": "Dashboard",
    "git": "Git",
    "scripts": "Scripts",
    "documentation": "Documentation",
    "testing": "Testing",
    "maps": "Map Files",
    "llm": "LLM",
    "search": "Search",
}


class _NoProjectSidebarPage(QWidget):
    """What the primary sidebar shows for a view clicked with no project open -- a centered "Open
    a Project to use ..." prompt, rather than that view's own real (otherwise-empty) panel. One
    shared instance serves all three views (see :meth:`MainWindow._on_sidebar_view_selected`);
    :meth:`set_view_label` retargets its text to whichever one was just clicked."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        self._label = QLabel()
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setEnabled(False)  # the theme's own muted/disabled-text shade, not an error
        layout.addStretch(1)
        layout.addWidget(self._label)
        layout.addStretch(1)

    def set_view_label(self, view: str) -> None:
        self._label.setText(f"Open a Project to use {_VIEW_DISPLAY_NAMES.get(view, view)}")


def _add_action(
    menu: QMenu, text: str, slot: Callable[[], None], shortcut: str | None = None
) -> QMenu:
    """``menu.addAction()`` plus an optional shortcut in one call -- every top bar menu action
    below goes through this so a shortcut typed here always shows up as the accelerator text next
    to that same action in the dropdown, rather than the two being set (or missed) separately."""
    action = menu.addAction(text, slot)
    if shortcut:
        action.setShortcut(QKeySequence(shortcut))
    return menu


class _FileMenuButton(QToolButton):
    """The top bar's "File" dropdown (PROMPT.md) -- every action delegates straight to a same-named
    method on ``window``, so this class is purely the menu's own construction/wiring."""

    def __init__(self, window: "MainWindow", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self.setText("File")
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setAutoRaise(True)

        menu = QMenu(self)
        _add_action(menu, "New Window", window.open_new_window, _SHORTCUT_NEW_WINDOW)
        menu.addAction("Load Welcome Tab", window.open_welcome_tab)
        _add_action(menu, "Open Folder...", window.open_folder, _SHORTCUT_OPEN_FOLDER)
        self.open_recent_menu = menu.addMenu("Open Recent")
        self.open_recent_menu.aboutToShow.connect(self._populate_open_recent)
        menu.addSeparator()
        _add_action(menu, "Save", window.save_current, _SHORTCUT_SAVE)
        menu.addAction("Save All", window.save_all)
        menu.addSeparator()
        _add_action(menu, "Close Project", window.close_project, _SHORTCUT_CLOSE_PROJECT)
        _add_action(menu, "Close Editor", window.close_editor, _SHORTCUT_CLOSE_EDITOR)
        _add_action(menu, "Close Window", window.close, _SHORTCUT_CLOSE_WINDOW)
        self.setMenu(menu)

    def _populate_open_recent(self) -> None:
        self.open_recent_menu.clear()
        env_project_dir = project.get_project_dir(self._window.root_dir)
        entries = recent.list_recent(env_project_dir)
        if not entries:
            placeholder = self.open_recent_menu.addAction("No Recent Projects")
            placeholder.setEnabled(False)
            return
        for folder in entries:
            label = new_project.read_project_title(folder)
            self.open_recent_menu.addAction(
                label, lambda _checked=False, f=folder: self._window.open_recent_project(f)
            )


class _EditMenuButton(QToolButton):
    """The top bar's "Edit" dropdown (PROMPT.md) -- Undo/Redo/Cut/Copy/Paste/Find/Replace against
    whichever text editor is active (see ``MainWindow._active_text_editor``)."""

    def __init__(self, window: "MainWindow", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText("Edit")
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setAutoRaise(True)

        menu = QMenu(self)
        _add_action(menu, "Undo", window.edit_undo, _SHORTCUT_UNDO)
        _add_action(menu, "Redo", window.edit_redo, _SHORTCUT_REDO)
        menu.addSeparator()
        _add_action(menu, "Cut", window.edit_cut, _SHORTCUT_CUT)
        _add_action(menu, "Copy", window.edit_copy, _SHORTCUT_COPY)
        _add_action(menu, "Paste", window.edit_paste, _SHORTCUT_PASTE)
        menu.addSeparator()
        # PROMPT.md: "Under edit in the top bar, please add an option for Find with shortcut CTRL
        # + F and Replace with shortcut CTRL + R" -- see find_replace.py's own module docstring for
        # the bar these open.
        _add_action(menu, "Find", window.edit_find, _SHORTCUT_FIND)
        _add_action(menu, "Replace", window.edit_replace, _SHORTCUT_REPLACE)
        self.setMenu(menu)


class _SelectionMenuButton(QToolButton):
    """The top bar's "Selection" dropdown (PROMPT.md: "Under Selection, please add Select All
    (ctrl A), should highlight all of the most recently opened tab")."""

    def __init__(self, window: "MainWindow", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText("Selection")
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setAutoRaise(True)

        menu = QMenu(self)
        _add_action(menu, "Select All", window.select_all, _SHORTCUT_SELECT_ALL)
        self.setMenu(menu)


class _ViewMenuButton(QToolButton):
    """The top bar's "View" dropdown (PROMPT.md: "Under View, please add Command Palette, a sub
    menu for appearance, then options to switch to the appropriate side panel (which should be in
    this order (please re-order default icon order too): compile, dashboard, git, scripts, maps,
    docs, testing, ai, search ... we are removing locations, and rvt ... please add an entry for
    view logs"). Each "switch to panel" entry clicks the matching activity-bar button directly
    (rather than re-implementing view-switching here) -- the exact same code path a real click
    takes, so the activity bar's own checked-button state and the sidebar both stay in sync."""

    def __init__(
        self, window: "MainWindow", quick_access: QuickAccessBar, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setText("View")
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setAutoRaise(True)

        menu = QMenu(self)
        # quick_access is the top bar's own instance, passed in directly rather than read off
        # `window.quick_access` -- MainWindow doesn't set that alias until *after* the top bar
        # (and so this button) finishes constructing, see _TopBar.__init__'s own comment.
        _add_action(menu, "Command Palette", quick_access.open_command_palette, _SHORTCUT_COMMAND_PALETTE)
        menu.addSeparator()

        appearance_menu = menu.addMenu("Appearance")
        theme_menu = appearance_menu.addMenu("Set Theme")
        for name in theme_module.list_themes():
            theme_menu.addAction(name, lambda _checked=False, n=name: window._set_theme(n))
        scale_menu = appearance_menu.addMenu("Set UI Scale")
        scale_menu.addAction("Increase", window._zoom_in)
        scale_menu.addAction("Decrease", window._zoom_out)
        menu.addSeparator()

        # PROMPT.md's own re-ordering, keyed to activity_bar.py's own button attributes -- "docs"/
        # "ai" there are the existing Documentation/LLM entries, not a rename (see activity_bar.py's
        # own module docstring).
        panel_buttons = (
            ("Dashboard", "explorer_button"),
            ("Git", "git_button"),
            ("Scripts", "scripts_button"),
            ("Map Files", "maps_button"),
            ("Testing", "testing_button"),
            ("Documentation", "documentation_button"),
            ("LLM", "llm_button"),
            ("Search", "search_button"),
        )
        for label, attr in panel_buttons:
            menu.addAction(label, lambda _checked=False, a=attr: getattr(window.activity_bar, a).click())
        menu.addSeparator()

        menu.addAction("View Logs", window.view_logs)
        self.setMenu(menu)


class _TopBar(QWidget):
    """The custom title-bar row: a small mark and dropdown menus on the left, sidebar/panel
    toggles and window controls on the right. Dragging empty space moves the (frameless) window;
    double-clicking it toggles maximize, same as a native title bar. Dragging within
    :data:`~in_reach.ide.window_resize.RESIZE_MARGIN` of the window's top edge (or its corners)
    resizes it instead, since the top bar covers the entire top edge and both top corners of the
    frameless window."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self._window = window
        self._drag_offset: QPoint | None = None
        self.setFixedHeight(_TOP_BAR_HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("topBar")
        # A scoped selector, not a bare declaration -- see style.TOOLTIP_STYLE's own docstring for
        # why a bare one here would otherwise quietly break every tooltip this bar's own buttons
        # show (Minimize/Maximize/Close/Toggle Sidebar/Toggle Panel).
        self.setStyleSheet("QWidget#topBar { background-color: palette(window); }")
        self.setMouseTracking(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(4)

        self.mark_label = QLabel()
        self.set_mark_size(_TOPBAR_MARK_SIZE)
        layout.addWidget(self.mark_label)
        layout.addSpacing(4)

        # Built (but not yet laid out -- see the addWidget() call further down, in its actual
        # visual position) before the Selection/View menus, which both need it to already exist:
        # View's own "Command Palette" entry opens straight through it.
        self.quick_access = QuickAccessBar(
            self,
            get_project_folder=lambda: self._window.explorer_panel.current_folder,
            open_file=self._window.open_quick_access_file,
            build_root_commands=self._window.build_command_palette_commands,
            label=self._window.root_dir.name,
        )

        self.file_menu_button = _FileMenuButton(window)
        layout.addWidget(self.file_menu_button)
        self.edit_menu_button = _EditMenuButton(window)
        layout.addWidget(self.edit_menu_button)
        self.selection_menu_button = _SelectionMenuButton(window)
        layout.addWidget(self.selection_menu_button)
        self.view_menu_button = _ViewMenuButton(window, self.quick_access)
        layout.addWidget(self.view_menu_button)
        layout.addStretch(1)

        # Two equal stretches around the pill center it in the gap between the left content
        # (mark/File/Edit/Selection/View) and the right-side toggle/window-control cluster, rather
        # than in the dead center of the whole bar (which would drift off-center against those
        # unequal-width neighbors) -- the standard QBoxLayout "center between two stretches" trick.
        layout.addWidget(self.quick_access)
        layout.addStretch(1)

        self.sidebar_toggle = self._toolbutton(
            "sidebar", "Toggle Primary Sidebar", checkable=True, checked=True
        )
        self.panel_toggle = self._toolbutton("panel", "Toggle Panel", checkable=True, checked=True)
        layout.addWidget(self.sidebar_toggle)
        layout.addWidget(self.panel_toggle)

        layout.addSpacing(8)

        self.minimize_button = self._toolbutton("win_minimize", "Minimize")
        self.maximize_button = self._toolbutton("win_maximize", "Maximize")
        self.close_button = self._toolbutton("win_close", "Close")
        for button in (self.minimize_button, self.maximize_button, self.close_button):
            button.setFixedWidth(_WINDOW_BUTTON_WIDTH)
            layout.addWidget(button)

    def _toolbutton(
        self, icon_name: str, tooltip: str, *, checkable: bool = False, checked: bool = False
    ) -> QToolButton:
        button = QToolButton()
        button.setToolTip(tooltip)
        button.setAutoRaise(True)
        button.setCheckable(checkable)
        button.setChecked(checked)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setProperty("_icon_name", icon_name)
        button.setFixedHeight(_TOP_BAR_HEIGHT)
        return button

    def icon_buttons(self) -> tuple[QToolButton, ...]:
        return (
            self.sidebar_toggle,
            self.panel_toggle,
            self.minimize_button,
            self.maximize_button,
            self.close_button,
        )

    def set_mark_size(self, size: int) -> None:
        """Re-renders the top-left mark's pixmap at ``size`` -- unlike the toolbutton icons below
        (baked fresh on every :meth:`MainWindow.refresh_icon_colors` call anyway, for their color),
        this one is otherwise only ever set once at construction, so a zoom change would otherwise
        leave it stuck at its original pixel size while every other icon in the row rescaled."""
        self.mark_label.setPixmap(icons.topbar_icon().pixmap(size, size))

    def _edges_at(self, pos: QPoint) -> Qt.Edge:
        if self._window.isMaximized():
            return Qt.Edge(0)
        return resize_edges(pos, self.width(), self.height(), top=True, bottom=False)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.childAt(event.position().toPoint()) is None:
            pos = event.position().toPoint()
            edges = self._edges_at(pos)
            window_handle = self._window.windowHandle()
            if edges and window_handle is not None:
                window_handle.startSystemResize(edges)
                return
            self._drag_offset = event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and bool(event.buttons() & Qt.MouseButton.LeftButton):
            if self._window.isMaximized():
                self._window.toggle_maximize()
                self._drag_offset = QPoint(self._window.width() // 2, self.height() // 2)
            self._window.move(event.globalPosition().toPoint() - self._drag_offset)
        elif not bool(event.buttons() & Qt.MouseButton.LeftButton):
            self.setCursor(cursor_for_edges(self._edges_at(event.position().toPoint())))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self.childAt(event.position().toPoint()) is None:
            self._window.toggle_maximize()
        super().mouseDoubleClickEvent(event)


class _ResizableBody(QWidget):
    """Fills the window between the top bar and the status bar. MainWindow's own background is
    never directly hoverable -- the top bar, this widget, and the status bar together tile its
    entire client area -- so left/right edge-resize hover/press detection has to live here rather
    than on MainWindow itself; a MainWindow-level override would simply never fire. The bottom
    edge is deliberately not this widget's to claim: it sits above the status bar, not at the
    window's true bottom, so :class:`~in_reach.ide.status_bar.StatusBar` handles that edge (and
    its own corners) itself instead."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self._window = window
        self.setMouseTracking(True)

    def _edges_at(self, pos) -> Qt.Edge:  # noqa: ANN001 -- QPoint
        if self._window.isMaximized():
            return Qt.Edge(0)
        return resize_edges(pos, self.width(), self.height(), top=False, bottom=False)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.childAt(event.position().toPoint()) is None:
            edges = self._edges_at(event.position().toPoint())
            window_handle = self._window.windowHandle()
            if edges and window_handle is not None:
                window_handle.startSystemResize(edges)
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not bool(event.buttons() & Qt.MouseButton.LeftButton) and self.childAt(event.position().toPoint()) is None:
            edges = self._edges_at(event.position().toPoint())
            self.setCursor(cursor_for_edges(edges)) if edges else self.unsetCursor()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: ANN001 -- QEvent
        # Otherwise a resize cursor set while hovering the edge gutter can stay stuck: a sibling
        # card doesn't set its own cursor, so it would inherit whatever this widget last set.
        self.unsetCursor()
        super().leaveEvent(event)


class MainWindow(QWidget):
    def __init__(
        self,
        root_dir: Path | None = None,
        *,
        initial_project: Path | None = None,
        restore_last_project: bool = True,
    ) -> None:
        """
        Args:
            root_dir: The repo root this window's own ``.in-reach`` project folder lives under.
            initial_project: Opens this exact gametype project folder instead of restoring whatever
                the shared ``.env`` last had open -- used only by :meth:`_open_project_with_popup`'s
                own "Open in New Window" choice (PROMPT.md: "1 per window"), so a project already
                open in *this* window can be handed to a fresh one without disturbing what's
                persisted for ordinary restarts.
            restore_last_project: Whether to fall back to reopening whatever ``PROJECT_DIR_KEY``
                last had open when ``initial_project`` isn't given. ``True`` for the app's own
                normal launch; :meth:`open_new_window` passes ``False`` so "File > New Window"
                starts blank (same working directory, no project auto-loaded) instead of just
                reopening the project already open in the window it was spawned from.
        """
        super().__init__()
        self.root_dir = root_dir or Path.cwd()
        self._initial_project = initial_project
        self._active_sidebar_view = DEFAULT_VIEW
        # Tracks only the has-project/no-project transition (not which project) -- see
        # _sync_project_dependent_views()'s own docstring for why.
        self._had_project = False
        # Qt never parents a top-level window to another -- without holding a reference somewhere,
        # a window opened via File > New Window would be garbage-collected (and vanish) as soon as
        # open_new_window() returns.
        self._child_windows: list[MainWindow] = []
        # PROMPT.md: "if project is closed in ide, if Reach Variant tool is open for that project
        # it should be closed" -- the RVT process launch_rvt() most recently started for each
        # project folder, so _close_rvt_for_project() knows what (if anything) to terminate.
        self._rvt_processes: dict[Path, subprocess.Popen] = {}
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowTitle("in-reach")
        self.setWindowIcon(icons.app_icon())

        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            # PROMPT.md: the frameless window's edges/corners should stay draggable-to-resize down
            # to a minimum of 1/4 of the (screen's normal, non-maximized) size.
            self.setMinimumSize(avail.width() // 4, avail.height() // 4)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.top_bar = _TopBar(self)
        outer.addWidget(self.top_bar)
        self.quick_access = self.top_bar.quick_access

        body = _ResizableBody(self)
        body_layout = QHBoxLayout(body)
        # Every top-level region (activity bar, sidebar, main panel, bottom panel) is its own
        # bordered/rounded card -- this margin/spacing is the window-background gap left around
        # and between them, so the rounding reads as rounded instead of flush against a neighbor.
        # It also happens to be exactly where the bottom/left/right edge-resize grab area lives --
        # see _ResizableBody's own mousePressEvent()/mouseMoveEvent() above.
        body_layout.setContentsMargins(style.PANEL_GAP, style.PANEL_GAP, style.PANEL_GAP, style.PANEL_GAP)
        body_layout.setSpacing(style.PANEL_GAP)
        outer.addWidget(body, 1)

        self.activity_bar = ActivityBar(env_path=project.get_project_dir(self.root_dir) / ".env")
        body_layout.addWidget(self.activity_bar)

        self._side_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._side_splitter.setStyleSheet(style.GAP_SPLITTER_HANDLE_STYLE)
        self._side_splitter.setHandleWidth(style.SIDEBAR_CONTENT_GAP)
        self._side_splitter.setChildrenCollapsible(False)
        # PROMPT.md: "the dragging behaviour is jerky. please fix" -- the default opaque resize
        # relayouts the sidebar's own (potentially expensive -- a QFileSystemModel-backed tree,
        # stats, ...) content on every single mouse-move event during the drag; Qt's own standard
        # remedy is to resize just once, on release, showing a plain drag indicator line for the
        # duration instead (drawn by Qt itself, independent of this handle's own QSS styling).
        self._side_splitter.setOpaqueResize(False)
        body_layout.addWidget(self._side_splitter, 1)

        self.primary_sidebar = self._build_primary_sidebar()
        self._side_splitter.addWidget(self.primary_sidebar)

        self._main_splitter = QSplitter(Qt.Orientation.Vertical)
        self._main_splitter.setStyleSheet(style.GAP_SPLITTER_HANDLE_STYLE)
        self._main_splitter.setHandleWidth(style.PANEL_GAP)
        self._main_splitter.setChildrenCollapsible(False)
        self._side_splitter.addWidget(self._main_splitter)
        self._side_splitter.setStretchFactor(0, 0)
        self._side_splitter.setStretchFactor(1, 1)
        self._side_splitter.setSizes([_SIDEBAR_DEFAULT_WIDTH, 1000])

        self.main_panel = MainPanelArea(
            root_dir=self.root_dir,
            reveal_in_explorer=self._reveal_in_explorer_view,
            on_project_opened=self._on_project_opened,
            on_file_saved=self._on_file_saved,
        )
        self._main_splitter.addWidget(self.main_panel)

        # PROMPT.md: "[generated files] should update when rvt saves" -- watches the active
        # project's own freshly-compiled .bin, the same file launch_rvt() opens RVT against (see
        # _rewatch_project_bin()) and re-syncs settings/ and build/'s *.autogenerated.json snapshot
        # whenever RVT writes over it from outside this process.
        self._bin_watcher = QFileSystemWatcher(self)
        self._bin_watcher.fileChanged.connect(self._on_watched_bin_changed)

        env_project_dir = project.get_project_dir(self.root_dir)
        self.explorer_panel.active_project_changed.connect(self.search_panel.set_project_folder)
        self.explorer_panel.active_project_changed.connect(self.git_panel.set_project)
        self.explorer_panel.active_project_changed.connect(self._rewatch_project_bin)
        self.explorer_panel.active_project_changed.connect(self._on_active_project_changed)
        self.explorer_panel.active_project_changed.connect(self._sync_project_dependent_views)
        self.explorer_panel.active_project_changed.connect(self._persist_active_project)
        self.explorer_panel.project_closed.connect(self._close_rvt_for_project)
        self.git_panel.stamp_requested.connect(self.vcs_stamp)
        self.git_panel.new_branch_requested.connect(self.vcs_new_branch)
        self.git_panel.switch_branch_requested.connect(self.vcs_switch_branch)
        self.git_panel.delete_branch_requested.connect(self.vcs_delete_branch)
        self.git_panel.compare_requested.connect(self.vcs_compare)
        self.git_panel.restore_requested.connect(self.vcs_restore)
        # PROMPT.md: "1 per window" -- initial_project (see __init__'s own docstring) wins over
        # whatever's persisted; otherwise restore the one project PROJECT_DIR_KEY last had open,
        # the same key every gametype-project creation already writes (see
        # in_reach.app.new_project.create_gametype_project).
        if self._initial_project is not None:
            to_open = self._initial_project if self._initial_project.is_dir() else None
        elif restore_last_project:
            already_open = env_file.get_env_values(env_project_dir / ".env").get(new_project.PROJECT_DIR_KEY)
            to_open = Path(already_open) if already_open and Path(already_open).is_dir() else None
        else:
            to_open = None
        if to_open is not None:
            self.explorer_panel.open_project(to_open)
        self.explorer_panel.file_activated.connect(self._on_explorer_file_activated)
        self.explorer_panel.export_requested.connect(self.export_rvt_file)
        self.explorer_panel.view_output_requested.connect(self.view_output_txt)
        self.explorer_panel.launch_rvt_requested.connect(self.launch_rvt)
        self.explorer_panel.open_builtin_folder_requested.connect(self._open_builtin_folder)
        self.search_panel.file_activated.connect(self._on_search_file_activated)

        self.bottom_panel = BottomPanel()
        self._bottom_panel_card = style.wrap_tab_widget(self.bottom_panel)
        self._main_splitter.addWidget(self._bottom_panel_card)
        self._main_splitter.setStretchFactor(0, 1)
        self._main_splitter.setStretchFactor(1, 0)
        self._main_splitter.setSizes([700, 200])

        self.status_bar = StatusBar(self)
        outer.addWidget(self.status_bar)
        # PROMPT.md: "where we presently have the name of the parent directory in the quick access
        # bar, we want to replace with the game file name and in brackets its uuid" -- primed once
        # immediately since any restored tab from the last launch (the `for folder in restored`
        # loop above) already fired active_project_changed before this connection existed.
        self.explorer_panel.active_project_changed.connect(self._update_quick_access_label)
        self._update_quick_access_label(self.explorer_panel.current_folder)
        # Same priming reasoning as the status label just above -- a restored project (or the lack
        # of one) already fired active_project_changed before this method's own connection existed.
        self._sync_project_dependent_views(self.explorer_panel.current_folder)
        # Also needs self.status_bar to already exist -- same reasoning as the status label above.
        self.explorer_panel.active_project_changed.connect(self._refresh_vcs_status)
        self._refresh_vcs_status(self.explorer_panel.current_folder)

        # PROMPT.md (Quick Access Bar work): bottom-right Ln/Col/Spaces segments -- connects to the
        # panel's own re-broadcast signal (MainPanelArea.cursor_info_changed), not one specific
        # pane's, since which pane is active_pane can change as the user moves between panes (see
        # that property's own docstring); _update_status_cursor_info always re-reads active_pane
        # fresh, so this one connection stays correct regardless of which pane fired it.
        indent_env_path = project.get_project_dir(self.root_dir) / ".env"
        indent_state.set_indent(*indent_settings.get_indent(indent_env_path))
        self.main_panel.cursor_info_changed.connect(self._update_status_cursor_info)
        self._update_status_cursor_info()

        self.activity_bar.view_selected.connect(self._on_sidebar_view_selected)
        self.activity_bar.view_collapsed.connect(self._on_sidebar_view_collapsed)
        self.activity_bar.apply_requested.connect(self.apply_settings_changes)
        self.activity_bar.settings_requested.connect(self.open_settings_dialog)
        self.top_bar.sidebar_toggle.toggled.connect(self._on_sidebar_toggle_changed)
        self.top_bar.panel_toggle.toggled.connect(self._bottom_panel_card.setVisible)
        self.top_bar.minimize_button.clicked.connect(self.showMinimized)
        self.top_bar.maximize_button.clicked.connect(self.toggle_maximize)
        self.top_bar.close_button.clicked.connect(self.close)

        self._zoom_in_shortcut = QShortcut(self)
        # Both '+' (Ctrl+Shift+= on a US keyboard) and bare '=' (Ctrl+=, no shift needed) are bound,
        # matching PROMPT.md's "Ctrl++" while still working without the shift key.
        # QKeySequence.StandardKey.ZoomIn/ZoomOut are deliberately not used here -- on this Qt build
        # they resolve to these exact same "Ctrl++"/"Ctrl+-" sequences, and a QShortcut carrying a
        # *duplicate* key sequence in its own key list counts that key press as matching twice, which
        # makes Qt treat it as ambiguous (the activatedAmbiguously signal, not activated) and the
        # shortcut silently never fires -- that's what made Ctrl+- (only ever bound once, so every
        # press was its own duplicate) never work at all.
        self._zoom_in_shortcut.setKeys([QKeySequence("Ctrl++"), QKeySequence("Ctrl+=")])
        self._zoom_in_shortcut.activated.connect(self._zoom_in)

        self._zoom_out_shortcut = QShortcut(self)
        self._zoom_out_shortcut.setKeys([QKeySequence("Ctrl+-")])
        self._zoom_out_shortcut.activated.connect(self._zoom_out)

        # Quick Access Bar (PROMPT.md): Ctrl+P search, Ctrl+Shift+P command palette.
        self._quick_open_shortcut = QShortcut(QKeySequence("Ctrl+P"), self)
        self._quick_open_shortcut.activated.connect(self.quick_access.open_search)
        self._command_palette_shortcut = QShortcut(QKeySequence(_SHORTCUT_COMMAND_PALETTE), self)
        self._command_palette_shortcut.activated.connect(self.quick_access.open_command_palette)

        self.refresh_icon_colors()
        # The activity bar's own buttons are fixed pixel sizes, not derived from app.font() the
        # way most of the rest of the UI is -- sync them to whatever zoom is already live on the
        # QApplication at construction time (app.py applies it before building this window; a
        # fresh QApplication with no zoom ever applied reads back as scale 1.0, matching this bar's
        # own construction-time sizes exactly). PROMPT.md: "when zooming in and out the quicklaunch
        # panel and its icons are not resizing".
        app = QApplication.instance()
        if app is not None:
            self.activity_bar.refresh_icon_scale(zoom_module.current_scale(app))

        # PROMPT.md: "a flame icon which can be of different states depending on the status of
        # the players halo install and running detection ... it should check every .5s" -- polls
        # both halves (verification, a cheap .env read, and MCC-running, a cheap win32 window
        # lookup) on the same timer rather than wiring a signal through the Welcome tab's own
        # verify flow, so the indicator is never more than half a second stale regardless of what
        # changed it (a fresh Verify System Settings run, MCC starting/closing, ...).
        self._refresh_halo_status()
        self._halo_status_timer = QTimer(self)
        self._halo_status_timer.timeout.connect(self._refresh_halo_status)
        self._halo_status_timer.start(_HALO_STATUS_POLL_MS)

    def _refresh_halo_status(self) -> None:
        project_dir = project.get_project_dir(self.root_dir)
        verified = system_verify.verified_keys(project_dir).get(system_verify.HALO_MCC_KEY, False)
        if not verified:
            state = icons.STATUS_UNVERIFIED
        elif halo_status.is_mcc_running():
            state = icons.STATUS_RUNNING
        else:
            state = icons.STATUS_VERIFIED
        self.activity_bar.set_halo_status(state)

    def _build_primary_sidebar(self) -> QWidget:
        sidebar = QWidget()
        screen = QApplication.primaryScreen()
        # PROMPT.md: "the side panel needs to be resiziable to be much smaller or wider" --
        # QSplitter enforces a pane's own setMinimumWidth()/setMaximumWidth() as a hard floor/
        # ceiling on how far the user can drag its handle. The floor is flat (see
        # _SIDEBAR_MIN_DRAG_WIDTH's own comment); the ceiling floors at that same flat minimum
        # purely so an extreme (sub-400px) screen can't leave a self-contradictory min > max for
        # Qt's own constraint solver to pick one of arbitrarily -- on any real screen this never
        # actually triggers, unlike the old shared-with-the-minimum floor it replaces.
        min_width = _SIDEBAR_MIN_DRAG_WIDTH
        if screen is not None:
            available = screen.availableGeometry().width()
            max_width = max(_SIDEBAR_MIN_DRAG_WIDTH, available // _SIDEBAR_MAX_WIDTH_FRACTION)
            sidebar.setMaximumWidth(max_width)
        sidebar.setMinimumWidth(min_width)
        sidebar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sidebar.setObjectName("primarySidebar")
        sidebar.setStyleSheet(style.PANEL_BORDER_STYLE)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)

        self.explorer_panel = ExplorerPanel()
        self.search_panel = SearchPanel()
        self.git_panel = GitPanel()
        self.scripts_panel = ScriptsPanel()
        self.documentation_panel = DocumentationPanel()
        self.testing_panel = TestingPanel()
        self.maps_panel = MapsPanel()
        self.llm_panel = LlmPanel()
        self._sidebar_pages = {
            "explorer": self.explorer_panel,
            "git": self.git_panel,
            "scripts": self.scripts_panel,
            "documentation": self.documentation_panel,
            "testing": self.testing_panel,
            "maps": self.maps_panel,
            "llm": self.llm_panel,
            "search": self.search_panel,
        }
        self._no_project_page = _NoProjectSidebarPage()
        self._sidebar_stack = QStackedWidget()
        for page in self._sidebar_pages.values():
            self._sidebar_stack.addWidget(page)
        self._sidebar_stack.addWidget(self._no_project_page)
        self._sidebar_stack.setCurrentWidget(self._sidebar_pages[DEFAULT_VIEW])
        layout.addWidget(self._sidebar_stack)
        return sidebar

    def _show_sidebar(self, visible: bool) -> None:
        self.primary_sidebar.setVisible(visible)
        self.top_bar.sidebar_toggle.blockSignals(True)
        self.top_bar.sidebar_toggle.setChecked(visible)
        self.top_bar.sidebar_toggle.blockSignals(False)

    def _on_sidebar_view_selected(self, view: str) -> None:
        self._active_sidebar_view = view
        if self.explorer_panel.current_folder is None:
            # "when no project is opened, clicking on dashboard, locations or search a blank
            # sidebar should popout" -- the real panel underneath has nothing but its own "no
            # project opened yet" placeholder to show anyway; this reads the same regardless of
            # which of the three was clicked, rather than that panel's own full (otherwise-empty)
            # chrome around it.
            self._no_project_page.set_view_label(view)
            self._sidebar_stack.setCurrentWidget(self._no_project_page)
        else:
            self._sidebar_stack.setCurrentWidget(self._sidebar_pages[view])
        self._show_sidebar(True)

    def _on_sidebar_view_collapsed(self) -> None:
        self._show_sidebar(False)

    def _on_sidebar_toggle_changed(self, visible: bool) -> None:
        self._show_sidebar(visible)
        self.activity_bar.set_active_view(self._active_sidebar_view if visible else None)

    def _reveal_in_explorer_view(self) -> None:
        """Switches the primary sidebar to the Explorer view and ensures it's open -- "Reveal in
        Explorer View" (a tab's context menu) doesn't yet select the specific file within the tree,
        just gets the tree itself on screen."""
        self._active_sidebar_view = "explorer"
        self._sidebar_stack.setCurrentWidget(self._sidebar_pages["explorer"])
        self._show_sidebar(True)
        self.activity_bar.set_active_view("explorer")

    def _on_project_opened(self, folder: Path) -> None:
        """A project just created/loaded (the Welcome tab's own "New .../Load Project" actions) --
        routed through :meth:`_open_project_with_popup` (PROMPT.md: "1 per window"), same as
        :meth:`open_folder`/:meth:`open_recent_project`."""
        self._open_project_with_popup(folder)

    def _open_project_with_popup(self, folder: Path) -> None:
        """The one entry point every "open/load a project" action in this window funnels through
        (the Welcome tab, File > Open Folder, File > Open Recent) -- PROMPT.md: "we now want it to
        be 1 per window ... opening (or loading) a new project when one is already open should
        trigger a popup: Open in this window, Open in new window, cancel." Opens directly, no
        popup, when nothing's open yet or ``folder`` is already the active project.
        """
        current = self.explorer_panel.current_folder
        if current is None or current == folder:
            self.explorer_panel.open_project(folder)
            return
        choice = self.ask_open_in_new_window(folder)
        if choice == "this_window":
            self.explorer_panel.open_project(folder)
        elif choice == "new_window":
            window = MainWindow(root_dir=self.root_dir, initial_project=folder)
            window.showMaximized()
            self._child_windows.append(window)
        # "cancel" (or anything else) -- leave the currently open project alone.

    def ask_open_in_new_window(self, folder: Path) -> str:
        """Kept as its own method purely as a test seam, same convention as
        :meth:`_confirm_overwrite_rvt_changes`. Returns ``"this_window"``, ``"new_window"``, or
        ``"cancel"``."""
        box = QMessageBox(self)
        box.setWindowTitle("in-reach")
        box.setText(
            f"A project is already open in this window. Open \"{new_project.read_project_title(folder)}\""
            " in this window (replacing it), or in a new window?"
        )
        this_window_button = box.addButton("Open in This Window", QMessageBox.ButtonRole.AcceptRole)
        new_window_button = box.addButton("Open in New Window", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(this_window_button)
        box.exec()
        clicked = box.clickedButton()
        if clicked is this_window_button:
            return "this_window"
        if clicked is new_window_button:
            return "new_window"
        return "cancel"

    def _persist_active_project(self, folder: Path | None) -> None:
        """Persists the single active project so it's restored on the next launch (PROMPT.md: "1
        per window") -- the same ``PROJECT_DIR_KEY`` a gametype project's own creation already
        writes (see :func:`~in_reach.app.new_project.create_gametype_project`)."""
        env_file.update_env_value(
            project.get_project_dir(self.root_dir) / ".env", new_project.PROJECT_DIR_KEY, str(folder) if folder else ""
        )

    def _update_quick_access_label(self, folder: Path | None) -> None:
        """Shows the active project as "<title> (<folder id>)" in the Quick Access pill (PROMPT.md:
        "where we presently have the name of the parent directory in the quick access bar, we want
        to replace with the game file name and in brackets its uuid" -- ``folder.name`` is that
        uuid-named project folder, see :func:`~in_reach.app.new_project.create_gametype_project`),
        or falls back to the workspace's own directory name once no project is open (its original,
        pre-project-open text). Also called from :meth:`_sync_project_title`, since a rename changes
        the title half of that text without the active project (and so without
        :attr:`~in_reach.ide.explorer.ExplorerPanel.active_project_changed`) actually changing."""
        if folder is None:
            self.quick_access.set_label(self.root_dir.name)
            return
        self.quick_access.set_label(f"{new_project.read_project_title(folder)} ({folder.name})")

    def _on_explorer_file_activated(self, path: Path) -> None:
        """Opens a file clicked in any of the Explorer panel's three trees -- into the active
        pane, same as "Open File" from the File menu (and, like that action, switching to the tab
        instead of duplicating it if the file's already open there)."""
        self.main_panel.active_pane.open_file(path)

    def _on_search_file_activated(self, path: Path, line_number: int) -> None:
        """Opens a search result -- into the active pane, jumping straight to the matched line."""
        self.main_panel.active_pane.open_file_at_line(path, line_number)

    # -- Quick Access Bar -------------------------------------------------------------------------

    def open_quick_access_file(self, path: Path) -> None:
        """A file picked from the Quick Access Bar's search mode -- opens into the active pane,
        same as any other "open this file" entry point."""
        self.main_panel.active_pane.open_file(path)

    def build_command_palette_commands(self) -> list[Command]:
        """The root ``>`` palette's own commands: the File and Edit top bar menus' own actions
        (PROMPT.md: "add corresponding command palette entries"), each showing its keyboard
        shortcut as its ``detail``, followed by "Set Theme" and "Set UI Scale", each a two-level
        pick. Rebuilt on every open rather than cached, since none of this is expensive to
        construct and this keeps it all from ever going stale."""
        from in_reach.app import notes_settings

        return [
            Command(label="New Window", action=self.open_new_window, detail=_SHORTCUT_NEW_WINDOW),
            Command(label="Open Folder", action=self.open_folder, detail=_SHORTCUT_OPEN_FOLDER),
            Command(label="Save", action=self.save_current, detail=_SHORTCUT_SAVE),
            Command(label="Close Project", action=self.close_project, detail=_SHORTCUT_CLOSE_PROJECT),
            Command(label="Close Editor", action=self.close_editor, detail=_SHORTCUT_CLOSE_EDITOR),
            Command(label="Close Window", action=self.close, detail=_SHORTCUT_CLOSE_WINDOW),
            Command(label="Undo", action=self.edit_undo, detail=_SHORTCUT_UNDO),
            Command(label="Redo", action=self.edit_redo, detail=_SHORTCUT_REDO),
            Command(label="Cut", action=self.edit_cut, detail=_SHORTCUT_CUT),
            Command(label="Copy", action=self.edit_copy, detail=_SHORTCUT_COPY),
            Command(label="Paste", action=self.edit_paste, detail=_SHORTCUT_PASTE),
            Command(
                label="Set Theme",
                children=[
                    Command(label=name, action=lambda n=name: self._set_theme(n))
                    for name in theme_module.list_themes()
                ],
            ),
            Command(
                label="Set UI Scale",
                children=[
                    Command(label="Increase", action=self._zoom_in),
                    Command(label="Decrease", action=self._zoom_out),
                ],
            ),
            Command(label="Open Notes", action=self.open_notes),
            Command(
                label="Set Notes Format",
                children=[
                    Command(label="Text (.txt)", action=lambda: self._set_notes_format(notes_settings.FORMAT_TXT)),
                    Command(label="Markdown (.md)", action=lambda: self._set_notes_format(notes_settings.FORMAT_MD)),
                ],
            ),
            Command(label="Stamp Release", action=self._vcs_stamp_via_dialog),
            Command(label="New Branch", action=self._vcs_new_branch_via_dialog),
            Command(
                label="Switch Branch",
                children=[
                    Command(label=name, action=lambda n=name: self.vcs_switch_branch(n))
                    for name in self._vcs_branches()
                ],
            ),
            Command(
                label="Delete Branch",
                children=[
                    Command(label=name, action=lambda n=name: self.vcs_delete_branch(n))
                    for name in self._vcs_branches()
                ],
            ),
            Command(
                label="Restore Snapshot",
                children=[
                    Command(
                        label=snapshot.stamp_message if snapshot.is_stamp else snapshot.message,
                        action=lambda sha=snapshot.sha: self.vcs_restore(sha),
                    )
                    for snapshot in self._vcs_history()
                ],
            ),
            Command(
                label="Compare",
                children=[
                    Command(
                        label=label_a,
                        children=[
                            Command(label=label_b, action=lambda a=ref_a, b=ref_b: self.vcs_compare(a, b))
                            for ref_b, label_b in self._vcs_compare_refs()
                            if ref_b != ref_a
                        ],
                    )
                    for ref_a, label_a in self._vcs_compare_refs()
                ],
            ),
        ]

    def _vcs_branches(self) -> list[str]:
        folder = self.explorer_panel.current_folder
        if folder is None:
            return []
        from in_reach.app import vcs

        return vcs.list_branches(folder) if vcs.is_initialized(folder) else []

    def _vcs_history(self) -> list:
        folder = self.explorer_panel.current_folder
        if folder is None:
            return []
        from in_reach.app import vcs

        return vcs.history(folder) if vcs.is_initialized(folder) else []

    def _vcs_compare_refs(self) -> list[tuple[str, str]]:
        """Every ref the ``>`` palette's "Compare" entry can pick from -- every branch (label =
        its own name) plus every stamp on the current branch (label = "Stamp: <message>") -- same
        set the Git panel's own compare combos offer."""
        folder = self.explorer_panel.current_folder
        refs = [(name, name) for name in self._vcs_branches()]
        if folder is not None:
            refs += [
                (snapshot.sha, self._vcs_ref_label(folder, snapshot.sha))
                for snapshot in self._vcs_history()
                if snapshot.is_stamp
            ]
        return refs

    def _vcs_stamp_via_dialog(self) -> None:
        from PyQt6.QtWidgets import QInputDialog

        message, ok = QInputDialog.getText(self, "Stamp Release", "Commit message:")
        if ok and message.strip():
            self.vcs_stamp(message.strip())

    def _vcs_new_branch_via_dialog(self) -> None:
        from PyQt6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "New Branch", "Branch name:")
        if ok and name.strip():
            self.vcs_new_branch(name.strip())

    def _set_theme(self, name: str) -> None:
        app = QApplication.instance()
        if app is None:
            return
        self.on_theme_applied(theme_module.apply_theme(app, name))

    # -- bottom status bar: Ln/Col/Spaces -----------------------------------------------------------

    def _update_status_cursor_info(self) -> None:
        """Refreshes (or hides) the bottom-right Ln/Col/Spaces segments to match the active pane's
        own current tab -- called on every cursor move/selection change and tab switch (see
        ``TabPane.cursor_info_changed``), and once at startup.

        PROMPT.md: only shown "if viewing either a .txt file or .json file" -- every other open tab
        kind (Welcome, a Markdown preview, a ``.mvar``/``.bin`` this app doesn't even open as text)
        clears the segments instead.
        """
        widget = self.main_panel.active_pane.currentWidget()
        if (
            not isinstance(widget, TextEditorWidget)
            or widget.path is None
            or widget.path.suffix.lower() not in (".txt", ".json")
        ):
            self.status_bar.clear_cursor_info()
            return
        cursor = widget.textCursor()
        style, width = indent_state.get_indent()
        self.status_bar.set_cursor_info(
            cursor.blockNumber() + 1,
            cursor.positionInBlock() + 1,
            abs(cursor.selectionEnd() - cursor.selectionStart()),
            style,
            width,
            on_cursor_click=lambda: self._open_goto_line(widget),
            on_spaces_click=self._open_indent_action_list,
        )

    def _open_goto_line(self, editor: TextEditorWidget) -> None:
        """The Ln/Col segment's own click -- opens the Quick Access Bar pre-armed to jump to a
        typed line number live (PROMPT.md: "snap the file to that line number as it is typed")."""

        def _goto(line: int) -> None:
            cursor = editor.textCursor()
            block = editor.document().findBlockByNumber(line - 1)
            cursor.setPosition(block.position())
            editor.setTextCursor(cursor)
            editor.centerCursor()
            # PROMPT.md: "when going to line number, the editor should highlight the selected
            # line (in both the main window and in the side preview)".
            editor.highlight_line(line - 1)

        self.quick_access.open_goto_line(editor.blockCount(), _goto)

    def _open_indent_action_list(self) -> None:
        """The Spaces segment's own click -- the fixed 4-item "Select Action" indentation menu
        (PROMPT.md), reachable only from here, not the root ``>`` palette."""
        self.quick_access.open_action_list(self._build_indent_action_commands(), heading="Select Action")

    def _build_indent_action_commands(self) -> list[Command]:
        return [
            Command(label="Detect Indentation from Content", action=self._detect_active_indentation),
            Command(label="Convert indentation to spaces", action=lambda: self._convert_active_indentation(to_spaces=True)),
            Command(label="Convert indentation to tabs", action=lambda: self._convert_active_indentation(to_spaces=False)),
            Command(label="Trim trailing whitespace", action=self._trim_active_trailing_whitespace),
        ]

    def _indent_env_path(self) -> Path:
        return project.get_project_dir(self.root_dir) / ".env"

    def _detect_active_indentation(self) -> None:
        """"Detect Indentation from Content" -- replaces the old manual "Indent using spaces"/
        "Indent using tabs" commands (PROMPT.md) with VSCode's own auto-detected equivalent (see
        :func:`~in_reach.app.indent_settings.detect_indent`), persisted/applied the same way a
        manual style pick used to be."""
        editor = self._active_text_editor()
        if editor is None:
            return
        current = indent_state.get_indent()
        style, width = indent_settings.detect_indent(editor.toPlainText(), current)
        style, width = indent_settings.set_indent(self._indent_env_path(), style, width)
        indent_state.set_indent(style, width)
        self._update_status_cursor_info()

    def _active_text_editor(self) -> TextEditorWidget | None:
        widget = self.main_panel.active_pane.currentWidget()
        return widget if isinstance(widget, TextEditorWidget) else None

    def _convert_active_indentation(self, *, to_spaces: bool) -> None:
        editor = self._active_text_editor()
        if editor is None:
            return
        _style, width = indent_state.get_indent()
        converter = indent_settings.convert_to_spaces if to_spaces else indent_settings.convert_to_tabs
        self._rewrite_active_lines(editor, lambda text: converter(text, width))

    def _trim_active_trailing_whitespace(self) -> None:
        editor = self._active_text_editor()
        if editor is None:
            return
        self._rewrite_active_lines(editor, indent_settings.trim_trailing_whitespace)

    def _rewrite_active_lines(self, editor: TextEditorWidget, transform: Callable[[str], str]) -> None:
        """Applies a whole-text-in, whole-text-out ``transform`` (one of
        :mod:`in_reach.app.indent_settings`'s own rewrites) to just the current selection's own
        full lines if there is one, otherwise to the entire document -- PROMPT.md: "indent using
        tabs or spaces should apply to selection". Edits through a single ``QTextCursor`` scoped to
        only the affected character range (rather than ``selectAll()`` + ``insertPlainText()``),
        so a selection-scoped rewrite doesn't touch, or move the cursor away from, the rest of the
        document.
        """
        cursor = editor.textCursor()
        if not cursor.hasSelection():
            text = editor.toPlainText()
            transformed = transform(text)
            if transformed != text:
                editor.selectAll()
                editor.insertPlainText(transformed)
            return

        doc = editor.document()
        start_cursor = QTextCursor(doc)
        start_cursor.setPosition(cursor.selectionStart())
        start_cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        end_cursor = QTextCursor(doc)
        end_cursor.setPosition(cursor.selectionEnd())
        end_cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)

        edit_cursor = QTextCursor(doc)
        edit_cursor.setPosition(start_cursor.position())
        edit_cursor.setPosition(end_cursor.position(), QTextCursor.MoveMode.KeepAnchor)
        original = edit_cursor.selectedText().replace(" ", "\n")
        transformed = transform(original)
        if transformed != original:
            edit_cursor.insertText(transformed)

    # -- File menu ------------------------------------------------------------------------------

    def open_welcome_tab(self) -> None:
        """"Load Welcome Tab" (PROMPT.md) -- brings the Welcome tab back into the active pane,
        e.g. after it's been closed."""
        self.main_panel.open_welcome_tab_in(self.main_panel.active_pane)

    def open_new_window(self) -> None:
        """"New Window" -- a fresh, independent MainWindow in the same working directory, starting
        blank (Welcome tab, no project loaded) rather than reopening whatever project is already
        open in this one."""
        _logger.info("opening a new window (root_dir=%s)", self.root_dir)
        window = MainWindow(root_dir=self.root_dir, restore_last_project=False)
        window.showMaximized()
        self._child_windows.append(window)

    def open_folder(self) -> None:
        """"Open Folder" -- the same "adopt this folder as the current gametype project" action as
        the Welcome tab's own "Load Project"."""
        chosen = self.ask_open_folder()
        if chosen:
            self._adopt_project(Path(chosen))

    def ask_open_folder(self) -> str:
        return QFileDialog.getExistingDirectory(self, "Open Folder", str(self.root_dir))

    def ask_export_path(self, default_path: Path) -> str:
        """Kept as its own method purely as a test seam (same reasoning as ``ask_open_folder``) --
        "Export File"'s own standard Save As dialog, offering both a full ``.bin`` and RVT's own
        bare ``.mglo`` as save formats (PROMPT.md: "allowing user to save as .bin or .mglo")."""
        chosen, _selected_filter = QFileDialog.getSaveFileName(
            self, "Export File", str(default_path), "Game Variant (*.bin);;Megalo Script (*.mglo)"
        )
        return chosen

    def open_settings_dialog(self) -> None:
        """The activity bar's settings cog -- opens the Settings popout (System stubbed, UI's own
        Notes format live, Theme live) centered at half the screen's size (see
        :class:`~in_reach.ide.settings_dialog.SettingsDialog`'s own ``showEvent``)."""
        from in_reach.app import notes_settings

        dialog = SettingsDialog(
            self,
            on_theme_changed=self.on_theme_applied,
            notes_format=notes_settings.get_notes_format(self._notes_format_env_path()),
            on_notes_format_changed=self._set_notes_format,
        )
        dialog.exec()

    def open_recent_project(self, folder: Path) -> None:
        self._adopt_project(folder)

    def _adopt_project(self, folder: Path) -> None:
        _logger.info("opening project %s", folder)
        recent.add_recent(project.get_project_dir(self.root_dir), folder)
        self._on_project_opened(folder)

    def save_current(self) -> None:
        _logger.info("saving the active tab")
        self.main_panel.active_pane.save_current()

    def save_all(self) -> None:
        _logger.info("saving all open tabs")
        self.main_panel.save_all()

    def close_project(self) -> None:
        """"Close Project" -- closes the one project open in this window (PROMPT.md: "1 per
        window"). Doesn't touch any files, and doesn't close this window (that's the title bar's
        own close button)."""
        _logger.info("closing project %s", self.explorer_panel.current_folder)
        self.explorer_panel.close_active_project()

    def close_editor(self) -> None:
        _logger.info("closing the active tab")
        self.main_panel.active_pane.close_current()

    # -- Edit menu --------------------------------------------------------------------------------

    def edit_undo(self) -> None:
        editor = self._active_text_editor()
        if editor is not None:
            editor.undo()

    def edit_redo(self) -> None:
        editor = self._active_text_editor()
        if editor is not None:
            editor.redo()

    def edit_cut(self) -> None:
        editor = self._active_text_editor()
        if editor is not None:
            editor.cut()

    def edit_copy(self) -> None:
        editor = self._active_text_editor()
        if editor is not None:
            editor.copy()

    def edit_paste(self) -> None:
        editor = self._active_text_editor()
        if editor is not None:
            editor.paste()

    def edit_find(self) -> None:
        """PROMPT.md: "add an option for Find with shortcut CTRL + F ... it should show a find and
        replace bar (cursored on find or replace depending on selection)" -- opens the active tab's
        own Find/Replace bar (see :meth:`~in_reach.ide.editor.TextEditorWidget.open_find`) focused
        on the Find field."""
        editor = self._active_text_editor()
        if editor is not None:
            editor.open_find(replace=False)

    def edit_replace(self) -> None:
        """"Replace" (Ctrl+R) -- same bar as :meth:`edit_find`, just opened with the Replace row
        shown and focused."""
        editor = self._active_text_editor()
        if editor is not None:
            editor.open_find(replace=True)

    # -- Selection menu -----------------------------------------------------------------------------

    def select_all(self) -> None:
        """"Select All" (Ctrl+A, PROMPT.md) -- highlights all of the active pane's own current tab,
        same "whichever editor is active" targeting as the Edit menu's Undo/Redo/Cut/Copy/Paste."""
        editor = self._active_text_editor()
        if editor is not None:
            editor.selectAll()

    # -- View menu ------------------------------------------------------------------------------

    def view_logs(self) -> None:
        """"View Logs" (the View menu, PROMPT.md) -- opens the bottom panel onto its live Logs tab
        (see :mod:`in_reach.ide.logs_panel`), showing the panel first if it was collapsed (same
        toggle the top bar's own panel_toggle button drives)."""
        self.top_bar.panel_toggle.setChecked(True)
        self.bottom_panel.show_logs()

    def toggle_maximize(self) -> None:
        if self.isMaximized():
            screen = self.screen() or QApplication.primaryScreen()
            self.showNormal()
            if screen is not None:
                # PROMPT.md: un-maximizing should restore to half the normal (screen) size,
                # centered -- not whatever tiny geometry showNormal() would otherwise fall back to
                # (this window's "normal" geometry was never explicitly set before the first
                # showMaximized(), so left to itself showNormal() would restore to an arbitrary
                # default rather than a sensible size).
                avail = screen.availableGeometry()
                self.resize(avail.width() // 2, avail.height() // 2)
                frame = self.frameGeometry()
                frame.moveCenter(avail.center())
                self.move(frame.topLeft())
        else:
            self.showMaximized()
        self.refresh_icon_colors()

    def refresh_icon_colors(self, color: str | None = None) -> None:
        """Re-renders the top bar's icons -- both the toggle/window-control buttons' color and, for
        every icon in the row including the top-left mark, their pixel size against the current
        zoom level.

        ``color`` defaults to the current theme's window-text color, read back from the live
        QPalette. Must be called again after a live theme switch (the first-run dialog's own theme
        buttons) or a zoom change, since :func:`in_reach.ide.icons.icon` bakes a fixed color and
        size into the pixmap rather than tracking either live. Prefer :meth:`on_theme_applied`
        (which passes ``color`` explicitly) over relying on the palette read-back for that case --
        ``QApplication.setPalette()`` only actually updates this widget's own ``self.palette()``
        once the resulting ``PaletteChange`` event is processed on the event loop, which hasn't
        happened yet by the time a theme-switch callback runs synchronously; reading it back here
        right after switching would silently reuse the *previous* theme's color for one click.
        """
        if color is None:
            color = self.palette().color(QPalette.ColorRole.WindowText).name()
        app = QApplication.instance()
        scale = zoom_module.current_scale(app) if app is not None else 1.0
        icon_size = round(_ICON_SIZE * scale)
        for button in self.top_bar.icon_buttons():
            icon_name = button.property("_icon_name")
            if button is self.top_bar.maximize_button:
                icon_name = "win_restore" if self.isMaximized() else "win_maximize"
            button.setIcon(icons.icon(icon_name, color=color, size=icon_size))
        self.top_bar.set_mark_size(round(_TOPBAR_MARK_SIZE * scale))

    def on_theme_applied(self, theme: Theme) -> None:
        """Refreshes every bit of chrome that a live theme switch doesn't drive automatically via
        QPalette alone: the top bar's icon colors and the status bar's accent color.

        Also persists the choice -- same shared-``.env`` mechanism as :mod:`in_reach.ide.zoom`'s
        own ``UI_ZOOM`` -- so it survives a relaunch. Every live theme switch in the app (the
        Settings dialog's Theme tab, the first-run dialog, and the Quick Access Bar's "Set Theme"
        command) already funnels through here, so this is the one place that needs to do it.
        """
        self.status_bar.set_color(theme.status_bar_color)
        self.refresh_icon_colors(theme.palette_colors.get("window_text"))
        env_file.update_env_value(
            project.get_project_dir(self.root_dir) / ".env", theme_module.THEME_KEY, theme.name
        )

    def _zoom_in(self) -> None:
        self._adjust_zoom(zoom_module.ZOOM_STEP)

    def _zoom_out(self) -> None:
        self._adjust_zoom(-zoom_module.ZOOM_STEP)

    def _adjust_zoom(self, delta: float) -> None:
        """Nudges the saved zoom level by ``delta``, applies it app-wide, and persists the result.

        Re-reads the current level from the ``.env`` on every call rather than caching it on
        ``self`` -- it's the same file :meth:`in_reach.ide.welcome.WelcomeTab.refresh` and every
        other zoom-aware piece of the IDE would read, so there's only ever the one source of truth.
        """
        env_path = project.get_project_dir(self.root_dir) / ".env"
        new_zoom = zoom_module.set_zoom(env_path, zoom_module.get_zoom(env_path) + delta)
        app = QApplication.instance()
        if app is not None:
            zoom_module.apply_zoom(app, new_zoom)
        # apply_zoom() only scales the live QFont -- every baked-pixmap icon (the top bar's mark
        # and toggle/window-control buttons) needs telling separately, since a font change alone
        # doesn't touch them.
        self.refresh_icon_colors()
        # Same reasoning as refresh_icon_colors() above -- the Explorer/Search panels' own text
        # scale is a one-time snapshot of app.font(), not a live binding to it.
        self.explorer_panel.refresh_font_scale()
        self.search_panel.refresh_font_scale()
        # Ditto for any already-open settings.json/script_settings.json/strings.json tab's own
        # +10% (PROMPT.md) -- TextEditorWidget.refresh_font_scale()'s own docstring.
        for pane in self.main_panel.panes:
            for index in range(pane.count()):
                widget = pane.widget(index)
                if isinstance(widget, TextEditorWidget):
                    widget.refresh_font_scale()
        # PROMPT.md: "when zooming in and out the quicklaunch panel and its icons are not
        # resizing" -- the activity bar's own buttons are fixed-pixel QToolButtons, same category
        # of "doesn't just fall out of a font change" as the top bar icons refresh_icon_colors()
        # already handles above.
        if app is not None:
            self.activity_bar.refresh_icon_scale(zoom_module.current_scale(app))

    def _run_compile(self, project_dir: Path, folder: Path):
        """Runs the real compile step (:func:`~in_reach.app.apply_settings.apply_settings_changes`)
        with a busy cursor shown for its duration.

        PROMPT.md: "when compiling saved changes we are having to press compile twice" -- this
        compile is a genuinely slow, fully synchronous/blocking native call for anything but a
        trivial script, and every one of its three call sites (this button, Launch RVT, Export RVT
        File) used to leave the button that triggered it fully clickable -- and, for Apply
        specifically, still showing its "changes pending" icon -- for that entire blocking call,
        with no feedback that anything was happening at all. An impatient second click during that
        window either queued a redundant second compile, or (once the first one's own state
        refresh finally landed) just read as "the first click didn't do anything," even though it
        had -- there was never actually a data/logic bug in ``settings_have_unapplied_changes()``
        itself to reproduce. Callers are responsible for disabling their own trigger button before
        calling this and restoring/refreshing it afterward, in both the success and failure case.
        """
        from in_reach.app import apply_settings

        _logger.info("compiling %s", folder)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = apply_settings.apply_settings_changes(project_dir, folder)
        finally:
            QApplication.restoreOverrideCursor()
        _logger.info("compile %s for %s", "succeeded" if result.success else "failed", folder)
        return result

    def launch_rvt(self) -> None:
        """Launches in-reach's own bundled ReachVariantTool -- no setup needed, it always resolves
        to a real executable shipped inside the package itself (see
        :func:`in_reach.app.rvt_launcher.resolve_rvt_exe`) -- against the currently selected
        project's own freshly-*compiled* ``.bin`` (see :func:`~in_reach.app.new_project.
        compiled_variant_path`), if one is open and a compile has produced one (PROMPT.md: "when
        rvt is opened, it opens the project in rvt").

        PROMPT.md: "launching rvt should apply the present settings into the rvt window" -- runs
        the same "Apply"/compile step the activity bar's own Apply button does first, so any
        hand-edited ``settings/`` is baked into ``build/dist/*.bin`` before RVT ever opens (a
        no-op if nothing's changed, see :func:`~in_reach.app.apply_settings.apply_settings_changes`).
        Best-effort, unlike the Apply button's own click handler: a compile failure here is
        swallowed rather than popping a blocking dialog on every RVT launch -- the Apply button
        (and its own explicit failure dialog, PROMPT.md item 8) is the place a user goes to find
        out *why* a compile failed; this is just "don't launch against visibly stale settings when
        it happens to already compile cleanly."

        PROMPT.md: "when clicking into rvt, it seems to be showing blank gametype and description
        not the contents from the saved settings" -- this used to hand RVT
        :func:`~in_reach.app.new_project.source_variant_path` instead, the project's frozen
        original starting point (never touched again after creation), so RVT always opened onto
        whatever that looked like, never anything the user had actually saved since.

        Records the launched process against ``folder`` in :attr:`_rvt_processes` (PROMPT.md: "if
        project is closed in ide, if Reach Variant tool is open for that project it should be
        closed") so :meth:`_close_rvt_for_project` has something to terminate later.

        Refuses to launch at all -- rather than the best-effort "launch against whatever happens
        to already compile cleanly" treatment above -- if any of the active project's own
        settings.json/script_settings.json/strings.json tabs are open with unsaved edits: RVT would
        otherwise open against whatever those files last held *on disk*, silently ignoring changes
        the user can still see sitting unsaved in an open tab. PROMPT.md: that warning offers a
        "Save and Continue" button (see :meth:`_warn_unsaved_settings_before_rvt`) that saves
        exactly those dirty tabs and lets the launch proceed, rather than only ever refusing.
        """
        folder = self.explorer_panel.current_folder
        if folder is not None:
            dirty_names = self.main_panel.dirty_tab_names(self._rvt_synced_json_paths(folder))
            if dirty_names and not self._warn_unsaved_settings_before_rvt(dirty_names, folder):
                return
            # Disabled for the compile's own duration -- see _run_compile()'s own docstring
            # (PROMPT.md: "we are having to press compile twice").
            self.explorer_panel.rvt_button.setEnabled(False)
            try:
                compile_result = self._run_compile(project.get_project_dir(self.root_dir), folder)
            except Exception:  # noqa: BLE001 -- native/pydantic code can raise almost anything
                _logger.exception("best-effort compile before RVT launch failed for %s", folder)
                compile_result = None
            finally:
                self.explorer_panel.rvt_button.setEnabled(True)  # folder is not None in this branch
            if compile_result is not None and not compile_result.success:
                # Still best-effort/non-blocking by design (see this method's own docstring) --
                # just logged, not a dialog on every launch -- but this needs at least a trace
                # somewhere: a script that fails to recompile (a very real risk for anything but a
                # trivial script -- the decompile->recompile round trip isn't guaranteed lossless)
                # used to leave build/dist/*.bin silently unwritten with no record of why anywhere,
                # not even in the log, since only a *raised* exception was ever logged above.
                _logger.warning(
                    "best-effort compile before RVT launch did not succeed for %s: %s",
                    folder,
                    compile_result.failure or "Megalo compile failed",
                )
            self._refresh_apply_enabled(folder)
            # A compile above may have just created build/dist/*.bin for the very first time (or
            # overwritten it via a delete-then-recreate save, which silently drops an already-
            # watched path -- see _on_watched_bin_changed()'s own tail) -- re-point the watcher at
            # it either way, so a subsequent RVT save over *this exact file* (the one RVT is about
            # to be opened against, below) is actually noticed.
            self._rewatch_project_bin(folder)
        try:
            process = rvt_launcher.launch_rvt(self._rvt_launch_target(folder))
        except OSError as exc:
            _logger.error("couldn't launch ReachVariantTool: %s", exc)
            QMessageBox.critical(self, "in-reach", f"Couldn't launch ReachVariantTool:\n{exc}")
            return
        _logger.info("launched ReachVariantTool (pid=%s, folder=%s)", getattr(process, "pid", None), folder)
        if folder is not None:
            self._rvt_processes[folder] = process

    def _rvt_synced_json_paths(self, folder: Path) -> list[Path]:
        """``folder``'s own settings.json/script_settings.json/strings.json paths -- the three
        files an RVT resync/launch reads or overwrites (see :data:`_RVT_SYNCED_JSON_FILENAMES`)."""
        settings_dir = folder / new_project.SETTINGS_DIRNAME
        return [settings_dir / name for name in _RVT_SYNCED_JSON_FILENAMES]

    def _warn_unsaved_settings_before_rvt(self, dirty_names: list[str], folder: Path) -> bool:
        """"RVT should not be openable if a user has unsaved changes to any of the settings jsons"
        -- kept as its own method purely as a test seam, same reasoning as
        :meth:`_confirm_overwrite_rvt_changes`. PROMPT.md: "please update to include a Save and
        Continue" -- saves exactly ``folder``'s own dirty settings/script_settings/strings.json
        tabs (not any other unrelated dirty tab) rather than only ever refusing to launch.

        Returns:
            ``True`` for "Save and Continue" (the launch should proceed), ``False`` for "Cancel".
        """
        joined = "\n".join(dirty_names)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("in-reach")
        box.setText(
            "Save your changes to the following files before launching ReachVariantTool:\n\n"
            f"{joined}"
        )
        save_button = box.addButton("Save and Continue", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save_button)
        box.exec()
        if box.clickedButton() is not save_button:
            return False
        self.main_panel.save_paths(self._rvt_synced_json_paths(folder))
        return True

    def _close_rvt_for_project(self, folder: Path) -> None:
        """PROMPT.md: "if project is closed in ide, if Reach Variant tool is open for that project
        it should be closed" -- terminates whichever RVT process :meth:`launch_rvt` most recently
        started for ``folder``, if it's still running. A no-op if RVT was never launched for this
        project, or if that process has already exited on its own (``Popen.poll()`` returns
        ``None`` only while a process is still running)."""
        process = self._rvt_processes.pop(folder, None)
        if process is not None and process.poll() is None:
            process.terminate()

    def _current_project_bin(self) -> Path | None:
        folder = self.explorer_panel.current_folder
        if folder is None:
            return None
        bin_path = new_project.compiled_variant_path(folder)
        return bin_path if bin_path.is_file() else None

    def _rvt_launch_target(self, folder: Path | None) -> Path | None:
        """What :meth:`launch_rvt` actually hands RVT to open -- the freshly-*compiled* ``.bin``
        (:func:`~in_reach.app.new_project.compiled_variant_path`) if the best-effort pre-launch
        compile above produced one, same as :attr:`_current_project_bin`'s own result. Falls back
        to :func:`~in_reach.app.new_project.source_variant_path` (the project's original,
        never-recompiled starting point) when it hasn't -- a project created from a real personal/
        built-in variant with a non-trivial script can genuinely fail to recompile (the decompile->
        recompile round trip isn't guaranteed lossless), which used to leave ``launch_rvt`` opening
        RVT against nothing at all rather than at least the gametype the user actually picked.
        """
        if folder is None:
            return None
        compiled = new_project.compiled_variant_path(folder)
        if compiled.is_file():
            return compiled
        source = new_project.source_variant_path(project.get_project_dir(self.root_dir), folder)
        return source if source.is_file() else None

    def _on_active_project_changed(self, folder: Path | None) -> None:
        """PROMPT.md: "rvt should not be launchable if no project is open" -- and the Apply
        button's own enabled state depends on the *active* project's own ``settings/`` too, so both
        need re-checking on every tab switch, not just when a project first opens/closes."""
        self.explorer_panel.rvt_button.setEnabled(folder is not None)
        self._refresh_apply_enabled(folder)

    def _sync_project_dependent_views(self, folder: Path | None) -> None:
        """Collapses the primary sidebar whenever the active project closes (nothing left open in
        it worth showing on screen unasked) -- clicking a view button again still works with no
        project open, it just switches to that view's own "Open a Project to use ..." placeholder
        rather than the real panel (see :meth:`_on_sidebar_view_selected`); the view-toggle buttons
        and the top bar's own sidebar toggle are never disabled for this, unlike before.

        Only reacts to the *has-a-project/has-none* transition, not to which project is active --
        replacing the open project with another one (PROMPT.md: "1 per window") re-fires
        ``active_project_changed`` too (``folder`` going from one real path to another), which
        should leave the sidebar's current open/collapsed state alone rather than force it back
        open on every switch. The one
        exception is the moment a project first becomes available with none open before it (at
        startup, or opening/creating the very first one) -- the panels were just unlocked, so this
        reveals the Dashboard automatically rather than leaving the user to notice the
        now-enabled icons themselves (matching this app's own prior default of always starting
        with the sidebar open).
        """
        has_project = folder is not None
        if not has_project:
            self._show_sidebar(False)
            self.activity_bar.set_active_view(None)
        elif not self._had_project:
            self._active_sidebar_view = DEFAULT_VIEW
            self._sidebar_stack.setCurrentWidget(self._sidebar_pages[DEFAULT_VIEW])
            self._show_sidebar(True)
            self.activity_bar.set_active_view(DEFAULT_VIEW)
        self._had_project = has_project

    def _refresh_apply_enabled(self, folder: Path | None) -> None:
        from in_reach.app import apply_settings

        enabled = folder is not None and apply_settings.settings_have_unapplied_changes(folder)
        self.activity_bar.set_apply_enabled(enabled)

    def _on_file_saved(self, path: Path) -> None:
        """Re-checks the Apply button's enabled state whenever a file is saved -- PROMPT.md: Apply
        "should only be available if a user has made changes to files in settings". Cheap enough to
        just always re-check on any save rather than filtering to paths under ``settings/`` first;
        the check itself is a handful of small-file reads.

        Also takes a traceable VCS snapshot of the active project (PROMPT.md: "every change should
        be traceable (but not stamped explicitly)") -- a no-op if nothing actually changed on disk
        since the last snapshot, or if the project has no history yet (see :func:`in_reach.app.vcs.
        record_change`)."""
        folder = self.explorer_panel.current_folder
        self._refresh_apply_enabled(folder)
        if folder is not None:
            from in_reach.app import vcs

            vcs.record_change(folder)
            self._refresh_vcs_status(folder)

    # -- VCS panel (PROMPT.md: "vcs panel and dulwich implementation") --------------------------

    def _refresh_vcs_status(self, folder: Path | None) -> None:
        """Refreshes (or hides) the bottom-left "<branch> - <last stamped> - <last saved>" segment
        to match ``folder``'s own VCS history -- called whenever the active project changes and
        after any action that adds to that history (a save, a stamp, a new/switched branch)."""
        from in_reach.app import vcs

        if folder is None or not vcs.is_initialized(folder):
            self.status_bar.clear_vcs_status()
            return
        branch = vcs.current_branch(folder) or "?"
        last_stamp = vcs.last_stamp(folder)
        stamp_text = last_stamp.stamp_message if last_stamp is not None else None
        saved_at = vcs.last_saved_at(folder)
        saved_text = self._format_time_ago(saved_at) if saved_at is not None else "never"
        self.status_bar.set_vcs_status(
            branch, stamp_text, saved_text, on_click=lambda: self._on_sidebar_view_selected("git")
        )

    @staticmethod
    def _format_time_ago(epoch: float) -> str:
        """A short "just now"/"N min ago"/"N hr ago"/"N days ago" rendering of a past Unix
        timestamp -- kept to whole units rather than exact durations, since the bottom bar's own
        segment is a glance-at-it status, not a precise log."""
        import time

        seconds = max(0, int(time.time() - epoch))
        if seconds < 60:
            return "just now"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} min ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours} hr ago"
        days = hours // 24
        return f"{days} day{'s' if days != 1 else ''} ago"

    def vcs_stamp(self, message: str) -> None:
        """"Stamp Release" (the Git panel's own button) -- PROMPT.md: "ability for a user to stamp
        a release (which takes a 'commit message')". A no-op with no project open."""
        folder = self.explorer_panel.current_folder
        if folder is None:
            return
        from in_reach.app import vcs

        try:
            vcs.stamp(folder, message)
        except ValueError as exc:
            QMessageBox.critical(self, "in-reach", str(exc))
            return
        _logger.info("stamped release %r for %s", message, folder)
        self.git_panel.refresh()
        self._refresh_vcs_status(folder)

    def vcs_new_branch(self, name: str) -> None:
        """"New Branch" (the Git panel's own button) -- PROMPT.md: "also ability to create a new
        branch". A no-op with no project open."""
        folder = self.explorer_panel.current_folder
        if folder is None:
            return
        from in_reach.app import vcs

        try:
            vcs.create_branch(folder, name)
        except ValueError as exc:
            QMessageBox.critical(self, "in-reach", str(exc))
            return
        _logger.info("created branch %r for %s", name, folder)
        self.git_panel.refresh()
        self._refresh_vcs_status(folder)

    def vcs_switch_branch(self, name: str) -> None:
        """Switching branches (the Git panel's own branch combo, PROMPT.md: "it should be possible
        ... to change and switch versions/branches") overwrites/deletes real files on disk to match
        the target branch's own last snapshot -- refuses outright if that would blow away an
        open tab's own unsaved edits (same "warn, don't silently clobber" treatment as an RVT
        resync, see :meth:`_confirm_overwrite_rvt_changes`), and snapshots the project's current
        state first so anything already saved to disk is never actually lost from history even
        though the working files themselves are about to change. Reloads every open tab under this
        project afterward so nothing already open goes stale."""
        folder = self.explorer_panel.current_folder
        if folder is None:
            return
        dirty_names = self.main_panel.dirty_tab_names_under(folder)
        if dirty_names and not self._confirm_switch_branch_overwrite(dirty_names):
            return
        from in_reach.app import vcs

        vcs.record_change(folder)
        try:
            vcs.switch_branch(folder, name)
        except ValueError as exc:
            QMessageBox.critical(self, "in-reach", str(exc))
            return
        _logger.info("switched to branch %r for %s", name, folder)
        self.main_panel.reload_open_tabs_under(folder)
        self.git_panel.refresh()
        self._refresh_vcs_status(folder)

    def _confirm_switch_branch_overwrite(self, dirty_names: list[str]) -> bool:
        """Asks whether to proceed with a branch switch that would overwrite unsaved edits in
        ``dirty_names`` -- kept as its own method purely as a test seam, same reasoning as
        :meth:`_confirm_overwrite_rvt_changes`.

        Returns:
            ``True`` for "Switch Anyway", ``False`` for "Cancel".
        """
        joined = "\n".join(dirty_names)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("in-reach")
        box.setText(
            "Switching branches will overwrite unsaved changes in the following open files:\n\n"
            f"{joined}\n\nSwitch anyway, or cancel?"
        )
        box.addButton("Switch Anyway", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.buttonRole(box.clickedButton()) == QMessageBox.ButtonRole.AcceptRole

    def vcs_delete_branch(self, name: str) -> None:
        """"Delete Branch" (the Git panel's own button, PROMPT.md: "add any other functionality
        you think may help the user manage the project using vcs") -- reports a refusal (the
        current branch, or the only remaining one) rather than crashing. A no-op with no project
        open."""
        folder = self.explorer_panel.current_folder
        if folder is None:
            return
        from in_reach.app import vcs

        try:
            vcs.delete_branch(folder, name)
        except ValueError as exc:
            QMessageBox.critical(self, "in-reach", str(exc))
            return
        _logger.info("deleted branch %r for %s", name, folder)
        self.git_panel.refresh()
        self._refresh_vcs_status(folder)

    def _vcs_ref_label(self, folder: Path, ref: str) -> str:
        """A ref token's own display label -- a branch name as-is, or a stamp's sha rendered as
        "Stamp: <message>" -- shared by the diff dialog's own title and the command palette's
        "Compare" entries."""
        from in_reach.app import vcs

        if ref in vcs.list_branches(folder):
            return ref
        snapshot = next((s for s in vcs.history(folder) if s.sha == ref and s.is_stamp), None)
        return f"Stamp: {snapshot.stamp_message}" if snapshot is not None else ref

    def vcs_compare(self, ref_a: str, ref_b: str) -> None:
        """"Compare" (the Git panel's own combos, PROMPT.md: "they should be able to view branch
        differences[; and] compare different stamped versions") -- opens a
        :class:`~in_reach.ide.diff_dialog.DiffDialog` listing every file that differs between
        ``ref_a`` and ``ref_b`` (each a branch name or a stamp's sha). A no-op with no project
        open."""
        folder = self.explorer_panel.current_folder
        if folder is None:
            return
        from in_reach.app import vcs
        from in_reach.ide.diff_dialog import DiffDialog

        try:
            diffs = vcs.diff(folder, ref_a, ref_b)
        except ValueError as exc:
            QMessageBox.critical(self, "in-reach", str(exc))
            return
        title = f"{self._vcs_ref_label(folder, ref_a)} vs. {self._vcs_ref_label(folder, ref_b)}"
        dialog = DiffDialog(self, title=title, diffs=diffs)
        dialog.exec()

    def vcs_restore(self, sha: str) -> None:
        """"Restore Selected" (the Git panel's own history list, PROMPT.md: "add any other
        functionality you think may help the user manage the project using vcs") -- brings the
        project's files back to a specific past snapshot (any stamp or traceable commit) without
        switching branches (see :func:`~in_reach.app.vcs.restore_snapshot`'s own docstring for why
        this never loses history). Same unsaved-edits guard and open-tab reload as
        :meth:`vcs_switch_branch`. A no-op with no project open."""
        folder = self.explorer_panel.current_folder
        if folder is None:
            return
        dirty_names = self.main_panel.dirty_tab_names_under(folder)
        if dirty_names and not self._confirm_restore_overwrite(dirty_names):
            return
        from in_reach.app import vcs

        try:
            vcs.restore_snapshot(folder, sha)
        except ValueError as exc:
            QMessageBox.critical(self, "in-reach", str(exc))
            return
        _logger.info("restored snapshot %s for %s", sha, folder)
        self.main_panel.reload_open_tabs_under(folder)
        self.git_panel.refresh()
        self._refresh_vcs_status(folder)

    def _confirm_restore_overwrite(self, dirty_names: list[str]) -> bool:
        """Asks whether to proceed with a restore that would overwrite unsaved edits in
        ``dirty_names`` -- kept as its own method purely as a test seam, same reasoning as
        :meth:`_confirm_switch_branch_overwrite`.

        Returns:
            ``True`` for "Restore Anyway", ``False`` for "Cancel".
        """
        joined = "\n".join(dirty_names)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("in-reach")
        box.setText(
            "Restoring this snapshot will overwrite unsaved changes in the following open files:\n\n"
            f"{joined}\n\nRestore anyway, or cancel?"
        )
        box.addButton("Restore Anyway", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.buttonRole(box.clickedButton()) == QMessageBox.ButtonRole.AcceptRole

    def apply_settings_changes(self) -> None:
        """"Apply" (the activity bar's own button) -- compiles the active project's ``settings/``
        + ``script/output.txt`` into a real gametype ``.bin`` (PROMPT.md: "applying changes
        should try and compile the jsons into a gametype"). A no-op with no project open (the
        button is disabled then anyway, see :meth:`_on_active_project_changed`).

        PROMPT.md: "i[f] it fails then dont allow application (raise errors in text window --
        although hopefully our schema validaation should catch this)" -- a failed compile leaves
        ``build/`` completely untouched (see
        :func:`~in_reach.app.rvt.compile.run_compile`'s own docstring) and is surfaced here as a
        critical message box listing every compiler error/warning/notice, same presentation as
        this window's other blocking failures (e.g. a schema-invalid save, see
        :meth:`~in_reach.ide.tabs.TabPane._save_tab`).

        Disables the button itself the instant it's clicked, before the (blocking) compile even
        starts -- PROMPT.md: "we are having to press compile twice" -- see :meth:`_run_compile`'s
        own docstring for why that alone was the actual bug, not the compile result itself.
        """
        folder = self.explorer_panel.current_folder
        if folder is None:
            return
        project_dir = project.get_project_dir(self.root_dir)
        self.activity_bar.apply_button.setEnabled(False)
        result = self._run_compile(project_dir, folder)
        if not result.success:
            from in_reach.app.rvt.compile import format_build_result

            QMessageBox.critical(self, "in-reach", f"Couldn't apply settings:\n{format_build_result(result)}")
            self._refresh_apply_enabled(folder)  # re-enable -- the edit is still unapplied
            return
        self._refresh_apply_enabled(folder)
        self._sync_project_title(folder)
        # A successful Apply may have just created build/dist/*.bin for the very first time --
        # see launch_rvt()'s own matching call for why this needs (re-)arming here too, not just
        # there (a project might never actually launch RVT, but its own edits should still resync
        # if the user opens that compiled .bin directly some other way).
        self._rewatch_project_bin(folder)
        # PROMPT.md: "please also add a stats view into the dashboard" -- a successful Apply just
        # regenerated build/stats.autogenerated.json too; the Dashboard's own Stats box only reads
        # it on project-switch otherwise, so it'd stay stale until the user clicked away and back.
        self.explorer_panel.refresh_stats()

    def view_output_txt(self) -> None:
        """"View Output.txt" (PROMPT.md, under the Dashboard's own button row) -- opens a
        read-only, always-freshly-regenerated view of the active project's ``script/output.txt``
        (see :func:`~in_reach.app.output_view.write_output_view`'s own docstring for why it's
        regenerated on every click rather than kept continuously in sync). A no-op with no project
        open."""
        folder = self.explorer_panel.current_folder
        if folder is None:
            return
        from in_reach.app.output_view import write_output_view

        _logger.info("viewing compiled output for %s", folder)
        path = write_output_view(folder)
        self.main_panel.active_pane.open_file(path, force_reload=True)

    def open_notes(self) -> None:
        """"Open Notes" (the ``>`` command palette, PROMPT.md) -- opens the active
        project's own freeform scratch notes file, ``Notes.txt`` or ``Notes.md`` per the saved
        :mod:`in_reach.app.notes_settings` preference (see :func:`~in_reach.app.notes_settings.
        ensure_notes_file`, which creates the target file from the same template ``Notes.txt``
        already starts with if this is the first time it's been opened in that format). A no-op
        with no project open.

        PROMPT.md: "if .md is chosen, then editor should be .md" -- opened as a real, editable tab
        (see :meth:`~in_reach.ide.tabs.TabPane.open_file`'s own ``editable_markdown``) rather than
        the usual read-only rendered preview every other ``.md`` file gets, so there's an actual
        source view to type notes into and (via the magnifying-glass icon that appears next to the
        split buttons for exactly this tab) split into a live preview alongside it.
        """
        folder = self.explorer_panel.current_folder
        if folder is None:
            return
        from in_reach.app import notes_settings

        notes_format = notes_settings.get_notes_format(self._notes_format_env_path())
        path = notes_settings.ensure_notes_file(folder, notes_format)
        _logger.info("opening notes for %s", folder)
        self.main_panel.active_pane.open_file(path, editable_markdown=notes_format == notes_settings.FORMAT_MD)

    def _notes_format_env_path(self) -> Path:
        return project.get_project_dir(self.root_dir) / ".env"

    def _set_notes_format(self, notes_format: str) -> None:
        """"Set Notes Format" (the ``>`` command palette, PROMPT.md: "can be set in settings or
        command palette") -- persists which file "Notes" opens from here on. Never touches whatever
        notes file is already open in a tab."""
        from in_reach.app import notes_settings

        notes_settings.set_notes_format(self._notes_format_env_path(), notes_format)

    def export_rvt_file(self) -> None:
        """"Export RVT File" (PROMPT.md, under the Dashboard's own button row) -- compiles the
        active project the same way :meth:`apply_settings_changes` does, then a standard Save As
        dialog lets the user save the result as either a full ``.bin`` (a plain copy of the
        freshly-compiled variant) or RVT's own bare/script-only ``.mglo`` (PROMPT.md: "please check
        old repos for guidance" -- ported from v2's own ``app/mglo.py``, see
        :func:`~in_reach.app.rvt.mglo.write_mglo`'s own docstring). A no-op with no project open.

        If the active project's own ``settings/`` has changes that haven't been compiled yet (the
        activity bar's own Apply/compile arrow isn't "green" -- see
        :func:`~in_reach.app.apply_settings.settings_have_unapplied_changes`), asks whether to
        compile them first rather than silently exporting whatever ``build/dist/*.bin`` already
        happens to hold (see :meth:`_confirm_compile_before_export`).
        """
        folder = self.explorer_panel.current_folder
        if folder is None:
            return
        from in_reach.app import apply_settings

        if apply_settings.settings_have_unapplied_changes(folder) and not self._confirm_compile_before_export():
            return

        project_dir = project.get_project_dir(self.root_dir)
        # Disabled for the compile's own duration -- see _run_compile()'s own docstring
        # (PROMPT.md: "we are having to press compile twice").
        self.explorer_panel.export_button.setEnabled(False)
        try:
            result = self._run_compile(project_dir, folder)
        finally:
            self.explorer_panel.export_button.setEnabled(True)
        if not result.success:
            from in_reach.app.rvt.compile import format_build_result

            QMessageBox.critical(self, "in-reach", f"Couldn't compile before export:\n{format_build_result(result)}")
            return
        # This compile is the same one Apply's own button runs -- refresh everything that button's
        # own click handler refreshes after a successful compile (the activity bar's own compile
        # arrow included), or the side icon panel keeps reading as "changes pending" even though
        # exporting here just applied them.
        self._refresh_apply_enabled(folder)
        self._sync_project_title(folder)
        self._rewatch_project_bin(folder)
        self.explorer_panel.refresh_stats()
        compiled = new_project.compiled_variant_path(folder)
        if not compiled.is_file():
            QMessageBox.critical(
                self, "in-reach", "Nothing to export -- this gametype hasn't compiled successfully yet."
            )
            return

        default_name = f"{new_project.read_project_title(folder)}.bin"
        chosen = self.ask_export_path(compiled.parent / default_name)
        if not chosen:
            return
        dest = Path(chosen)

        if dest.suffix.lower() == ".mglo":
            from in_reach.app.rvt.decompile import SCRIPT_FILENAME
            from in_reach.app.rvt.mglo import write_mglo

            script_path = folder / new_project.SCRIPT_DIRNAME / SCRIPT_FILENAME
            if not write_mglo(compiled, script_path, dest):
                QMessageBox.critical(self, "in-reach", f"Couldn't write {dest.name}.")
                return
            _logger.info("exported %s to %s", folder, dest)
            return

        import shutil

        try:
            shutil.copyfile(compiled, dest)
        except OSError as exc:
            QMessageBox.critical(self, "in-reach", f"Couldn't export {dest.name}:\n{exc}")
            return
        _logger.info("exported %s to %s", folder, dest)

    def _open_builtin_folder(self, env_key: str) -> None:
        """Handles :attr:`~in_reach.ide.explorer.ExplorerPanel.open_builtin_folder_requested` --
        PROMPT.md's Dashboard "Quick Launch" "Built-in"/"Hot Reload" buttons. Resolves ``env_key``
        (one of :mod:`in_reach.app.system_verify`'s own checklist keys, e.g. ``STANDARD_VARIANTS_
        KEY``) against this window's own project-root ``.env`` -- the same one the Welcome tab's
        Verify System Settings flow itself writes to (:class:`~in_reach.ide.verify_dialog.
        VerifyDialog`) -- rather than the active gametype project's own folder, since these are
        install-wide locations (Steam's own game/map variant folders, MCC's hot-reload folder), not
        anything scoped to a single project.

        Tells the user to run Verify System Settings first rather than silently doing nothing if
        the checklist was never run (or that particular step never resolved) for this key.
        """
        env_path = system_verify.env_path_for(project.get_project_dir(self.root_dir))
        value = env_file.get_env_values(env_path).get(env_key, "")
        if not value or not Path(value).is_dir():
            QMessageBox.information(
                self,
                "in-reach",
                "This folder hasn't been resolved yet -- run Verify System Settings from the "
                "Welcome tab first.",
            )
            return
        self.open_folder_in_os_explorer(Path(value))

    def open_folder_in_os_explorer(self, path: Path) -> None:
        """Kept as its own method purely as a test seam (same reasoning as ``ask_open_folder``) --
        opens ``path`` in the OS's own file explorer."""
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _sync_project_title(self, folder: Path) -> None:
        """Brings every cached display of ``folder``'s own title -- any already-open editor's
        breadcrumb, the Welcome tab's Recent list, the bottom status bar's own centered label --
        back in sync with ``settings/settings.json``'s own ``meta.title`` (PROMPT.md: "when a
        project name is changed [via rvt or via apply settings.json change] - the project title
        should change in the tabs and in the breadcrumb"; later: "it needs to be renamed in
        recents in dropdown and in the welcome window").

        There used to be a separate README.md carrying its own copy of the title that this had to
        rewrite to match; now that :func:`~in_reach.app.new_project.read_project_title` reads
        ``settings.json`` directly (PROMPT.md: "please remove the README.md file completely"),
        ``settings.json`` is already the up-to-date, sole source of truth by the time this runs --
        the resync/Apply that just finished is exactly what wrote it -- so this just needs to tell
        every *cached* display to re-read it. Called unconditionally after a successful Apply (a
        hand-edited ``settings.json``) and after a resync from a changed ``.bin`` (an RVT-driven
        rename, now left free to flow through -- see
        :func:`~in_reach.app.rvt.decompile.resync_from_bin`'s own docstring); harmless to call when
        nothing actually changed.
        """
        self.main_panel.refresh_project_titles()
        self._update_quick_access_label(folder)

    def _rewatch_project_bin(self, _folder: Path | None) -> None:
        """Re-points :attr:`_bin_watcher` at the newly-active project's own freshly-*compiled*
        ``.bin`` (see :func:`~in_reach.app.new_project.compiled_variant_path` -- the same file
        :meth:`launch_rvt` opens RVT against, PROMPT.md: generated files "should update when rvt
        saves") -- called on every ``explorer_panel.active_project_changed`` (switching tabs, or
        closing the last one, always watches the right file rather than a stale one left over from
        whichever project used to be active), and again after :meth:`launch_rvt`/
        :meth:`apply_settings_changes` each successfully compile, since that may be the first time
        this path actually exists to watch at all (or a fresh delete-then-recreate save that
        dropped the previous watch -- see :meth:`_on_watched_bin_changed`'s own tail)."""
        watched = self._bin_watcher.files()
        if watched:
            self._bin_watcher.removePaths(watched)
        bin_path = self._current_project_bin()
        if bin_path is not None:
            self._bin_watcher.addPath(str(bin_path))

    def _on_watched_bin_changed(self, path: str) -> None:
        """Re-decompiles the watched ``.bin`` into ``settings/`` and ``build/``'s
        ``*.autogenerated.json`` snapshot -- ``script/output.txt`` (the one genuinely
        hand-editable thing left) is deliberately untouched, see
        :func:`~in_reach.app.rvt.decompile.resync_from_bin`'s own docstring. Best-effort: a
        ``.bin`` RVT happened to be mid-write on, or any other decompile failure, is silently
        swallowed rather than popping an error over a background sync the user didn't explicitly
        ask for.

        PROMPT.md: "when making changes to a project in rvt, upon save: any open
        script_settings.json, settings.json, or strings.json without saved changes should
        immediately update in place[; a]ny of the above with unsaved changes should pop up showing
        all unsaved changes and asking whether to confirm overwrite or abort reach variant tool
        save" -- checked *before* the resync actually runs (see :meth:`_confirm_overwrite_rvt_changes`),
        so choosing "Abort" leaves ``settings/`` (and every open tab) untouched by this cycle
        rather than trying to undo a write that's already landed on disk. "Overwrite" (or nothing
        dirty at all) proceeds with the resync as before, then reloads every matching open tab in
        place via :meth:`~in_reach.ide.tabs.MainPanelArea.reload_open_tabs`.

        Title/description are deliberately *not* carried forward from the old ``settings.json``
        here (unlike category, which isn't a ``.bin`` concept at all) -- PROMPT.md: "when a project
        name is changed via rvt ... the project title should change in the tabs and in the
        breadcrumb". Leaving them out of the call lets resync_from_bin's own freshly-extracted
        values win, and :meth:`_sync_project_title` (below) is what actually refreshes the
        Explorer's own project tab/an open editor's breadcrumb to match.

        Args:
            path: The changed file's path, as ``QFileSystemWatcher.fileChanged`` reports it.
        """
        bin_path = Path(path)
        folder = self.explorer_panel.current_folder
        if folder is not None and bin_path.is_file():
            from in_reach.app import maps_io
            from in_reach.app.rvt import settings_io
            from in_reach.app.rvt.decompile import resync_from_bin

            watched_json_paths = self._rvt_synced_json_paths(folder)
            dirty_names = self.main_panel.dirty_tab_names(watched_json_paths)
            if not dirty_names or self._confirm_overwrite_rvt_changes(dirty_names):
                settings_path = folder / new_project.SETTINGS_DIRNAME / "settings.json"
                category, category_icon = settings_io.load_meta_category(settings_path)
                map_entries = maps_io.read_maps_json(project.get_project_dir(self.root_dir))
                try:
                    resync_from_bin(
                        bin_path,
                        folder,
                        category=category,
                        category_icon=category_icon,
                        map_entries=map_entries,
                    )
                except Exception:  # noqa: BLE001 -- native/pydantic code can raise almost anything
                    pass
                else:
                    self.main_panel.reload_open_tabs(watched_json_paths)
                    self._sync_project_title(folder)
                    # PROMPT.md: "please also add a stats view into the dashboard" -- this resync
                    # just regenerated build/stats.autogenerated.json too.
                    self.explorer_panel.refresh_stats()
                    # PROMPT.md: "every change should be traceable" -- RVT overwriting settings/
                    # directly (outside the normal in-app save path _on_file_saved already covers)
                    # is still a real change to the project's own tracked files.
                    from in_reach.app import vcs

                    vcs.record_change(folder)
                    self._refresh_vcs_status(folder)
        # Some writers (RVT included, potentially) save via delete-then-recreate rather than an
        # in-place write, which silently drops the path from a QFileSystemWatcher -- re-add it so
        # the *next* save still gets caught.
        if bin_path.is_file() and str(bin_path) not in self._bin_watcher.files():
            self._bin_watcher.addPath(str(bin_path))

    def _confirm_overwrite_rvt_changes(self, dirty_names: list[str]) -> bool:
        """Asks whether to let a just-saved RVT resync overwrite unsaved edits in ``dirty_names``
        (already-open settings/script_settings/strings.json tabs) -- kept as its own method purely
        as a test seam, same reasoning as :meth:`~in_reach.ide.tabs.TabPane._ask_save_choice`.

        Returns:
            ``True`` for "Overwrite" (the resync should proceed), ``False`` for "Abort".
        """
        box = QMessageBox(self)
        box.setWindowTitle("in-reach")
        joined = "\n".join(dirty_names)
        box.setText(
            "ReachVariantTool just saved this project, but the following files have unsaved "
            f"changes here that would be overwritten:\n\n{joined}\n\n"
            "Overwrite your unsaved changes with ReachVariantTool's, or abort applying this save?"
        )
        overwrite_button = box.addButton("Overwrite", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Abort", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(overwrite_button)
        box.exec()
        return box.buttonRole(box.clickedButton()) == QMessageBox.ButtonRole.AcceptRole

    def _confirm_compile_before_export(self) -> bool:
        """"[I]f a user has made changes to the settings jsons that haven't been applied yet ...
        then export rvt should prompt the user to compile first" (PROMPT.md) -- asked right before
        :meth:`export_rvt_file` would otherwise silently compile over whatever ``build/dist/*.bin``
        already holds. Kept as its own method purely as a test seam, same reasoning as
        :meth:`_confirm_overwrite_rvt_changes`.

        Returns:
            ``True`` for "Compile Now" (export should proceed), ``False`` for "Cancel".
        """
        box = QMessageBox(self)
        box.setWindowTitle("in-reach")
        box.setText(
            "This project has changes in settings/ that haven't been compiled yet. Compile them "
            "now before exporting?"
        )
        compile_button = box.addButton("Compile Now", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(compile_button)
        box.exec()
        return box.buttonRole(box.clickedButton()) == QMessageBox.ButtonRole.AcceptRole
