"""Plain text-editor widget used for every open/Untitled tab in the main panel.

Adds, on top of the base ``QPlainTextEdit`` (PROMPT.md, across two passes):

- A line-number gutter -- the standard Qt "Code Editor Example" pattern: a small sibling widget
  drawn in the space ``setViewportMargins()`` reserves along the editor's left edge, repainted from
  ``QPlainTextEdit``'s own block-layout geometry rather than tracked as separate state, so it can
  never drift out of sync with the actual text.
- Fold markers in that same gutter, and the bracket-matching behind them (see
  :mod:`in_reach.ide.code_folding`) -- "collapsible and expandable snippets" plus the fold-arrow
  "symbol to show line markers" that triggers them. Bracket-based, not JSON-specific, so it works
  the same for a Megalo ``script.txt`` as a settings ``.json``.
- A breadcrumb bar pinned to the top margin (the same reserved-margin trick, just on the opposite
  edge) -- the open file's own path, plus (for a ``.json`` file specifically) the live JSON
  structural path to wherever the cursor currently sits (see :mod:`in_reach.ide.json_breadcrumb`).
- JSON syntax highlighting (see :mod:`in_reach.ide.json_highlighter`), attached only when the
  file's own extension is ``.json``.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtGui import QMouseEvent, QPaintEvent, QPainter, QPainterPath, QPalette, QResizeEvent
from PyQt6.QtWidgets import QLabel, QPlainTextEdit, QWidget

from in_reach.ide.code_folding import compute_fold_ranges
from in_reach.ide.json_breadcrumb import json_breadcrumb_path
from in_reach.ide.json_highlighter import JsonSyntaxHighlighter

# Padding on each side of the line-number digits, so they don't sit flush against the text or the
# panel's own edge.
_GUTTER_PADDING = 6
#: Width reserved for the fold-arrow column, to the right of the line numbers.
_FOLD_MARKER_WIDTH = 14
#: Height of the breadcrumb strip pinned to the editor's top margin.
_BREADCRUMB_HEIGHT = 22


class _LineNumberArea(QWidget):
    """The gutter widget itself -- just forwards sizing/painting/clicks back to the editor, which
    owns all the actual layout math (it needs the editor's own block geometry either way)."""

    def __init__(self, editor: "TextEditorWidget") -> None:
        super().__init__(editor)
        self._editor = editor
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event: QPaintEvent) -> None:
        self._editor.paint_line_numbers(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._editor.toggle_fold_at(event.pos())


class _BreadcrumbBar(QLabel):
    """A single-line strip pinned to the editor's top margin -- the open file's path, plus (for
    JSON) the live structural path to the cursor (see :meth:`TextEditorWidget._update_breadcrumb`)."""

    def __init__(self, editor: "TextEditorWidget") -> None:
        super().__init__(editor)
        self.setAutoFillBackground(True)
        self.setBackgroundRole(QPalette.ColorRole.AlternateBase)
        self.setContentsMargins(6, 0, 6, 0)
        self.setEnabled(False)  # renders in the theme's own muted/disabled-text shade

    def sizeHint(self) -> QSize:
        return QSize(0, _BREADCRUMB_HEIGHT)


class TextEditorWidget(QPlainTextEdit):
    """One text-editor tab's content.

    Dirty tracking rides ``QTextDocument``'s own ``isModified()``/``modificationChanged`` --
    no extra state lives here.
    """

    def __init__(self, parent: QWidget | None = None, *, path: Path | None = None) -> None:
        super().__init__(parent)
        self.path: Path | None = None
        self._highlighter: JsonSyntaxHighlighter | None = None
        self._fold_ranges: dict[int, int] = {}
        self._collapsed_folds: set[int] = set()

        self._line_number_area = _LineNumberArea(self)
        self._breadcrumb = _BreadcrumbBar(self)

        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter_on_scroll)
        self.textChanged.connect(self._on_text_changed)
        self.cursorPositionChanged.connect(self._update_breadcrumb)

        self._update_gutter_width()
        self.set_path(path)

    def set_path(self, path: Path | None) -> None:
        """(Re-)points this editor at ``path`` -- e.g. "Save As" giving a previously-Untitled tab
        a real path for the first time. Re-evaluates JSON syntax highlighting and the breadcrumb
        to match."""
        self.path = path
        if self._highlighter is not None:
            self._highlighter.setDocument(None)
            self._highlighter = None
        if path is not None and path.suffix.lower() == ".json":
            base_color = self.palette().color(QPalette.ColorRole.Base)
            self._highlighter = JsonSyntaxHighlighter(self.document(), base_color=base_color)
        # Also re-derives fold ranges, not just the breadcrumb -- matters for the split-pane
        # duplicate path (TabPane._duplicate_current_tab), which calls this *after* swapping in
        # the shared document setDocument() points at, whose content this editor hasn't seen a
        # textChanged for yet.
        self._on_text_changed()

    # -- gutter: line numbers + fold markers -------------------------------------------------------

    def line_number_area_width(self) -> int:
        """How wide the gutter needs to be to fit the current line count's digits plus the
        fold-marker column, with padding -- grows as a file passes 9/99/999/... lines rather than
        staying a fixed guess."""
        digits = len(str(max(1, self.blockCount())))
        numbers_width = self.fontMetrics().horizontalAdvance("9") * digits
        return _GUTTER_PADDING * 2 + numbers_width + _FOLD_MARKER_WIDTH

    def _update_gutter_width(self, _new_block_count: int = 0) -> None:
        # setViewportMargins() reserves this widget's own left/top edges for the gutter/breadcrumb,
        # shrinking the text viewport by exactly that much -- both child widgets are positioned to
        # fill their reserved strip in resizeEvent() below.
        self.setViewportMargins(self.line_number_area_width(), _BREADCRUMB_HEIGHT, 0, 0)

    def _update_gutter_on_scroll(self, rect: QRect, dy: int) -> None:
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(0, rect.y(), self._line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        contents = self.contentsRect()
        self._breadcrumb.setGeometry(QRect(contents.left(), contents.top(), contents.width(), _BREADCRUMB_HEIGHT))
        self._line_number_area.setGeometry(
            QRect(
                contents.left(),
                contents.top() + _BREADCRUMB_HEIGHT,
                self.line_number_area_width(),
                contents.height() - _BREADCRUMB_HEIGHT,
            )
        )

    def paint_line_numbers(self, event: QPaintEvent) -> None:
        """Draws every visible block's 1-based line number, right-aligned, plus a fold-arrow
        marker for any block that opens a foldable region -- walking ``firstVisibleBlock()``
        forward is what keeps this correct under wrapped lines (one block can occupy several
        pixel-rows), and under folded-away (invisible, zero-height) blocks, without this widget
        needing to duplicate ``QPlainTextEdit``'s own line-wrapping/folding layout logic."""
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), self.palette().color(QPalette.ColorRole.Base))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())

        muted = self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText)
        numbers_width = self._line_number_area.width() - _FOLD_MARKER_WIDTH - _GUTTER_PADDING
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(muted)
                painter.drawText(
                    0,
                    top,
                    numbers_width,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    str(block_number + 1),
                )
                if block_number in self._fold_ranges:
                    self._draw_fold_marker(
                        painter, numbers_width + 2, top, muted, block_number in self._collapsed_folds
                    )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1
        painter.end()

    def _draw_fold_marker(self, painter: QPainter, x: int, top: int, color, collapsed: bool) -> None:
        """A small filled triangle -- pointing right while collapsed, down while expanded, the same
        convention VS Code's own fold arrows use."""
        line_height = self.fontMetrics().height()
        cy = top + line_height / 2
        half = min(line_height, _FOLD_MARKER_WIDTH) * 0.28
        path = QPainterPath()
        if collapsed:
            path.moveTo(x, cy - half)
            path.lineTo(x, cy + half)
            path.lineTo(x + half * 1.4, cy)
        else:
            path.moveTo(x, cy - half * 0.6)
            path.lineTo(x + half * 1.4, cy - half * 0.6)
            path.lineTo(x + half * 0.7, cy + half * 0.8)
        path.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPath(path)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def toggle_fold_at(self, pos: QPoint) -> None:
        """Toggles whichever foldable line the gutter was clicked on, if any -- ``pos`` is in the
        gutter widget's own coordinates, which share their vertical axis with the editor's block
        layout (the gutter is exactly as tall as the text area, so no translation is needed)."""
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        while block.isValid():
            bottom = top + round(self.blockBoundingRect(block).height())
            if block.isVisible():
                if top <= pos.y() < bottom:
                    self.toggle_fold(block.blockNumber())
                    return
                top = bottom
            block = block.next()

    def toggle_fold(self, block_number: int) -> None:
        """Collapses (or re-expands) the foldable region starting at ``block_number``, if it's
        actually one of :attr:`_fold_ranges`' start lines -- a no-op otherwise."""
        if block_number not in self._fold_ranges:
            return
        if block_number in self._collapsed_folds:
            self._collapsed_folds.discard(block_number)
        else:
            self._collapsed_folds.add(block_number)
        self._apply_fold_visibility()

    def _apply_fold_visibility(self) -> None:
        doc = self.document()
        block = doc.firstBlock()
        while block.isValid():
            block.setVisible(True)
            block = block.next()
        for start in self._collapsed_folds:
            end = self._fold_ranges.get(start)
            if end is None:
                continue
            block = doc.findBlockByNumber(start + 1)
            while block.isValid() and block.blockNumber() <= end:
                block.setVisible(False)
                block = block.next()
        doc.markContentsDirty(0, doc.characterCount())
        self.viewport().update()
        self._line_number_area.update()

    def _on_text_changed(self) -> None:
        self._fold_ranges = compute_fold_ranges(self.toPlainText())
        self._collapsed_folds &= self._fold_ranges.keys()
        self._apply_fold_visibility()
        self._update_breadcrumb()

    # -- breadcrumb ---------------------------------------------------------------------------------

    def _update_breadcrumb(self) -> None:
        parts: list[str] = []
        if self.path is not None:
            parts.append(self.path.parent.name)
            parts.append(self.path.name)
            if self.path.suffix.lower() == ".json":
                parts.extend(json_breadcrumb_path(self.toPlainText(), self.textCursor().position()))
        self._breadcrumb.setText(" > ".join(parts))
