"""VSCode-shaped main window: a frameless custom top bar (dropdown menus, sidebar/panel toggles,
window controls), a fixed activity bar, a toggleable primary sidebar, and a split-capable main
panel above a toggleable bottom panel.
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QMouseEvent, QPalette
from PyQt6.QtWidgets import (
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
from in_reach.ide.tabs import MainPanelArea

_TOP_BAR_HEIGHT = 36
_ICON_SIZE = 16
_WINDOW_BUTTON_WIDTH = 46
_SIDEBAR_MIN_WIDTH = 180


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
    """The custom title-bar row: dropdown menus on the left, sidebar/panel toggles and window
    controls on the right. Dragging empty space moves the (frameless) window; double-clicking it
    toggles maximize, same as a native title bar."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self._window = window
        self._drag_offset: QPoint | None = None
        self.setFixedHeight(_TOP_BAR_HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background-color: palette(window);")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(4)

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

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.childAt(event.position().toPoint()) is None:
            self._drag_offset = event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and bool(event.buttons() & Qt.MouseButton.LeftButton):
            if self._window.isMaximized():
                self._window.toggle_maximize()
                self._drag_offset = QPoint(self._window.width() // 2, self.height() // 2)
            self._window.move(event.globalPosition().toPoint() - self._drag_offset)
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

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.top_bar = _TopBar(self)
        outer.addWidget(self.top_bar)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        # Every top-level region (activity bar, sidebar, main panel, bottom panel) is its own
        # bordered/rounded card -- this margin/spacing is the window-background gap left around
        # and between them, so the rounding reads as rounded instead of flush against a neighbor.
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

    def toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
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
