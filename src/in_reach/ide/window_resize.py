"""Shared edge/cursor math for hand-implemented frameless-window resizing, used by every widget
that tiles part of the window's outer edge (the top bar's top edge, the body's left/right edges,
the status bar's bottom edge) -- split out from ``main_window.py`` so ``status_bar.py`` can use it
without importing ``main_window`` (which imports ``StatusBar``) and creating a cycle.
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt

RESIZE_MARGIN = 6


def resize_edges(pos: QPoint, width: int, height: int, *, top: bool, bottom: bool) -> Qt.Edge:
    """Which window edge(s) ``pos`` (widget-local) falls within :data:`RESIZE_MARGIN` of, as an
    OR'd :class:`Qt.Edge` flag combination suitable for :meth:`QWindow.startSystemResize`.
    ``top``/``bottom`` gate whether that particular edge is even reachable from the calling widget
    (the top bar only ever reports its own top/corners; the status bar only bottom/corners; the
    window body in between reports neither, only left/right)."""
    edges = Qt.Edge(0)
    if top and pos.y() <= RESIZE_MARGIN:
        edges |= Qt.Edge.TopEdge
    if bottom and pos.y() >= height - RESIZE_MARGIN:
        edges |= Qt.Edge.BottomEdge
    if pos.x() <= RESIZE_MARGIN:
        edges |= Qt.Edge.LeftEdge
    if pos.x() >= width - RESIZE_MARGIN:
        edges |= Qt.Edge.RightEdge
    return edges


def cursor_for_edges(edges: Qt.Edge) -> Qt.CursorShape:
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
