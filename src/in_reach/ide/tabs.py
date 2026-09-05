"""The main tab panel: a stub 8-tab view that can be split horizontally (max 2 splits -> 3
side-by-side pane-groups) and, independently, each pane-group can be split vertically once (max 2
stacked panes per group) -- so the area tops out at 3 x 2 = 6 panes. Splitting duplicates the
source pane's current tab into the new pane (VSCode's "split editor" behavior) rather than leaving
it empty. Tabs are closable and reorderable within a pane, and draggable from any pane into any
other, regardless of which group they belong to.
"""

from __future__ import annotations

from PyQt6.QtCore import QMimeData, Qt
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
_INITIAL_TAB_COUNT = 8
_SPLIT_ICON_COLOR = "#808080"


def _stub_tab_content(label: str) -> QWidget:
    widget = QLabel(f"{label} content")
    widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return widget


class _DragTabBar(QTabBar):
    """A QTabBar that starts a cross-pane drag (carrying the owning pane's id + tab index) once
    the mouse leaves the tab bar's own bounds while dragging a tab -- reordering *within* the bar
    is left entirely to Qt's own built-in movable-tab handling (``setMovable(True)``), so any drag
    that stays inside the bar falls through to the base implementation untouched."""

    def __init__(self, pane: "TabPane") -> None:
        super().__init__(pane)
        self._pane = pane
        self._drag_start_index: int | None = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_index = self.tabAt(event.position().toPoint())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        index = self._drag_start_index
        if (
            index is not None
            and index >= 0
            and bool(event.buttons() & Qt.MouseButton.LeftButton)
            and not self.rect().contains(event.position().toPoint())
        ):
            self._drag_start_index = None
            self._start_drag(index)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_start_index = None
        super().mouseReleaseEvent(event)

    def _start_drag(self, index: int) -> None:
        mime = QMimeData()
        mime.setData(_MIME_TYPE, f"{id(self._pane)}:{index}".encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)


class TabPane(QTabWidget):
    """One pane of the main panel area -- a closable, reorderable tab strip that accepts a tab
    dragged in from a sibling pane, with a corner widget offering both a horizontal and a vertical
    split button."""

    def __init__(self, area: "MainPanelArea", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._area = area
        self.group: "_PaneGroup | None" = None  # set by _PaneGroup.add_pane()
        self.card: QWidget | None = None  # set by _PaneGroup.add_pane()
        self.setTabBar(_DragTabBar(self))
        self.setMovable(True)
        self.setTabsClosable(True)
        self.tabCloseRequested.connect(self._close_tab)
        self.setAcceptDrops(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
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

    def _close_tab(self, index: int) -> None:
        widget = self.widget(index)
        self.removeTab(index)
        if widget is not None:
            widget.deleteLater()
        self._area.on_pane_emptied(self)

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
            # A same-pane drag never reaches here -- see _DragTabBar's own docstring -- but guard
            # against it anyway rather than duplicating the tab.
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
        # A pane dragged down to (or past) its neighbor's edge must not be able to collapse it to
        # zero height -- only the tab-close/auto-close path should ever remove a pane.
        self.splitter.setChildrenCollapsible(False)
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
        # Same reasoning as _PaneGroup.splitter above -- in particular, this is what stops the
        # leftmost pane-group from being drag-resized down to zero width (effectively hiding it).
        self._splitter.setChildrenCollapsible(False)
        layout.addWidget(self._splitter)

        self.groups: list[_PaneGroup] = []
        first_group = self._new_group()
        first_pane = self._new_pane()
        for n in range(1, _INITIAL_TAB_COUNT + 1):
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

    def _duplicate_current_tab(self, source: TabPane, target: TabPane) -> None:
        """Splitting a pane duplicates its current tab into the new pane, rather than leaving the
        new pane empty -- matching e.g. VSCode's "split editor" behavior. Stub content only, so
        "duplicate" just means a fresh stub widget carrying the same label."""
        index = source.currentIndex()
        if index < 0:
            return
        label = source.tabText(index)
        target.addTab(_stub_tab_content(label), label)

    def split_from(self, source: TabPane) -> None:
        """Horizontal split: adds a new pane-group beside ``source``'s own group, seeded with a
        duplicate of ``source``'s current tab."""
        if self.split_count >= _MAX_H_SPLITS:
            return
        new_group = self._new_group()
        new_pane = self._new_pane()
        self._duplicate_current_tab(source, new_pane)
        new_group.add_pane(new_pane)
        self._add_group(new_group)

    def vsplit_from(self, source: TabPane) -> None:
        """Vertical split: adds a new pane stacked within ``source``'s own group, seeded with a
        duplicate of ``source``'s current tab."""
        group = source.group
        if group is None or group.vsplit_count >= _MAX_V_SPLITS:
            return
        new_pane = self._new_pane()
        self._duplicate_current_tab(source, new_pane)
        group.add_pane(new_pane)
        self._update_split_buttons()

    def find_pane(self, pane_id: int) -> TabPane | None:
        for pane in self.panes:
            if id(pane) == pane_id:
                return pane
        return None

    def on_pane_emptied(self, pane: TabPane) -> None:
        """Called after a tab is dragged or closed out of ``pane`` -- removes it (and its group, if
        that was the group's last pane) unless it's the very last pane in the whole area."""
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
