"""A VSCode/``git log --graph``-style commit graph widget (PROMPT.md: "we also want to show a git
graph of commits, branches and stamps instead in vscode style") -- replaces the Git panel's old flat
``QListWidget`` history list with a lane-painted canvas: one dot per commit, a colored vertical lane
per branch, diagonal connectors where two branches share a fork point, a star marker on stamped
commits, and each branch's name labelled at its own tip.

Lane assignment (:func:`compute_lanes`) is plain, framework-free logic over
:func:`~in_reach.app.vcs.graph_history`'s own ``Snapshot.parents``/``Snapshot.branches`` -- kept
separate from :class:`GitGraphWidget`'s painting so it's cheaply unit-testable without a live Qt
event loop. This shadow VCS has no merge functionality at all yet (:mod:`in_reach.app.vcs` never
gives a commit more than one parent), so the only "convergence" a lane ever needs to draw is two
branches sharing a common ancestor further back in history -- never a true multi-parent merge commit
-- which is what keeps this algorithm considerably simpler than a general-purpose one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QMouseEvent, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from in_reach.app.vcs import Snapshot

#: Cycled through by lane index -- distinct enough to tell adjacent lanes apart at a glance, same
#: role as VSCode's own per-branch graph colors.
_LANE_COLORS = [
    "#4FC1FF", "#B180D7", "#FF8A65", "#89D185", "#F0DF6E", "#FF6B9E", "#5CD3C4", "#E8AB53",
]

_ROW_HEIGHT = 28
_LANE_WIDTH = 18
_DOT_RADIUS = 5
_LEFT_MARGIN = 12
_TEXT_GAP = 10


def _lane_color(lane: int) -> QColor:
    return QColor(_LANE_COLORS[lane % len(_LANE_COLORS)])


@dataclass
class LaneRow:
    """One :class:`~in_reach.app.vcs.Snapshot`, positioned into the graph -- everything
    :class:`GitGraphWidget` needs to paint one row without re-deriving lane topology itself."""

    snapshot: Snapshot
    lane: int
    #: Lanes (from the row directly above) that connect down into this row's own :attr:`lane` --
    #: more than one entry means two branches converge here (a shared ancestor commit); each is
    #: drawn as a diagonal line into this row's dot, except the entry equal to :attr:`lane` itself,
    #: which is a plain straight vertical continuation.
    incoming_lanes: list[int] = field(default_factory=list)
    #: This row's own lane continues to the next (older) row -- ``False`` for a root commit (no
    #: parent), which simply ends its lane here.
    continues: bool = True
    #: How many lanes are simultaneously in play at this row -- the widest this row's own painting
    #: needs to reserve horizontal space for.
    active_lane_count: int = 1


def compute_lanes(snapshots: list[Snapshot]) -> list[LaneRow]:
    """Assigns each of ``snapshots`` (newest-first, as :func:`~in_reach.app.vcs.graph_history`
    returns them) a lane index, plus enough topology (:attr:`LaneRow.incoming_lanes`) to draw
    straight/diagonal connector lines between rows.

    Each of ``snapshots``' own :attr:`~in_reach.app.vcs.Snapshot.parents` is at most 1-entry (see
    this module's own docstring for why) -- a commit with 0 parents is a branch root; one with 1
    either continues its own lane (nothing else was already waiting for that parent) or converges
    into a lane that reached the same parent first (two branches sharing a fork point).
    """
    active: dict[str, list[int]] = {}
    free_lanes: list[int] = []
    next_lane = 0
    rows: list[LaneRow] = []
    for snapshot in snapshots:
        incoming = active.pop(snapshot.sha, [])
        if incoming:
            lane = min(incoming)
            for extra in incoming:
                if extra != lane:
                    free_lanes.append(extra)
        elif free_lanes:
            free_lanes.sort()
            lane = free_lanes.pop(0)
        else:
            lane = next_lane
            next_lane += 1

        continues = bool(snapshot.parents)
        if continues:
            parent = snapshot.parents[0]
            active.setdefault(parent, []).append(lane)
        else:
            free_lanes.append(lane)

        active_count = max(
            (l for lanes in active.values() for l in lanes), default=lane
        ) + 1 if active else lane + 1
        rows.append(
            LaneRow(
                snapshot=snapshot,
                lane=lane,
                incoming_lanes=incoming or [lane],
                continues=continues,
                active_lane_count=active_count,
            )
        )
    return rows


class GitGraphWidget(QWidget):
    """Paints a list of :class:`LaneRow` (see :func:`compute_lanes`) as a scrollable commit graph --
    one row per commit, a dot per commit colored by its own lane, connector lines between rows,
    branch-name labels at tip commits, and a small star marker on stamped commits. Meant to sit
    inside a ``QScrollArea`` (its own :meth:`sizeHint` reports the full content height, not a
    clamped viewport size)."""

    #: Emitted with a commit's sha when a row is clicked.
    snapshot_selected = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[LaneRow] = []
        self._selected_sha: str | None = None
        self.setMinimumHeight(_ROW_HEIGHT)

    def set_snapshots(self, snapshots: list[Snapshot]) -> None:
        self._rows = compute_lanes(snapshots)
        self._selected_sha = None
        self._update_geometry()
        self.update()

    def selected_sha(self) -> str | None:
        return self._selected_sha

    def _update_geometry(self) -> None:
        width = _LEFT_MARGIN + max((r.active_lane_count for r in self._rows), default=1) * _LANE_WIDTH + 420
        height = max(_ROW_HEIGHT, len(self._rows) * _ROW_HEIGHT)
        self.setMinimumWidth(width)
        self.setFixedHeight(height)

    def sizeHint(self):  # noqa: ANN201 -- QSize, matches QWidget.sizeHint's own signature
        from PyQt6.QtCore import QSize

        return QSize(self.minimumWidth(), max(_ROW_HEIGHT, len(self._rows) * _ROW_HEIGHT))

    def row_count(self) -> int:
        return len(self._rows)

    def _row_at(self, y: int) -> LaneRow | None:
        index = y // _ROW_HEIGHT
        if 0 <= index < len(self._rows):
            return self._rows[index]
        return None

    def select_row(self, index: int) -> None:
        """Programmatically selects row ``index`` (0 = newest), exactly as if it had been clicked --
        the test/keyboard-navigation seam mouse input alone doesn't cover."""
        if 0 <= index < len(self._rows):
            self._select(self._rows[index].snapshot.sha)

    def _select(self, sha: str) -> None:
        self._selected_sha = sha
        self.update()
        self.snapshot_selected.emit(sha)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        row = self._row_at(int(event.position().y()))
        if row is not None:
            self._select(row.snapshot.sha)
        super().mousePressEvent(event)

    def _lane_x(self, lane: int) -> int:
        return _LEFT_MARGIN + lane * _LANE_WIDTH + _LANE_WIDTH // 2

    def paintEvent(self, event) -> None:  # noqa: ANN001 -- QPaintEvent
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        text_color = self.palette().color(self.foregroundRole())
        muted_color = QColor(text_color)
        muted_color.setAlpha(140)
        metrics = QFontMetrics(self.font())

        for index, row in enumerate(self._rows):
            y = index * _ROW_HEIGHT
            center_y = y + _ROW_HEIGHT // 2
            if row.snapshot.sha == self._selected_sha:
                painter.fillRect(0, y, self.width(), _ROW_HEIGHT, self._selection_color())

            self._paint_connectors(painter, row, index, y, center_y)

            dot_color = _lane_color(row.lane)
            dot_x = self._lane_x(row.lane)
            painter.setBrush(dot_color)
            painter.setPen(QPen(dot_color.darker(130), 1))
            painter.drawEllipse(QRectF(dot_x - _DOT_RADIUS, center_y - _DOT_RADIUS, _DOT_RADIUS * 2, _DOT_RADIUS * 2))
            if row.snapshot.is_stamp:
                self._paint_star(painter, dot_x, center_y)

            text_x = _LEFT_MARGIN + (max((r.active_lane_count for r in self._rows), default=1)) * _LANE_WIDTH + _TEXT_GAP
            label = row.snapshot.stamp_message if row.snapshot.is_stamp else row.snapshot.message
            painter.setPen(text_color)
            painter.drawText(text_x, center_y + metrics.ascent() // 2 - 1, label)

            if row.snapshot.branches:
                branch_text = "  ".join(f"[{name}]" for name in sorted(row.snapshot.branches))
                branch_width = metrics.horizontalAdvance(label) + _TEXT_GAP
                painter.setPen(QColor("#569CD6"))
                painter.drawText(text_x + branch_width, center_y + metrics.ascent() // 2 - 1, branch_text)

            sha_text = row.snapshot.sha[:8]
            painter.setPen(muted_color)
            painter.drawText(self.width() - metrics.horizontalAdvance(sha_text) - _LEFT_MARGIN, center_y + metrics.ascent() // 2 - 1, sha_text)
        painter.end()

    def _selection_color(self) -> QColor:
        color = self.palette().color(self.foregroundRole())
        color.setAlpha(30)
        return color

    def _paint_connectors(self, painter: QPainter, row: LaneRow, index: int, y: int, center_y: int) -> None:
        # Straight continuation lines for every lane that's simply passing through this row
        # untouched (not this row's own incoming/outgoing lanes).
        touched = set(row.incoming_lanes) | {row.lane}
        for lane in range(row.active_lane_count):
            if lane in touched:
                continue
            x = self._lane_x(lane)
            painter.setPen(QPen(_lane_color(lane), 2))
            painter.drawLine(x, y, x, y + _ROW_HEIGHT)

        # Connectors from each incoming lane (the row above) into this row's own dot.
        for lane in row.incoming_lanes:
            x_from = self._lane_x(lane)
            x_to = self._lane_x(row.lane)
            pen = QPen(_lane_color(lane if lane != row.lane else row.lane), 2)
            painter.setPen(pen)
            if x_from == x_to:
                painter.drawLine(x_from, y, x_to, center_y)
            else:
                path = QPainterPath()
                path.moveTo(x_from, y)
                path.cubicTo(x_from, center_y, x_to, y, x_to, center_y)
                painter.strokePath(path, pen)

        # This row's own lane continuing down to the next (older) row.
        if row.continues:
            x = self._lane_x(row.lane)
            painter.setPen(QPen(_lane_color(row.lane), 2))
            painter.drawLine(x, center_y, x, y + _ROW_HEIGHT)

    def _paint_star(self, painter: QPainter, cx: int, cy: int) -> None:
        import math

        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#F0C000"))
        points = []
        outer, inner = 8.0, 3.5
        for i in range(10):
            radius = outer if i % 2 == 0 else inner
            angle = math.pi / 2 + i * math.pi / 5
            points.append((cx + radius * math.cos(angle), cy - 14 - radius * math.sin(angle)))
        path = QPainterPath()
        path.moveTo(*points[0])
        for point in points[1:]:
            path.lineTo(*point)
        path.closeSubpath()
        painter.drawPath(path)
        painter.restore()
