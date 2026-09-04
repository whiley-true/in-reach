"""The main tab panel: a stub 3-tab view that can be split (max 3 splits) and whose tabs can be
dragged from one split pane into another.
"""

from __future__ import annotations

from PyQt6.QtCore import QMimeData, QPoint, Qt
from PyQt6.QtGui import QDrag, QDragEnterEvent, QDragMoveEvent, QDropEvent, QMouseEvent
from PyQt6.QtWidgets import QLabel, QSplitter, QTabBar, QTabWidget, QToolButton, QVBoxLayout, QWidget

from in_reach.ide import icons, style

_MIME_TYPE = "application/x-inreach-tab"
_MAX_SPLITS = 3
_DRAG_START_DISTANCE = 10
_SPLIT_ICON_COLOR = "#808080"


def _stub_tab_content(label: str) -> QWidget:
    widget = QLabel(f"{label} content")
    widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return widget


class _DragTabBar(QTabBar):
    """A QTabBar that starts a drag (carrying the owning pane's id + tab index) once the mouse
    moves far enough from where a tab was pressed."""

    def __init__(self, pane: "TabPane") -> None:
        super().__init__(pane)
        self._pane = pane
        self._drag_start_pos: QPoint | None = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        start = self._drag_start_pos
        if (
            start is not None
            and bool(event.buttons() & Qt.MouseButton.LeftButton)
            and (event.position().toPoint() - start).manhattanLength() >= _DRAG_START_DISTANCE
        ):
            index = self.tabAt(start)
            self._drag_start_pos = None
            if index >= 0:
                self._start_drag(index)
                return
        super().mouseMoveEvent(event)

    def _start_drag(self, index: int) -> None:
        mime = QMimeData()
        mime.setData(_MIME_TYPE, f"{id(self._pane)}:{index}".encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)


class TabPane(QTabWidget):
    """One split pane of the main panel area -- a plain tab strip that accepts a tab dragged in
    from a sibling pane."""

    def __init__(self, area: "MainPanelArea", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._area = area
        self.card: QWidget | None = None  # set by MainPanelArea._add_pane()
        self.setTabBar(_DragTabBar(self))
        self.setMovable(True)
        self.setAcceptDrops(True)
        self.setStyleSheet(style.TAB_PANEL_BORDER_STYLE)

        self.split_button = QToolButton()
        self.split_button.setIcon(icons.icon("split", color=_SPLIT_ICON_COLOR, size=16))
        self.split_button.setToolTip("Split panel")
        self.split_button.setAutoRaise(True)
        self.split_button.clicked.connect(lambda: self._area.split_from(self))
        self.setCornerWidget(self.split_button, Qt.Corner.TopRightCorner)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(_MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasFormat(_MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        mime = event.mimeData()
        if not mime.hasFormat(_MIME_TYPE):
            super().dropEvent(event)
            return

        pane_id_str, index_str = bytes(mime.data(_MIME_TYPE)).decode("utf-8").split(":")
        source = self._area.find_pane(int(pane_id_str))
        index = int(index_str)
        if source is None or source is self:
            event.ignore()
            return

        label = source.tabText(index)
        content = source.widget(index)
        source.removeTab(index)
        new_index = self.addTab(content, label)
        self.setCurrentIndex(new_index)
        self._area.on_pane_emptied(source)
        event.acceptProposedAction()


class MainPanelArea(QWidget):
    """Holds one or more :class:`TabPane` instances side by side in a horizontal splitter, up to
    :data:`_MAX_SPLITS` splits (``_MAX_SPLITS + 1`` panes total)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setStyleSheet(style.GAP_SPLITTER_HANDLE_STYLE)
        self._splitter.setHandleWidth(style.PANEL_GAP)
        layout.addWidget(self._splitter)

        self.panes: list[TabPane] = []
        first = self._new_pane()
        for n in (1, 2, 3):
            first.addTab(_stub_tab_content(f"Tab {n}"), f"Tab {n}")
        self._add_pane(first)

    @property
    def split_count(self) -> int:
        return len(self.panes) - 1

    def _new_pane(self) -> TabPane:
        return TabPane(self)

    def _add_pane(self, pane: TabPane) -> None:
        pane.card = style.wrap_tab_widget(pane)
        self._splitter.addWidget(pane.card)
        self.panes.append(pane)
        self._equalize_sizes()
        self._update_split_buttons()

    def _equalize_sizes(self) -> None:
        count = self._splitter.count()
        if count <= 0:
            return
        total = max(self._splitter.width(), count * 200)
        self._splitter.setSizes([total // count] * count)

    def _update_split_buttons(self) -> None:
        can_split = self.split_count < _MAX_SPLITS
        for pane in self.panes:
            pane.split_button.setEnabled(can_split)

    def split_from(self, source: TabPane) -> None:
        """Adds a new, empty pane next to ``source`` -- a tab can then be dragged into it."""
        if self.split_count >= _MAX_SPLITS:
            return
        self._add_pane(self._new_pane())

    def find_pane(self, pane_id: int) -> TabPane | None:
        for pane in self.panes:
            if id(pane) == pane_id:
                return pane
        return None

    def on_pane_emptied(self, pane: TabPane) -> None:
        """Called after a tab is dragged out of ``pane`` -- removes it if it's now empty, unless
        it's the last remaining pane."""
        if pane.count() == 0 and len(self.panes) > 1:
            self.panes.remove(pane)
            card = pane.card
            card.setParent(None)
            card.deleteLater()
            self._equalize_sizes()
            self._update_split_buttons()
