from PyQt6.QtCore import QPoint, Qt

from in_reach.ide.window_resize import RESIZE_MARGIN, cursor_for_edges, resize_edges

_W, _H = 200, 100


def test_resize_edges_detects_left_and_right() -> None:
    assert resize_edges(QPoint(0, 50), _W, _H, top=False, bottom=False) == Qt.Edge.LeftEdge
    assert resize_edges(QPoint(_W - 1, 50), _W, _H, top=False, bottom=False) == Qt.Edge.RightEdge


def test_resize_edges_gates_top_and_bottom_on_the_flags() -> None:
    # Right at the top/bottom edge, but the caller says it can't claim that side.
    assert resize_edges(QPoint(100, 0), _W, _H, top=False, bottom=False) == Qt.Edge(0)
    assert resize_edges(QPoint(100, _H - 1), _W, _H, top=False, bottom=False) == Qt.Edge(0)

    assert resize_edges(QPoint(100, 0), _W, _H, top=True, bottom=False) == Qt.Edge.TopEdge
    assert resize_edges(QPoint(100, _H - 1), _W, _H, top=False, bottom=True) == Qt.Edge.BottomEdge


def test_resize_edges_detects_corners_as_combined_flags() -> None:
    assert (
        resize_edges(QPoint(0, 0), _W, _H, top=True, bottom=False)
        == Qt.Edge.TopEdge | Qt.Edge.LeftEdge
    )
    assert (
        resize_edges(QPoint(_W - 1, _H - 1), _W, _H, top=False, bottom=True)
        == Qt.Edge.BottomEdge | Qt.Edge.RightEdge
    )


def test_resize_edges_is_empty_away_from_any_edge() -> None:
    assert resize_edges(QPoint(_W // 2, _H // 2), _W, _H, top=True, bottom=True) == Qt.Edge(0)


def test_resize_edges_respects_the_margin_boundary() -> None:
    assert resize_edges(QPoint(RESIZE_MARGIN, 50), _W, _H, top=False, bottom=False) == Qt.Edge.LeftEdge
    assert (
        resize_edges(QPoint(RESIZE_MARGIN + 1, 50), _W, _H, top=False, bottom=False) == Qt.Edge(0)
    )


def test_cursor_for_edges_maps_diagonal_combinations() -> None:
    assert cursor_for_edges(Qt.Edge.TopEdge | Qt.Edge.LeftEdge) == Qt.CursorShape.SizeFDiagCursor
    assert cursor_for_edges(Qt.Edge.BottomEdge | Qt.Edge.RightEdge) == Qt.CursorShape.SizeFDiagCursor
    assert cursor_for_edges(Qt.Edge.TopEdge | Qt.Edge.RightEdge) == Qt.CursorShape.SizeBDiagCursor
    assert cursor_for_edges(Qt.Edge.BottomEdge | Qt.Edge.LeftEdge) == Qt.CursorShape.SizeBDiagCursor


def test_cursor_for_edges_maps_straight_edges() -> None:
    assert cursor_for_edges(Qt.Edge.LeftEdge) == Qt.CursorShape.SizeHorCursor
    assert cursor_for_edges(Qt.Edge.RightEdge) == Qt.CursorShape.SizeHorCursor
    assert cursor_for_edges(Qt.Edge.TopEdge) == Qt.CursorShape.SizeVerCursor
    assert cursor_for_edges(Qt.Edge.BottomEdge) == Qt.CursorShape.SizeVerCursor


def test_cursor_for_edges_is_arrow_when_no_edges() -> None:
    assert cursor_for_edges(Qt.Edge(0)) == Qt.CursorShape.ArrowCursor
