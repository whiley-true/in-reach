"""A from-scratch replacement for ``QSplitter`` used to arrange split panes/pane-groups.

PROMPT.md: "if i have two tabs open (1 on welcome and one on any json) and i close the welcome,
things crash" -- turned out to reproduce identically just from *manually dragging* either of
``tabs.py``'s two ``QSplitter``s (between stacked panes in a group, and between side-by-side
pane-groups), independent of tab-closing or file type: a real, native access-violation crash deep
inside Qt6Core's own ``QObject::metaObject()`` (confirmed via minidump analysis -- a cached
"dynamic meta-object" pointer read as ``-1`` instead of null/valid), persisting across two
different PyQt6/Qt6 versions and two Python versions, and reproducible only via genuine
mouse-driven dragging of a real ``QSplitterHandle`` -- every scripted/synthetic resize attempt
(``setSizes()``, ``moveSplitter()``, even ``QTest``-synthesized mouse events on the real handle)
consistently failed to reproduce it. ``setOpaqueResize(False)`` (still live child-widget resizing,
but only once, on release, instead of continuously through the drag) measurably changed the
crash's own exact signature between attempts but never stopped it outright.

With no way to inspect or patch ``QSplitterHandle``'s own closed-source implementation, and every
angle of *working around* it exhausted, :class:`PaneSplitter` (plus :class:`_DragHandle`) replaces
it outright: a plain ``QWidget`` that positions its children with direct ``setGeometry()`` calls
instead of a real ``QLayout``, with its own minimal press/move/release handling standing in for
``QSplitterHandle`` entirely. This never constructs a real ``QSplitter``/``QSplitterHandle``
anywhere, so whatever internal Qt6 state that widget's own drag-handling was corrupting never gets
a chance to be touched in the first place.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QResizeEvent
from PyQt6.QtWidgets import QSizePolicy, QWidget

#: A pane dragged down to (or past) its neighbor's edge must not be able to collapse it away to
#: nothing -- only the tab-close/auto-close path should ever actually remove a pane/group (see
#: :meth:`PaneSplitter.setChildrenCollapsible`).
_MIN_PANE_SIZE = 40


class _DragHandle(QWidget):
    """The thin, transparent strip between two panes -- entirely our own press/move/release
    handling (see module docstring for why this doesn't just subclass/reuse ``QSplitterHandle``).

    Reports the *total* pixel delta since the press on every move (not an incremental, move-to-move
    one) -- :meth:`PaneSplitter._on_dragged` applies each one against the sizes captured once at
    press time, the same anchor-at-press-not-at-last-position technique
    :class:`~in_reach.ide.editor._Minimap`'s own drag handling already uses, so rounding never
    compounds across a long drag.
    """

    dragged = pyqtSignal(int)
    drag_finished = pyqtSignal()

    def __init__(self, orientation: Qt.Orientation, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._orientation = orientation
        # Never takes keyboard focus -- a click on the handle (to start a drag) has no reason to
        # steal focus away from whatever editor/tab already had it.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(
            Qt.CursorShape.SplitHCursor
            if orientation == Qt.Orientation.Horizontal
            else Qt.CursorShape.SplitVCursor
        )
        self._press_pos: QPointF | None = None

    def set_thickness(self, thickness: int) -> None:
        if self._orientation == Qt.Orientation.Horizontal:
            self.setFixedWidth(thickness)
        else:
            self.setFixedHeight(thickness)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.globalPosition()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._press_pos is None:
            return
        current = event.globalPosition()
        delta = (
            current.x() - self._press_pos.x()
            if self._orientation == Qt.Orientation.Horizontal
            else current.y() - self._press_pos.y()
        )
        self.dragged.emit(round(delta))
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._press_pos is not None:
            self._press_pos = None
            self.drag_finished.emit()
        event.accept()


class PaneSplitter(QWidget):
    """Arranges its children side by side (or stacked), separated by draggable
    :class:`_DragHandle`s -- a drop-in-enough replacement for the handful of ``QSplitter`` methods
    ``tabs.py`` actually used (``addWidget``/``count``/``widget``/``sizes``/``setSizes``/
    ``setHandleWidth``/``setChildrenCollapsible``/``setOpaqueResize``), plus a new
    ``removeWidget()`` -- unlike a real ``QSplitter``, reparenting a child away doesn't
    automatically drop it from this splitter's own bookkeeping, so callers that used to just
    ``widget.setParent(None)`` now call ``removeWidget(widget)`` first (see ``tabs.py``'s own
    ``remove_pane``/group-removal call sites).
    """

    def __init__(self, orientation: Qt.Orientation, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._orientation = orientation
        self._widgets: list[QWidget] = []
        self._handles: list[_DragHandle] = []
        self._sizes: list[int] = []
        self._handle_width = 1
        self._collapsible = True
        self._drag_start_sizes: list[int] | None = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    # -- QSplitter-compatible surface ------------------------------------------------------------

    def setHandleWidth(self, width: int) -> None:
        self._handle_width = width
        for handle in self._handles:
            handle.set_thickness(width)
        self._relayout()

    def setChildrenCollapsible(self, collapsible: bool) -> None:
        self._collapsible = collapsible

    def childrenCollapsible(self) -> bool:
        return self._collapsible

    def setOpaqueResize(self, opaque: bool) -> None:
        # No live/indicator-line distinction here -- see module docstring: every resize this
        # widget ever does comes from _DragHandle's own press/move/release, never QSplitterHandle's,
        # so the crash-prone code path opaqueResize(False) used to merely reduce the frequency of
        # (but never fully avoid) simply never exists in the first place. Kept as a no-op purely so
        # tabs.py's existing setOpaqueResize(False) call doesn't need to be ripped out too.
        pass

    def opaqueResize(self) -> bool:
        return False

    def count(self) -> int:
        return len(self._widgets)

    def widget(self, index: int) -> QWidget:
        return self._widgets[index]

    def sizes(self) -> list[int]:
        return list(self._sizes)

    def setSizes(self, sizes: list[int]) -> None:
        if len(sizes) != len(self._widgets):
            return
        self._sizes = list(sizes)
        self._relayout()

    def addWidget(self, widget: QWidget) -> None:
        if self._widgets:
            handle = _DragHandle(self._orientation, self)
            handle.set_thickness(self._handle_width)
            index = len(self._handles)
            handle.dragged.connect(lambda delta, i=index: self._on_dragged(i, delta))
            handle.drag_finished.connect(self._on_drag_finished)
            handle.show()
            self._handles.append(handle)
        widget.setParent(self)
        widget.show()
        self._widgets.append(widget)
        self._sizes = self._equal_sizes(len(self._widgets))
        self._relayout()

    def removeWidget(self, widget: QWidget) -> None:
        """Drops ``widget`` from this splitter's own bookkeeping -- unlike a real ``QSplitter``,
        this does *not* itself reparent/delete ``widget``; call this before (not instead of) the
        usual ``widget.setParent(None)``/``deleteLater()``."""
        if widget not in self._widgets:
            return
        index = self._widgets.index(widget)
        self._widgets.pop(index)
        if self._sizes:
            self._sizes.pop(min(index, len(self._sizes) - 1))
        # Drop whichever adjoining handle sat *after* the removed widget, unless it was the last
        # one, in which case there is no "after" -- drop the one *before* it instead.
        handle_index = index if index < len(self._handles) else index - 1
        if 0 <= handle_index < len(self._handles):
            handle = self._handles.pop(handle_index)
            handle.setParent(None)
            handle.deleteLater()
        # Rescales the remaining sizes to fill whatever space the removed widget (and its dropped
        # handle) leaves behind -- same "stretch to fit" logic resizeEvent() already uses, so a
        # bare removeWidget() alone never leaves the survivors under-filling the container.
        self._relayout(rescale=True)

    # -- layout -----------------------------------------------------------------------------------

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._relayout(rescale=True)

    def _main_axis_size(self) -> int:
        return self.width() if self._orientation == Qt.Orientation.Horizontal else self.height()

    def _available_main_axis_size(self, count: int) -> int:
        return max(0, self._main_axis_size() - self._handle_width * max(0, count - 1))

    def _min_size(self) -> int:
        return _MIN_PANE_SIZE if not self._collapsible else 0

    def _equal_sizes(self, count: int) -> list[int]:
        if count <= 0:
            return []
        available = self._available_main_axis_size(count)
        base = available // count
        sizes = [base] * count
        sizes[-1] += available - base * count
        return sizes

    def _on_dragged(self, handle_index: int, delta: int) -> None:
        if self._drag_start_sizes is None:
            self._drag_start_sizes = list(self._sizes)
        left, right = handle_index, handle_index + 1
        if right >= len(self._drag_start_sizes):
            return
        min_size = self._min_size()
        new_left = self._drag_start_sizes[left] + delta
        new_right = self._drag_start_sizes[right] - delta
        if new_left < min_size:
            new_right -= min_size - new_left
            new_left = min_size
        if new_right < min_size:
            new_left -= min_size - new_right
            new_right = min_size
        if new_left < 0 or new_right < 0:
            return  # container too small to honor even the minimum -- leave sizes untouched
        sizes = list(self._sizes)
        sizes[left] = new_left
        sizes[right] = new_right
        self._sizes = sizes
        self._relayout()

    def _on_drag_finished(self) -> None:
        self._drag_start_sizes = None

    def _relayout(self, *, rescale: bool = False) -> None:
        count = len(self._widgets)
        if count == 0:
            return
        if len(self._sizes) != count:
            self._sizes = self._equal_sizes(count)
        elif rescale:
            available = self._available_main_axis_size(count)
            current_total = sum(self._sizes)
            if available > 0 and current_total > 0:
                scaled = [max(0, round(size * available / current_total)) for size in self._sizes]
                # Rounding every pane individually can drift the total off by a pixel or two --
                # corrected on the last one so the container's own full width/height is always
                # exactly accounted for.
                scaled[-1] += available - sum(scaled)
                self._sizes = scaled

        pos = 0
        for index, widget in enumerate(self._widgets):
            size = max(0, self._sizes[index])
            if self._orientation == Qt.Orientation.Horizontal:
                widget.setGeometry(pos, 0, size, self.height())
            else:
                widget.setGeometry(0, pos, self.width(), size)
            pos += size
            if index < len(self._handles):
                handle = self._handles[index]
                if self._orientation == Qt.Orientation.Horizontal:
                    handle.setGeometry(pos, 0, self._handle_width, self.height())
                else:
                    handle.setGeometry(0, pos, self.width(), self._handle_width)
                pos += self._handle_width
