"""Plain text-editor widget used for every open/Untitled tab in the main panel.

Adds a line-number gutter (PROMPT.md) -- the standard Qt ``QPlainTextEdit`` pattern (see Qt's own
"Code Editor Example"): a small sibling widget drawn in the space ``setViewportMargins()`` reserves
along the editor's left edge, repainted from ``QPlainTextEdit``'s own block-layout geometry rather
than tracked as separate state, so it can never drift out of sync with the actual text.
"""

from __future__ import annotations

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QPaintEvent, QPainter, QPalette, QResizeEvent
from PyQt6.QtWidgets import QPlainTextEdit, QWidget

# Padding on each side of the line-number digits, so they don't sit flush against the text or the
# panel's own edge.
_GUTTER_PADDING = 6


class _LineNumberArea(QWidget):
    """The gutter widget itself -- just forwards sizing/painting back to the editor, which owns
    all the actual layout math (it needs the editor's own block geometry either way)."""

    def __init__(self, editor: "TextEditorWidget") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event: QPaintEvent) -> None:
        self._editor.paint_line_numbers(event)


class TextEditorWidget(QPlainTextEdit):
    """One text-editor tab's content.

    Dirty tracking rides ``QTextDocument``'s own ``isModified()``/``modificationChanged`` --
    no extra state lives here. No syntax highlighting or file-type awareness yet.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._line_number_area = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter_on_scroll)
        self._update_gutter_width()

    def line_number_area_width(self) -> int:
        """How wide the gutter needs to be to fit the current line count's digits, plus padding on
        both sides -- grows as a file passes 9/99/999/... lines rather than staying a fixed guess."""
        digits = len(str(max(1, self.blockCount())))
        return _GUTTER_PADDING * 2 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_gutter_width(self, _new_block_count: int = 0) -> None:
        # setViewportMargins() reserves this widget's own left edge for the gutter, shrinking the
        # text viewport by exactly that much -- the gutter widget itself is positioned to fill
        # that reserved strip in resizeEvent() below.
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

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
        self._line_number_area.setGeometry(
            QRect(contents.left(), contents.top(), self.line_number_area_width(), contents.height())
        )

    def paint_line_numbers(self, event: QPaintEvent) -> None:
        """Draws every visible block's 1-based line number, right-aligned, at that block's actual
        on-screen ``y`` -- walking ``firstVisibleBlock()`` forward is what keeps this correct
        under wrapped lines (one block can occupy several pixel-rows) without this widget needing
        to duplicate ``QPlainTextEdit``'s own line-wrapping layout logic."""
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), self.palette().color(QPalette.ColorRole.Base))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())

        muted = self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText)
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(muted)
                painter.drawText(
                    0,
                    top,
                    self._line_number_area.width() - _GUTTER_PADDING,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    str(block_number + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1
        painter.end()
