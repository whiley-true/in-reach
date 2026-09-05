"""VSCode-shaped main window: a frameless custom top bar (a small mark, dropdown menus,
sidebar/panel toggles, window controls), a fixed activity bar, a toggleable primary sidebar, a
split-capable main panel above a toggleable bottom panel, and a bottom status bar. Since the window
is frameless, edge/corner dragging (to resize) and the maximize/restore button are both
hand-implemented here rather than provided by the OS chrome -- see ``_resize_edges()``/
``toggle_maximize()``.
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QKeySequence, QMouseEvent, QPalette, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from in_reach.ide import icons, style
from in_reach.ide.activity_bar import ActivityBar
from in_reach.ide.bottom_panel import BottomPanel
from in_reach.ide.quick_access import QuickAccessBar
from in_reach.ide.status_bar import StatusBar
from in_reach.ide.tabs import MainPanelArea
from in_reach.ide.theme import Theme

_TOP_BAR_HEIGHT = 36
_ICON_SIZE = 16
_TOPBAR_MARK_SIZE = 16
_WINDOW_BUTTON_WIDTH = 46
_SIDEBAR_MIN_WIDTH = 180
_RESIZE_MARGIN = 6


def _resize_edges(pos: QPoint, width: int, height: int, *, top: bool, bottom: bool) -> Qt.Edge:
    """Which window edge(s) ``pos`` (widget-local) falls within :data:`_RESIZE_MARGIN` of, as an
    OR'd :class:`Qt.Edge` flag combination suitable for :meth:`QWindow.startSystemResize`.
    ``top``/``bottom`` gate whether that particular edge is even reachable from the calling
    widget (the top bar only ever reports its own top/corners; the window body only bottom)."""
    edges = Qt.Edge(0)
    if top and pos.y() <= _RESIZE_MARGIN:
        edges |= Qt.Edge.TopEdge
    if bottom and pos.y() >= height - _RESIZE_MARGIN:
        edges |= Qt.Edge.BottomEdge
    if pos.x() <= _RESIZE_MARGIN:
        edges |= Qt.Edge.LeftEdge
    if pos.x() >= width - _RESIZE_MARGIN:
        edges |= Qt.Edge.RightEdge
    return edges


def _cursor_for_edges(edges: Qt.Edge) -> Qt.CursorShape:
    if (edges & Qt.Edge.TopEdge and edges & Qt.Edge.LeftEdge) or (
        edges & Qt.Edge.BottomEdge and edges & Qt.Edge.RightEdge
    ):
        return Qt.CursorShape.SizeFDiagCursor
    if (edges & Qt.Edge.TopEdge and edges & Qt.Edge.RightEdge) or (
        edges & Qt.Edge.BottomEdge and edges & Qt.Edge.LeftEdge
    ):
        return Qt.CursorShape.SizeBDiagCursor
    if edges & Qt.Edge.LeftEdge or edges & Qt.Edge.RightEdge:
        return Qt.CursorShape.SizeHorCursor
    if edges & Qt.Edge.TopEdge or edges & Qt.Edge.BottomEdge:
        return Qt.CursorShape.SizeVerCursor
    return Qt.CursorShape.ArrowCursor


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


class _TopBar(QWidget):
    """The custom title-bar row: a small mark and dropdown menus on the left, sidebar/panel
    toggles and window controls on the right. Dragging empty space moves the (frameless) window;
    double-clicking it toggles maximize, same as a native title bar. Dragging within
    :data:`_RESIZE_MARGIN` of the window's top edge (or its corners) resizes it instead, since the
    top bar covers the entire top edge and both top corners of the frameless window."""

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

        mark = QLabel()
        mark.setPixmap(icons.topbar_icon().pixmap(_TOPBAR_MARK_SIZE, _TOPBAR_MARK_SIZE))
        layout.addWidget(mark)
        layout.addSpacing(4)

        layout.addWidget(_DropdownButton("text1"))
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

    def _edges_at(self, pos: QPoint) -> Qt.Edge:
        if self._window.isMaximized():
            return Qt.Edge(0)
        return _resize_edges(pos, self.width(), self.height(), top=True, bottom=False)

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
            self.setCursor(_cursor_for_edges(self._edges_at(event.position().toPoint())))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self.childAt(event.position().toPoint()) is None:
            self._window.toggle_maximize()
        super().mouseDoubleClickEvent(event)


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowTitle("in-reach")
        self.setWindowIcon(icons.app_icon())
        self.setMouseTracking(True)

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

        body = QWidget()
        body.setMouseTracking(True)
        body_layout = QHBoxLayout(body)
        # Every top-level region (activity bar, sidebar, main panel, bottom panel) is its own
        # bordered/rounded card -- this margin/spacing is the window-background gap left around
        # and between them, so the rounding reads as rounded instead of flush against a neighbor.
        # It also happens to be exactly where the bottom/left/right edge-resize grab area lives --
        # see mousePressEvent()/mouseMoveEvent() below.
        body_layout.setContentsMargins(style.PANEL_GAP, style.PANEL_GAP, style.PANEL_GAP, style.PANEL_GAP)
        body_layout.setSpacing(style.PANEL_GAP)
        outer.addWidget(body, 1)

        self.activity_bar = ActivityBar()
        body_layout.addWidget(self.activity_bar)

        self._side_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._side_splitter.setStyleSheet(style.GAP_SPLITTER_HANDLE_STYLE)
        self._side_splitter.setHandleWidth(style.SIDEBAR_CONTENT_GAP)
        body_layout.addWidget(self._side_splitter, 1)

        self.primary_sidebar = self._build_primary_sidebar()
        self._side_splitter.addWidget(self.primary_sidebar)

        self._main_splitter = QSplitter(Qt.Orientation.Vertical)
        self._main_splitter.setStyleSheet(style.GAP_SPLITTER_HANDLE_STYLE)
        self._main_splitter.setHandleWidth(style.PANEL_GAP)
        self._side_splitter.addWidget(self._main_splitter)
        self._side_splitter.setStretchFactor(0, 0)
        self._side_splitter.setStretchFactor(1, 1)
        self._side_splitter.setSizes([220, 1000])

        self.main_panel = MainPanelArea()
        self._main_splitter.addWidget(self.main_panel)

        self.bottom_panel = BottomPanel()
        self._bottom_panel_card = style.wrap_tab_widget(self.bottom_panel)
        self._main_splitter.addWidget(self._bottom_panel_card)
        self._main_splitter.setStretchFactor(0, 1)
        self._main_splitter.setStretchFactor(1, 0)
        self._main_splitter.setSizes([700, 200])

        self.status_bar = StatusBar()
        outer.addWidget(self.status_bar)

        self.quick_access = QuickAccessBar(self)
        QShortcut(QKeySequence("Ctrl+P"), self, activated=self._open_quick_access)
        QShortcut(QKeySequence("Ctrl+Shift+P"), self, activated=self._open_quick_access_command_mode)

        self.activity_bar.search_toggled.connect(self._set_primary_sidebar_visible)
        self.top_bar.sidebar_toggle.toggled.connect(self._set_primary_sidebar_visible)
        self.top_bar.panel_toggle.toggled.connect(self._bottom_panel_card.setVisible)
        self.top_bar.minimize_button.clicked.connect(self.showMinimized)
        self.top_bar.maximize_button.clicked.connect(self.toggle_maximize)
        self.top_bar.close_button.clicked.connect(self.close)

        self.refresh_icon_colors()

    def _build_primary_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setMinimumWidth(_SIDEBAR_MIN_WIDTH)
        sidebar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sidebar.setStyleSheet(style.PANEL_BORDER_STYLE)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(QLabel("Search"))
        layout.addStretch(1)
        return sidebar

    def _set_primary_sidebar_visible(self, visible: bool) -> None:
        self.primary_sidebar.setVisible(visible)
        self.activity_bar.set_primary_sidebar_open(visible)
        self.top_bar.sidebar_toggle.blockSignals(True)
        self.top_bar.sidebar_toggle.setChecked(visible)
        self.top_bar.sidebar_toggle.blockSignals(False)

    def _open_quick_access(self) -> None:
        self.quick_access.open()

    def _open_quick_access_command_mode(self) -> None:
        self.quick_access.open(command_mode=True)

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

    def refresh_icon_colors(self) -> None:
        """Re-renders the top bar's icon buttons in the current theme's window-text color.

        Must be called again after a live theme switch (the first-run dialog's own theme buttons),
        since :func:`in_reach.ide.icons.icon` bakes a fixed color into the pixmap rather than
        tracking a live QPalette.
        """
        color = self.palette().color(QPalette.ColorRole.WindowText).name()
        for button in self.top_bar.icon_buttons():
            icon_name = button.property("_icon_name")
            if button is self.top_bar.maximize_button:
                icon_name = "win_restore" if self.isMaximized() else "win_maximize"
            button.setIcon(icons.icon(icon_name, color=color, size=_ICON_SIZE))

    def on_theme_applied(self, theme: Theme) -> None:
        """Refreshes every bit of chrome that a live theme switch doesn't drive automatically via
        QPalette alone: the top bar's icon colors and the status bar's accent color."""
        self.status_bar.set_color(theme.status_bar_color)
        self.refresh_icon_colors()

    def _edges_at(self, pos: QPoint) -> Qt.Edge:
        if self.isMaximized():
            return Qt.Edge(0)
        return _resize_edges(pos, self.width(), self.height(), top=False, bottom=True)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._edges_at(event.position().toPoint())
            window_handle = self.windowHandle()
            if edges and window_handle is not None:
                window_handle.startSystemResize(edges)
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not bool(event.buttons() & Qt.MouseButton.LeftButton):
            self.setCursor(_cursor_for_edges(self._edges_at(event.position().toPoint())))
        super().mouseMoveEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: ANN001 -- QResizeEvent, matches base signature
        super().resizeEvent(event)
        if self.quick_access.isVisible():
            self.quick_access.reposition()
