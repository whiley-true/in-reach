from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QWidget

from in_reach.ide.pane_splitter import PaneSplitter, _DragHandle


def _mouse_event(kind: QMouseEvent.Type, global_x: float) -> QMouseEvent:
    pos = QPointF(global_x, 0)
    button = Qt.MouseButton.LeftButton if kind != QMouseEvent.Type.MouseMove else Qt.MouseButton.NoButton
    buttons = Qt.MouseButton.LeftButton
    return QMouseEvent(kind, pos, pos, button, buttons, Qt.KeyboardModifier.NoModifier)


def _drag(handle: _DragHandle, *, from_x: float, to_x: list[float]) -> None:
    handle.mousePressEvent(_mouse_event(QMouseEvent.Type.MouseButtonPress, from_x))
    for x in to_x:
        handle.mouseMoveEvent(_mouse_event(QMouseEvent.Type.MouseMove, x))
    handle.mouseReleaseEvent(_mouse_event(QMouseEvent.Type.MouseButtonRelease, to_x[-1]))


def test_addWidget_splits_evenly(qtbot):
    splitter = PaneSplitter(Qt.Orientation.Horizontal)
    qtbot.addWidget(splitter)
    splitter.setHandleWidth(0)
    splitter.resize(300, 100)

    splitter.addWidget(QWidget())
    splitter.addWidget(QWidget())

    assert splitter.count() == 2
    assert sum(splitter.sizes()) == 300
    assert splitter.sizes()[0] == splitter.sizes()[1]


def test_three_widgets_split_evenly_and_have_two_handles(qtbot):
    splitter = PaneSplitter(Qt.Orientation.Horizontal)
    qtbot.addWidget(splitter)
    splitter.setHandleWidth(8)
    splitter.resize(316, 100)

    for _ in range(3):
        splitter.addWidget(QWidget())

    assert splitter.count() == 3
    assert len(splitter._handles) == 2
    sizes = splitter.sizes()
    assert sum(sizes) + 2 * 8 == 316
    assert sizes[0] == sizes[1] == sizes[2]


def test_set_sizes_repositions_widgets(qtbot):
    splitter = PaneSplitter(Qt.Orientation.Horizontal)
    qtbot.addWidget(splitter)
    splitter.setHandleWidth(4)
    splitter.resize(204, 50)
    a, b = QWidget(), QWidget()
    splitter.addWidget(a)
    splitter.addWidget(b)

    splitter.setSizes([150, 50])

    assert splitter.sizes() == [150, 50]
    assert a.geometry().width() == 150
    assert b.geometry().x() == 154  # after a (150) + the 4px handle
    assert b.geometry().width() == 50


def test_dragging_the_handle_resizes_both_neighbors(qtbot):
    splitter = PaneSplitter(Qt.Orientation.Horizontal)
    qtbot.addWidget(splitter)
    splitter.setHandleWidth(4)
    splitter.resize(300, 50)
    splitter.addWidget(QWidget())
    splitter.addWidget(QWidget())
    start_left, start_right = splitter.sizes()

    handle = splitter._handles[0]
    _drag(handle, from_x=100, to_x=[120, 140])

    left, right = splitter.sizes()
    assert left == start_left + 40
    assert right == start_right - 40


def test_drag_delta_is_measured_from_the_press_not_the_last_move(qtbot):
    # _DragHandle reports the *total* delta since press on every move -- PaneSplitter must apply
    # each one against the sizes captured at press time, not compound them move over move.
    splitter = PaneSplitter(Qt.Orientation.Horizontal)
    qtbot.addWidget(splitter)
    splitter.resize(300, 50)
    splitter.addWidget(QWidget())
    splitter.addWidget(QWidget())
    start_left, _start_right = splitter.sizes()

    handle = splitter._handles[0]
    handle.mousePressEvent(_mouse_event(QMouseEvent.Type.MouseButtonPress, 100))
    handle.mouseMoveEvent(_mouse_event(QMouseEvent.Type.MouseMove, 110))
    handle.mouseMoveEvent(_mouse_event(QMouseEvent.Type.MouseMove, 130))
    handle.mouseReleaseEvent(_mouse_event(QMouseEvent.Type.MouseButtonRelease, 130))

    assert splitter.sizes()[0] == start_left + 30


def test_dragging_past_the_minimum_size_clamps_instead_of_collapsing(qtbot):
    splitter = PaneSplitter(Qt.Orientation.Horizontal)
    qtbot.addWidget(splitter)
    splitter.setHandleWidth(0)
    splitter.setChildrenCollapsible(False)
    splitter.resize(300, 50)
    splitter.addWidget(QWidget())
    splitter.addWidget(QWidget())

    handle = splitter._handles[0]
    _drag(handle, from_x=150, to_x=[290, 500])  # try to drag almost the entire width away

    left, right = splitter.sizes()
    assert left > 0
    assert right > 0
    assert sum(splitter.sizes()) == 300


def test_remove_widget_drops_its_own_bookkeeping_and_relayouts(qtbot):
    splitter = PaneSplitter(Qt.Orientation.Horizontal)
    qtbot.addWidget(splitter)
    splitter.setHandleWidth(4)
    splitter.resize(300, 50)
    a, b, c = QWidget(), QWidget(), QWidget()
    for w in (a, b, c):
        splitter.addWidget(w)

    splitter.removeWidget(b)

    assert splitter.count() == 2
    assert splitter.widget(0) is a
    assert splitter.widget(1) is c
    assert len(splitter._handles) == 1
    assert sum(splitter.sizes()) + 4 == 300


def test_resizing_the_container_rescales_children_proportionally(qtbot):
    splitter = PaneSplitter(Qt.Orientation.Horizontal)
    qtbot.addWidget(splitter)
    splitter.setHandleWidth(0)
    # resizeEvent() is only ever delivered to a widget Qt actually considers visible -- matches how
    # this is always used for real (always a child of an already-shown window), but a bare,
    # never-shown widget in a test needs an explicit show() for the same to hold here.
    splitter.show()
    splitter.resize(200, 50)
    splitter.addWidget(QWidget())
    splitter.addWidget(QWidget())
    splitter.setSizes([150, 50])

    splitter.resize(400, 50)
    QApplication.processEvents()

    left, right = splitter.sizes()
    assert (left, right) == (300, 100)


def test_drag_handle_never_takes_keyboard_focus():
    handle = _DragHandle(Qt.Orientation.Horizontal)
    assert handle.focusPolicy() == Qt.FocusPolicy.NoFocus
