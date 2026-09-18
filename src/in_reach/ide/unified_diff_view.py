"""A VSCode-style *unified* (single-pane, not split) diff view -- PROMPT.md: "please make it so
that when clicking in history on commits - it extends to show a list of files changed (which can
then be clicked on to view (please note this should be a single (not split) view, see sample.png for
styling))". Opened by the Git panel's own History section (see ``MainWindow.vcs_open_commit_diff``)
for one file changed in a selected commit, ``HEAD``-vs-``HEAD``'s-own-first-parent -- distinct from
:mod:`in_reach.ide.diff_view`'s side-by-side :class:`~in_reach.ide.diff_view.DiffViewWidget` (used
for the Changes tab's own live working-tree diff, and the Compare window's own two-ref diff), which
stays split intentionally per that same PROMPT.md line.

Every removed line is shown, then every added line, interleaved in original document order (an
"equal" block passes through once) -- one running text, two line-number gutter columns (old | new,
blank on whichever side a line doesn't exist on) instead of two side-by-side panes.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QColor, QFontDatabase, QPainter, QPaintEvent, QPalette, QResizeEvent, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QTextEdit, QVBoxLayout, QWidget

from in_reach.ide.json_highlighter import JsonSyntaxHighlighter

_REMOVED_COLOR = QColor(244, 63, 94, 45)
_ADDED_COLOR = QColor(34, 197, 94, 45)
_LINE_KIND_COLOR = {"removed": _REMOVED_COLOR, "added": _ADDED_COLOR}
_GUTTER_PADDING = 6
_GUTTER_COLUMN_GAP = 10


@dataclass
class UnifiedLine:
    old_lineno: int | None
    new_lineno: int | None
    text: str
    kind: str  # "equal" | "removed" | "added"


def unify(old_lines: list[str], new_lines: list[str]) -> list[UnifiedLine]:
    """One interleaved run of ``old_lines``/``new_lines`` -- an ``"equal"`` block appears once (both
    line numbers real), a ``"replace"`` block's own removed lines are listed before its added ones
    (matching a plain unified diff's own hunk order), each line carrying whichever of its own
    old/new line number actually applies (``None`` for the side it doesn't exist on)."""
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    result: list[UnifiedLine] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                result.append(UnifiedLine(i1 + k + 1, j1 + k + 1, old_lines[i1 + k], "equal"))
        elif tag == "delete":
            for k in range(i2 - i1):
                result.append(UnifiedLine(i1 + k + 1, None, old_lines[i1 + k], "removed"))
        elif tag == "insert":
            for k in range(j2 - j1):
                result.append(UnifiedLine(None, j1 + k + 1, new_lines[j1 + k], "added"))
        elif tag == "replace":
            for k in range(i2 - i1):
                result.append(UnifiedLine(i1 + k + 1, None, old_lines[i1 + k], "removed"))
            for k in range(j2 - j1):
                result.append(UnifiedLine(None, j1 + k + 1, new_lines[j1 + k], "added"))
    return result


class _UnifiedGutter(QWidget):
    def __init__(self, pane: "_UnifiedDiffPane") -> None:
        super().__init__(pane)
        self._pane = pane

    def sizeHint(self) -> QSize:
        return QSize(self._pane.gutter_width(), 0)

    def paintEvent(self, event: QPaintEvent) -> None:
        self._pane.paint_gutter(event)


class _UnifiedDiffPane(QPlainTextEdit):
    """The single running text pane -- a dual-column (old | new) line-number gutter, ``+``/``-``
    markers, per-line background coloring, and JSON syntax highlighting when applicable, all applied
    by :meth:`set_lines`."""

    def __init__(self) -> None:
        super().__init__()
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self._lines: list[UnifiedLine] = []
        self._highlighter: JsonSyntaxHighlighter | None = None
        self._gutter = _UnifiedGutter(self)
        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self._update_gutter_width()

    def set_json_highlighting(self, enabled: bool) -> None:
        if enabled and self._highlighter is None:
            base_color = self.palette().color(QPalette.ColorRole.Base)
            self._highlighter = JsonSyntaxHighlighter(self.document(), base_color=base_color)
        elif not enabled and self._highlighter is not None:
            self._highlighter.setDocument(None)
            self._highlighter = None

    def set_lines(self, lines: list[UnifiedLine]) -> None:
        self._lines = lines
        marker = {"removed": "-", "added": "+"}
        self.setPlainText("\n".join(f"{marker.get(line.kind, ' ')} {line.text}" for line in lines))
        selections = []
        block = self.document().firstBlock()
        for line in lines:
            if not block.isValid():
                break
            color = _LINE_KIND_COLOR.get(line.kind)
            if color is not None:
                selection = QTextEdit.ExtraSelection()
                selection.format.setBackground(color)
                selection.format.setProperty(QTextCharFormat.Property.FullWidthSelection, True)
                cursor = QTextCursor(block)
                cursor.clearSelection()
                selection.cursor = cursor
                selections.append(selection)
            block = block.next()
        self.setExtraSelections(selections)
        self._update_gutter_width()
        self._gutter.update()

    # -- dual-column line-number gutter -------------------------------------------------------

    def _digit_width(self) -> int:
        max_old = max((line.old_lineno for line in self._lines if line.old_lineno is not None), default=1)
        max_new = max((line.new_lineno for line in self._lines if line.new_lineno is not None), default=1)
        digits = max(len(str(max_old)), len(str(max_new)))
        return self.fontMetrics().horizontalAdvance("9") * digits

    def gutter_width(self) -> int:
        return _GUTTER_PADDING * 2 + self._digit_width() * 2 + _GUTTER_COLUMN_GAP

    def _update_gutter_width(self) -> None:
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _update_gutter(self, rect, dy: int) -> None:  # noqa: ANN001 -- QRect
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        rect = self.contentsRect()
        self._gutter.setGeometry(QRect(rect.left(), rect.top(), self.gutter_width(), rect.height()))

    def paint_gutter(self, event: QPaintEvent) -> None:
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), self.palette().color(QPalette.ColorRole.Window))
        digit_width = self._digit_width()
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        text_color = self.palette().color(QPalette.ColorRole.PlaceholderText)
        height = self.fontMetrics().height()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                line = self._lines[block_number] if block_number < len(self._lines) else None
                if line is not None:
                    painter.setPen(text_color)
                    if line.old_lineno is not None:
                        painter.drawText(0, top, digit_width, height, Qt.AlignmentFlag.AlignRight, str(line.old_lineno))
                    if line.new_lineno is not None:
                        painter.drawText(
                            digit_width + _GUTTER_COLUMN_GAP,
                            top,
                            digit_width,
                            height,
                            Qt.AlignmentFlag.AlignRight,
                            str(line.new_lineno),
                        )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1


class UnifiedDiffViewWidget(QWidget):
    """The tab's own content widget for a single commit's own file diff -- one running
    :class:`_UnifiedDiffPane`, not split. ``rel_path``/``sha`` together are what
    :meth:`~in_reach.ide.tabs.TabPane.open_commit_diff` matches an already-open tab against."""

    def __init__(self, *, rel_path: str, sha: str, old_text: str | None, new_text: str | None) -> None:
        super().__init__()
        self.rel_path = rel_path
        self.sha = sha

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel(f"{rel_path}  ({sha[:8]})")
        header.setContentsMargins(8, 4, 8, 4)
        layout.addWidget(header)

        self.pane = _UnifiedDiffPane()
        layout.addWidget(self.pane, 1)

        is_json = Path(rel_path).suffix.lower() == ".json"
        self.pane.set_json_highlighting(is_json)

        self.set_diff(old_text, new_text)

    def set_diff(self, old_text: str | None, new_text: str | None) -> None:
        old_lines = (old_text or "").splitlines()
        new_lines = (new_text or "").splitlines()
        self.pane.set_lines(unify(old_lines, new_lines))
