"""The main tab panel: a stub 3-tab view that can be split horizontally (max 2 splits -> 3
side-by-side pane-groups) and, independently, each pane-group can be split vertically once (max 2
stacked panes per group) -- so the area tops out at 3 x 2 = 6 panes. Tabs can be dragged from any
pane into any other, regardless of which group they belong to.
"""

from __future__ import annotations

from PyQt6.QtCore import QMimeData, QPoint, Qt
from PyQt6.QtGui import QDrag, QDragEnterEvent, QDragMoveEvent, QDropEvent, QMouseEvent
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSplitter,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from in_reach.ide import icons, style

_MIME_TYPE = "application/x-inreach-tab"
_MAX_H_SPLITS = 2  # -> up to 3 pane-groups side by side
_MAX_V_SPLITS = 1  # -> up to 2 panes stacked within one group
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
    """One pane of the main panel area -- a plain tab strip that accepts a tab dragged in from a
    sibling pane, with a corner widget offering both a horizontal and a vertical split button."""

    def __init__(self, area: "MainPanelArea", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._area = area
        self.group: "_PaneGroup | None" = None  # set by _PaneGroup.add_pane()
        self.card: QWidget | None = None  # set by _PaneGroup.add_pane()
        self.setTabBar(_DragTabBar(self))
        self.setMovable(True)
        self.setAcceptDrops(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(style.TAB_PANEL_BORDER_STYLE)

        self.vsplit_button = QToolButton()
        self.vsplit_button.setIcon(icons.icon("split_vertical", color=_SPLIT_ICON_COLOR, size=16))
        self.vsplit_button.setToolTip("Split panel down")
        self.vsplit_button.setAutoRaise(True)
        self.vsplit_button.clicked.connect(lambda: self._area.vsplit_from(self))

        self.split_button = QToolButton()
        self.split_button.setIcon(icons.icon("split", color=_SPLIT_ICON_COLOR, size=16))
        self.split_button.setToolTip("Split panel right")
        self.split_button.setAutoRaise(True)
        self.split_button.clicked.connect(lambda: self._area.split_from(self))

        corner = QWidget()
        corner_layout = QHBoxLayout(corner)
        corner_layout.setContentsMargins(0, 0, 0, 0)
        corner_layout.setSpacing(0)
        corner_layout.addWidget(self.vsplit_button)
        corner_layout.addWidget(self.split_button)
        self.setCornerWidget(corner, Qt.Corner.TopRightCorner)

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


class _PaneGroup(QWidget):
    """One horizontal slot of the main panel area -- a vertical splitter holding one or two
    :class:`TabPane`s (a second one added via a pane's "split vertical" button)."""

    def __init__(self, area: "MainPanelArea") -> None:
        super().__init__()
        self._area = area
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setStyleSheet(style.GAP_SPLITTER_HANDLE_STYLE)
        self.splitter.setHandleWidth(style.PANEL_GAP)
        layout.addWidget(self.splitter)

        self.panes: list[TabPane] = []

    @property
    def vsplit_count(self) -> int:
        return len(self.panes) - 1

    def add_pane(self, pane: TabPane) -> None:
        pane.group = self
        pane.card = style.wrap_tab_widget(pane)
        self.splitter.addWidget(pane.card)
        self.panes.append(pane)
        self._equalize()

    def remove_pane(self, pane: TabPane) -> None:
        self.panes.remove(pane)
        card = pane.card
        card.setParent(None)
        card.deleteLater()
        self._equalize()

    def _equalize(self) -> None:
        count = self.splitter.count()
        if count <= 0:
            return
        total = max(self.splitter.height(), count * 150)
        self.splitter.setSizes([total // count] * count)


class MainPanelArea(QWidget):
    """Holds one or more :class:`_PaneGroup` instances side by side in a horizontal splitter, up
    to :data:`_MAX_H_SPLITS` horizontal splits, each in turn holding up to one vertical split."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setStyleSheet(style.GAP_SPLITTER_HANDLE_STYLE)
        self._splitter.setHandleWidth(style.PANEL_GAP)
        layout.addWidget(self._splitter)

        self.groups: list[_PaneGroup] = []
        first_group = self._new_group()
        first_pane = self._new_pane()
        for n in (1, 2, 3):
            first_pane.addTab(_stub_tab_content(f"Tab {n}"), f"Tab {n}")
        first_group.add_pane(first_pane)
        self._add_group(first_group)

    @property
    def panes(self) -> list[TabPane]:
        return [pane for group in self.groups for pane in group.panes]

    @property
    def split_count(self) -> int:
        """Horizontal split count -- ``len(self.groups) - 1``."""
        return len(self.groups) - 1

    def _new_pane(self) -> TabPane:
        return TabPane(self)

    def _new_group(self) -> _PaneGroup:
        return _PaneGroup(self)

    def _add_group(self, group: _PaneGroup) -> None:
        self._splitter.addWidget(group)
        self.groups.append(group)
        self._equalize_groups()
        self._update_split_buttons()

    def _equalize_groups(self) -> None:
        count = self._splitter.count()
        if count <= 0:
            return
        total = max(self._splitter.width(), count * 200)
        self._splitter.setSizes([total // count] * count)

    def _update_split_buttons(self) -> None:
        can_hsplit = self.split_count < _MAX_H_SPLITS
        for group in self.groups:
            can_vsplit = group.vsplit_count < _MAX_V_SPLITS
            for pane in group.panes:
                pane.split_button.setEnabled(can_hsplit)
                pane.vsplit_button.setEnabled(can_vsplit)

    def split_from(self, source: TabPane) -> None:
        """Horizontal split: adds a new, empty pane-group beside ``source``'s own group."""
        if self.split_count >= _MAX_H_SPLITS:
            return
        new_group = self._new_group()
        new_group.add_pane(self._new_pane())
        self._add_group(new_group)

    def vsplit_from(self, source: TabPane) -> None:
        """Vertical split: adds a new, empty pane stacked within ``source``'s own group."""
        group = source.group
        if group is None or group.vsplit_count >= _MAX_V_SPLITS:
            return
        group.add_pane(self._new_pane())
        self._update_split_buttons()

    def find_pane(self, pane_id: int) -> TabPane | None:
        for pane in self.panes:
            if id(pane) == pane_id:
                return pane
        return None

    def on_pane_emptied(self, pane: TabPane) -> None:
        """Called after a tab is dragged out of ``pane`` -- removes it (and its group, if that was
        the group's last pane) unless it's the very last pane in the whole area."""
        if pane.count() != 0 or len(self.panes) <= 1:
            return

        group = pane.group
        group.remove_pane(pane)
        if group.panes:
            group._equalize()
        else:
            self.groups.remove(group)
            group.setParent(None)
            group.deleteLater()
            self._equalize_groups()
        self._update_split_buttons()
