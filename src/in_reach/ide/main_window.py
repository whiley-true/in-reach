"""VSCode-shaped main window: a frameless custom top bar (a small mark, dropdown menus,
sidebar/panel toggles, window controls), a fixed activity bar, a toggleable primary sidebar, a
split-capable main panel above a toggleable bottom panel, and a bottom status bar. Since the window
is frameless, edge/corner dragging (to resize) and the maximize/restore button are both
hand-implemented here rather than provided by the OS chrome -- see ``in_reach.ide.window_resize``/
``toggle_maximize()``.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QFileSystemWatcher, QPoint, Qt
from PyQt6.QtGui import QKeySequence, QMouseEvent, QPalette, QShortcut
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

from in_reach.app import env_file, new_project, open_projects, project, recent, rvt_launcher
from in_reach.ide import icons, style
from in_reach.ide import zoom as zoom_module
from in_reach.ide.activity_bar import DEFAULT_VIEW, ActivityBar
from in_reach.ide.bottom_panel import BottomPanel
from in_reach.ide.explorer import ExplorerPanel
from in_reach.ide.search_panel import SearchPanel
from in_reach.ide.status_bar import StatusBar
from in_reach.ide.tabs import MainPanelArea
from in_reach.ide.theme import Theme
from in_reach.ide.window_resize import cursor_for_edges, resize_edges

_TOP_BAR_HEIGHT = 36
_ICON_SIZE = 16
_TOPBAR_MARK_SIZE = 20  # PROMPT.md: "make the taskbar icon 10% bigger" -- 16 -> 18 (+10%) -> 20 (+10% again)
_WINDOW_BUTTON_WIDTH = 46
#: PROMPT.md: "make sure file explorer panel expands by default so text is visible without
#: contracting (at the moment we see Personal G..e Variants)" -- 180 let the sidebar (and with it,
#: the "Personal Game/Map Variants" section headers) get squeezed narrow enough to middle-elide.
#: Bumped once to 220 (still not quite enough headroom at DEFAULT_ZOOM's un-reduced 150%, per a
#: later PROMPT.md: "the default file explorer panel [width] still needs to be slightly wider by
#: default") and again here to 240 -- wide enough headroom over the headers' own sizeHint() that a
#: narrow window has to shrink something else before this text does (see test_ide_smoke.py's own
#: width-vs-sizeHint regression guard for the margin this was picked against).
_SIDEBAR_MIN_WIDTH = 240


class _DropdownButton(QToolButton):
    """A "text1"/"text2"-style topbar dropdown -- placeholder items only, per PROMPT.md."""

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(label)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setAutoRaise(True)
        menu = QMenu(self)
        menu.addAction(f"{label} item 1")
        menu.addAction(f"{label} item 2")
        self.setMenu(menu)


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
        menu.addAction("New File", window.new_file)
        menu.addAction("New Window", window.open_new_window)
        menu.addAction("Open File...", window.open_file)
        menu.addAction("Open Folder...", window.open_folder)
        self.open_recent_menu = menu.addMenu("Open Recent")
        self.open_recent_menu.aboutToShow.connect(self._populate_open_recent)
        menu.addSeparator()
        menu.addAction("Save", window.save_current)
        menu.addAction("Save As...", window.save_current_as)
        menu.addAction("Save All", window.save_all)
        menu.addSeparator()
        menu.addAction("Close Project", window.close_project)
        menu.addAction("Close Editor", window.close_editor)
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
        self.setStyleSheet("background-color: palette(window);")
        self.setMouseTracking(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(4)

        self.mark_label = QLabel()
        self.set_mark_size(_TOPBAR_MARK_SIZE)
        layout.addWidget(self.mark_label)
        layout.addSpacing(4)

        self.file_menu_button = _FileMenuButton(window)
        layout.addWidget(self.file_menu_button)
        layout.addWidget(_DropdownButton("text2"))
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
    def __init__(self, root_dir: Path | None = None) -> None:
        super().__init__()
        self.root_dir = root_dir or Path.cwd()
        self._active_sidebar_view = DEFAULT_VIEW
        # Qt never parents a top-level window to another -- without holding a reference somewhere,
        # a window opened via File > New Window would be garbage-collected (and vanish) as soon as
        # open_new_window() returns.
        self._child_windows: list[MainWindow] = []
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

        self.activity_bar = ActivityBar()
        body_layout.addWidget(self.activity_bar)

        self._side_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._side_splitter.setStyleSheet(style.GAP_SPLITTER_HANDLE_STYLE)
        self._side_splitter.setHandleWidth(style.SIDEBAR_CONTENT_GAP)
        self._side_splitter.setChildrenCollapsible(False)
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
        self._side_splitter.setSizes([_SIDEBAR_MIN_WIDTH, 1000])

        self.main_panel = MainPanelArea(
            root_dir=self.root_dir,
            reveal_in_explorer=self._reveal_in_explorer_view,
            on_project_opened=self._on_project_opened,
            on_settings_changed=self._on_settings_changed,
            on_file_saved=self._on_file_saved,
        )
        self._main_splitter.addWidget(self.main_panel)

        # PROMPT.md: "[generated files] should update when rvt saves" -- watches the active
        # project's own source .bin (see _rewatch_project_bin()) and re-syncs settings/ and
        # build/'s *.autogenerated.json snapshot whenever RVT writes over it from outside this
        # process.
        self._bin_watcher = QFileSystemWatcher(self)
        self._bin_watcher.fileChanged.connect(self._on_watched_bin_changed)

        env_project_dir = project.get_project_dir(self.root_dir)
        self.explorer_panel.set_env_project_dir(env_project_dir)
        # PROMPT.md: multi-project tabs -- re-open every tab still on disk from last launch;
        # PROJECT_DIR_KEY (the single most-recently-created project) is only a fallback for a
        # .env from before OPEN_PROJECTS existed, so upgrading doesn't silently lose the one
        # project that .env already knew about.
        self.explorer_panel.active_project_changed.connect(self.search_panel.set_project_folder)
        self.explorer_panel.active_project_changed.connect(self._rewatch_project_bin)
        self.explorer_panel.active_project_changed.connect(self._on_active_project_changed)
        self.explorer_panel.open_projects_changed.connect(self._on_open_projects_changed)
        restored = open_projects.list_open(env_project_dir)
        if not restored:
            already_open = env_file.get_env_values(env_project_dir / ".env").get(new_project.PROJECT_DIR_KEY)
            if already_open and Path(already_open).is_dir():
                restored = [Path(already_open)]
        for folder in restored:
            self.explorer_panel.open_project(folder)
        self.explorer_panel.file_activated.connect(self._on_explorer_file_activated)
        self.search_panel.file_activated.connect(self._on_search_file_activated)

        self.bottom_panel = BottomPanel()
        self._bottom_panel_card = style.wrap_tab_widget(self.bottom_panel)
        self._main_splitter.addWidget(self._bottom_panel_card)
        self._main_splitter.setStretchFactor(0, 1)
        self._main_splitter.setStretchFactor(1, 0)
        self._main_splitter.setSizes([700, 200])

        self.status_bar = StatusBar(self)
        outer.addWidget(self.status_bar)

        self.activity_bar.view_selected.connect(self._on_sidebar_view_selected)
        self.activity_bar.view_collapsed.connect(self._on_sidebar_view_collapsed)
        self.activity_bar.launch_rvt_requested.connect(self.launch_rvt)
        self.activity_bar.apply_requested.connect(self.apply_settings_changes)
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

    def _build_primary_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setMinimumWidth(_SIDEBAR_MIN_WIDTH)
        sidebar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sidebar.setStyleSheet(style.PANEL_BORDER_STYLE)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)

        self.explorer_panel = ExplorerPanel()
        self.search_panel = SearchPanel()
        self._sidebar_pages = {
            "explorer": self.explorer_panel,
            "search": self.search_panel,
        }
        self._sidebar_stack = QStackedWidget()
        for page in self._sidebar_pages.values():
            self._sidebar_stack.addWidget(page)
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
        """Opens a newly created/loaded gametype project as an Explorer tab (PROMPT.md:
        multi-project tabs), switching to it -- alongside whatever other projects are already
        open, not replacing them. The Search panel follows along via
        ``explorer_panel.active_project_changed`` (see ``__init__``), not called directly here."""
        self.explorer_panel.open_project(folder)

    def _on_open_projects_changed(self, folders: list[Path]) -> None:
        """Persists the Explorer's current tab set so it comes back on the next launch (PROMPT.md:
        multi-project tabs)."""
        open_projects.set_open(project.get_project_dir(self.root_dir), folders)

    def _on_settings_changed(self) -> None:
        """Re-resolves the Explorer panel's personal-folder sections after a verify run or "Clear
        Entries" on the Welcome tab might have changed either one."""
        self.explorer_panel.refresh_personal_folders()

    def _on_explorer_file_activated(self, path: Path) -> None:
        """Opens a file clicked in any of the Explorer panel's three trees -- into the active
        pane, same as "Open File" from the File menu (and, like that action, switching to the tab
        instead of duplicating it if the file's already open there)."""
        self.main_panel.active_pane.open_file(path)

    def _on_search_file_activated(self, path: Path, line_number: int) -> None:
        """Opens a search result -- into the active pane, jumping straight to the matched line."""
        self.main_panel.active_pane.open_file_at_line(path, line_number)

    # -- File menu ------------------------------------------------------------------------------

    def new_file(self) -> None:
        self.main_panel.new_tab_in(self.main_panel.active_pane)

    def open_new_window(self) -> None:
        """"New Window" -- another MainWindow on the same project, independent of this one."""
        window = MainWindow(root_dir=self.root_dir)
        window.showMaximized()
        self._child_windows.append(window)

    def open_file(self) -> None:
        chosen = self.ask_open_file()
        if chosen:
            self.main_panel.active_pane.open_file(Path(chosen))

    def ask_open_file(self) -> str:
        """Kept as its own method purely as a test seam (see ``tabs.py``'s ``_ask_save_path``)."""
        chosen, _selected_filter = QFileDialog.getOpenFileName(self, "Open File", str(self.root_dir))
        return chosen

    def open_folder(self) -> None:
        """"Open Folder" -- the same "adopt this folder as the current gametype project" action as
        the Welcome tab's own "Load Project"."""
        chosen = self.ask_open_folder()
        if chosen:
            self._adopt_project(Path(chosen))

    def ask_open_folder(self) -> str:
        return QFileDialog.getExistingDirectory(self, "Open Folder", str(self.root_dir))

    def open_recent_project(self, folder: Path) -> None:
        self._adopt_project(folder)

    def _adopt_project(self, folder: Path) -> None:
        recent.add_recent(project.get_project_dir(self.root_dir), folder)
        self._on_project_opened(folder)

    def save_current(self) -> None:
        self.main_panel.active_pane.save_current()

    def save_current_as(self) -> None:
        self.main_panel.active_pane.save_current_as()

    def save_all(self) -> None:
        self.main_panel.save_all()

    def close_project(self) -> None:
        """"Close Project" -- closes whichever project tab is currently active (PROMPT.md:
        multi-project tabs; any other open tabs stay open). Doesn't touch any files, and doesn't
        close this window (that's the title bar's own close button)."""
        self.explorer_panel.close_active_project()

    def close_editor(self) -> None:
        self.main_panel.active_pane.close_current()

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
        QPalette alone: the top bar's icon colors and the status bar's accent color."""
        self.status_bar.set_color(theme.status_bar_color)
        self.refresh_icon_colors(theme.palette_colors.get("window_text"))

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
        # PROMPT.md: "when zooming in and out the quicklaunch panel and its icons are not
        # resizing" -- the activity bar's own buttons are fixed-pixel QToolButtons, same category
        # of "doesn't just fall out of a font change" as the top bar icons refresh_icon_colors()
        # already handles above.
        if app is not None:
            self.activity_bar.refresh_icon_scale(zoom_module.current_scale(app))

    def launch_rvt(self) -> None:
        """Launches in-reach's own bundled ReachVariantTool -- no setup needed, it always resolves
        to a real executable shipped inside the package itself (see
        :func:`in_reach.app.rvt_launcher.resolve_rvt_exe`) -- against the currently selected
        project's own source ``.bin``, if one is open and it has one (PROMPT.md: "when rvt is
        opened, it opens the project in rvt")."""
        try:
            rvt_launcher.launch_rvt(self._current_project_bin())
        except OSError as exc:
            QMessageBox.critical(self, "in-reach", f"Couldn't launch ReachVariantTool:\n{exc}")

    def _current_project_bin(self) -> Path | None:
        folder = self.explorer_panel.current_folder
        if folder is None:
            return None
        bin_path = new_project.source_variant_path(project.get_project_dir(self.root_dir), folder)
        return bin_path if bin_path.is_file() else None

    def _on_active_project_changed(self, folder: Path | None) -> None:
        """PROMPT.md: "rvt should not be launchable if no project is open" -- and the Apply
        button's own enabled state depends on the *active* project's own ``settings/`` too, so both
        need re-checking on every tab switch, not just when a project first opens/closes."""
        self.activity_bar.set_rvt_enabled(folder is not None)
        self._refresh_apply_enabled(folder)

    def _refresh_apply_enabled(self, folder: Path | None) -> None:
        from in_reach.app import apply_settings

        enabled = folder is not None and apply_settings.settings_have_unapplied_changes(folder)
        self.activity_bar.set_apply_enabled(enabled)

    def _on_file_saved(self, path: Path) -> None:
        """Re-checks the Apply button's enabled state whenever a file is saved -- PROMPT.md: Apply
        "should only be available if a user has made changes to files in settings". Cheap enough to
        just always re-check on any save rather than filtering to paths under ``settings/`` first;
        the check itself is a handful of small-file reads."""
        self._refresh_apply_enabled(self.explorer_panel.current_folder)

    def apply_settings_changes(self) -> None:
        """"Apply" (the activity bar's own button) -- pushes the active project's ``settings/``
        onto ``build/``'s ``*.autogenerated.json`` snapshot. A no-op with no project open (the
        button is disabled then anyway, see :meth:`_on_active_project_changed`)."""
        folder = self.explorer_panel.current_folder
        if folder is None:
            return
        from in_reach.app import apply_settings

        apply_settings.apply_settings_changes(folder)
        self._refresh_apply_enabled(folder)

    def _rewatch_project_bin(self, _folder: Path | None) -> None:
        """Re-points :attr:`_bin_watcher` at the newly-active project's own source ``.bin``
        (PROMPT.md: generated files "should update when rvt saves") -- called on every
        ``explorer_panel.active_project_changed``, so switching tabs (or closing the last one)
        always watches the right file, never a stale one left over from whichever project used to
        be active."""
        watched = self._bin_watcher.files()
        if watched:
            self._bin_watcher.removePaths(watched)
        bin_path = self._current_project_bin()
        if bin_path is not None:
            self._bin_watcher.addPath(str(bin_path))

    def _on_watched_bin_changed(self, path: str) -> None:
        """Re-decompiles the watched ``.bin`` into ``settings/`` and ``build/``'s
        ``*.autogenerated.json`` snapshot -- ``edit/rvt/script.txt`` (the one genuinely
        hand-editable thing left) is deliberately untouched, see
        :func:`~in_reach.app.rvt.decompile.resync_from_bin`'s own docstring. Best-effort: a
        ``.bin`` RVT happened to be mid-write on, or any other decompile failure, is silently
        swallowed rather than popping an error over a background sync the user didn't explicitly
        ask for.

        Args:
            path: The changed file's path, as ``QFileSystemWatcher.fileChanged`` reports it.
        """
        bin_path = Path(path)
        folder = self.explorer_panel.current_folder
        if folder is not None and bin_path.is_file():
            from in_reach.app import maps_io
            from in_reach.app.rvt import settings_io
            from in_reach.app.rvt.decompile import resync_from_bin

            settings_path = folder / new_project.SETTINGS_DIRNAME / "settings.json"
            category, category_icon = settings_io.load_meta_category(settings_path)
            map_entries = maps_io.read_maps_json(project.get_project_dir(self.root_dir))
            try:
                resync_from_bin(
                    bin_path, folder, category=category, category_icon=category_icon, map_entries=map_entries
                )
            except Exception:  # noqa: BLE001 -- native/pydantic code can raise almost anything
                pass
        # Some writers (RVT included, potentially) save via delete-then-recreate rather than an
        # in-place write, which silently drops the path from a QFileSystemWatcher -- re-add it so
        # the *next* save still gets caught.
        if bin_path.is_file() and str(bin_path) not in self._bin_watcher.files():
            self._bin_watcher.addPath(str(bin_path))
