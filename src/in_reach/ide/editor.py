"""Plain text-editor widget used for every open/Untitled tab in the main panel.

Adds, on top of the base ``QPlainTextEdit`` (PROMPT.md, across two passes):

- A line-number gutter -- the standard Qt "Code Editor Example" pattern: a small sibling widget
  drawn in the space ``setViewportMargins()`` reserves along the editor's left edge, repainted from
  ``QPlainTextEdit``'s own block-layout geometry rather than tracked as separate state, so it can
  never drift out of sync with the actual text.
- Fold markers in that same gutter, and the bracket-matching behind them (see
  :mod:`in_reach.ide.code_folding`) -- "collapsible and expandable snippets". Bracket-based, not
  JSON-specific, so it works the same for a Megalo ``script.txt`` as a settings ``.json``.
- Indent guides -- thin vertical lines through the text area at each indentation level (PROMPT.md:
  "the | symbol to show line markers"; a first pass read this as the fold arrows above instead, per
  a later PROMPT.md pass -- "we're still missing the | symbol" -- that one wasn't it).
- A breadcrumb bar pinned to the top margin (the same reserved-margin trick, just on the opposite
  edge) -- the open file's own path, plus (for a ``.json`` file specifically) the live JSON
  structural path to wherever the cursor currently sits (see :mod:`in_reach.ide.json_breadcrumb`).
- JSON syntax highlighting (see :mod:`in_reach.ide.json_highlighter`), attached only when the
  file's own extension is ``.json``.
- A minimap pinned along the right edge, next to the vertical scrollbar (PROMPT.md: "a live code
  preview on the right hand side next to the scrollbar") -- see :class:`_Minimap`.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPainterPath,
    QPalette,
    QResizeEvent,
    QTextCharFormat,
    QTextCursor,
)
from PyQt6.QtWidgets import QLabel, QPlainTextEdit, QTextEdit, QToolTip, QWidget

from in_reach.ide import schema_check
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
#: Width reserved for the minimap, along the editor's right edge.
_MINIMAP_WIDTH = 72
#: Fixed error red -- same reasoning as json_highlighter.py's own fixed token palette: a schema
#: error reads as unambiguously wrong regardless of which of this app's themes is active.
_ERROR_COLOR = "#f14c4c"
#: Spaces per indent level for the vertical guide lines -- matches this project's own generated
#: ``.json`` files (``json.dump(..., indent=2)``) and ``vs_sample.png`` itself.
_INDENT_SIZE = 2


def _indent_level(text: str) -> int:
    """How many complete :data:`_INDENT_SIZE`-space indent levels ``text`` (one line) starts
    with."""
    leading = len(text) - len(text.lstrip(" "))
    return leading // _INDENT_SIZE


def _find_project_title(path: Path) -> str | None:
    """Walks ``path``'s own ancestors looking for a gametype project folder (one holding a
    ``Notes.txt`` -- every project has exactly one, see
    :func:`~in_reach.app.new_project.create_gametype_project`, and unlike ``settings/settings.json``
    it's there even for a genuinely blank project with nothing decompiled yet) and returns its
    title (see :func:`~in_reach.app.new_project.read_project_title`).

    Returns ``None`` if no ancestor has one -- ``path`` isn't inside a real project (an Untitled
    tab later saved somewhere else entirely, say).
    """
    from in_reach.app import new_project

    for ancestor in path.parents:
        if (ancestor / new_project.NOTES_FILENAME).is_file():
            return new_project.read_project_title(ancestor)
    return None


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


#: Fixed pixel height per rendered line in the minimap (PROMPT.md: "the live code preview ... it
#: should scroll with the editor, and should contain text instead of blocks") -- a real (if tiny)
#: rendering of the actual glyphs, shrunk down via a painter scale rather than an unreadably small
#: point size (see :meth:`_Minimap._paint_lines`), same density VS Code's own minimap uses.
_MINI_LINE_HEIGHT = 3.0


class _Minimap(QWidget):
    """A shrunk, *scrolling* preview of the surrounding text pinned along the editor's right edge,
    next to its vertical scrollbar (PROMPT.md: "a live code preview on the right hand side next to
    the scrollbar").

    Unlike a traditional whole-document overview, this always starts from the same line the main
    view itself currently starts from (:meth:`QPlainTextEdit.firstVisibleBlock`) and draws real
    text at a fixed, tiny line height -- PROMPT.md: "it should scroll with the editor" (rather than
    staying static while squashing the entire file to fit) "and should contain text instead of
    blocks". A short file simply runs out of lines partway down rather than being stretched to fill
    the column (PROMPT.md: "if the editor file is not long, the preview does not need to fill the
    full screen vertically"). A translucent band over the top of it shows how much of that same
    stretch the main view currently shows, and a line the live schema check currently flags (see
    :meth:`TextEditorWidget._update_schema_validation`) draws as a full-width red bar behind its own
    text, so a problem stays visible even where it's only a page or two away (PROMPT.md: "it should
    highlight errors as a line in colour"). Clicking or dragging inside it scrolls the editor to
    match.
    """

    def __init__(self, editor: "TextEditorWidget") -> None:
        super().__init__(editor)
        self._editor = editor
        #: 0-based block numbers the live schema check currently flags -- see
        #: :meth:`set_error_lines`.
        self.error_lines: set[int] = set()
        #: Set for the duration of a press-drag -- ``(press_y, scrollbar_value_at_press)``, so a
        #: drag's own scroll delta is measured from where the mouse went down, not from wherever it
        #: last was (which would compound movement rather than track the pointer 1:1).
        self._drag_anchor: tuple[float, int] | None = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(_MINIMAP_WIDTH, 0)

    def set_error_lines(self, lines: set[int]) -> None:
        """Repaints only if ``lines`` (0-based block numbers) actually changed -- called on every
        keystroke via :meth:`TextEditorWidget._update_schema_validation`, so a document with no
        errors (the overwhelming common case) never triggers a paint over this alone."""
        if lines != self.error_lines:
            self.error_lines = lines
            self.update()

    def _visible_block_count(self) -> int:
        """How many of the main editor's own blocks currently fit in its viewport -- walking block
        geometry (same technique :meth:`TextEditorWidget._draw_indent_guides` already uses) rather
        than a fixed guess, so it stays correct as a block wraps across several visual lines."""
        editor = self._editor
        viewport_height = editor.viewport().height()
        block = editor.firstVisibleBlock()
        top = round(editor.blockBoundingGeometry(block).translated(editor.contentOffset()).top())
        count = 0
        while block.isValid() and top < viewport_height:
            top += round(editor.blockBoundingRect(block).height())
            count += 1
            block = block.next()
        return count

    def _line_offset(self, y: float) -> int:
        """How many minimap lines below its own top edge ``y`` sits -- the unit both a click's own
        jump and a drag's own delta are measured in."""
        return round(y / _MINI_LINE_HEIGHT)

    def _first_line(self) -> int:
        """The 0-based block number the minimap starts rendering from -- always the main editor's
        own current :meth:`~QPlainTextEdit.firstVisibleBlock`, which is what makes this a *scrolling*
        preview (PROMPT.md: "it should scroll with the editor") rather than a static, whole-document
        overview."""
        return self._editor.firstVisibleBlock().blockNumber()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        scrollbar = self._editor.verticalScrollBar()
        scrollbar.setValue(scrollbar.value() + self._line_offset(event.position().y()))
        self._drag_anchor = (event.position().y(), scrollbar.value())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_anchor is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        start_y, start_value = self._drag_anchor
        delta = self._line_offset(event.position().y() - start_y)
        self._editor.verticalScrollBar().setValue(start_value + delta)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_anchor = None

    def paintEvent(self, event: QPaintEvent) -> None:
        editor = self._editor
        palette = editor.palette()
        painter = QPainter(self)
        painter.fillRect(self.rect(), palette.color(QPalette.ColorRole.Base))

        max_lines = int(self.height() / _MINI_LINE_HEIGHT) + 1
        first_line = self._first_line()

        if self.error_lines:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(_ERROR_COLOR))
            for line in self.error_lines:
                offset = line - first_line
                if 0 <= offset < max_lines:
                    painter.drawRect(QRectF(0, offset * _MINI_LINE_HEIGHT, self.width(), _MINI_LINE_HEIGHT))

        self._paint_lines(painter, max_lines)

        visible = self._visible_block_count()
        band_color = palette.color(QPalette.ColorRole.Highlight)
        band_color.setAlpha(70)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(band_color)
        painter.drawRect(QRectF(0, 0, self.width(), visible * _MINI_LINE_HEIGHT))
        painter.end()

    def _paint_lines(self, painter: QPainter, max_lines: int) -> None:
        """Draws each line starting from the main view's own :meth:`~QPlainTextEdit.
        firstVisibleBlock` as real (if shrunken) text -- a scaled-down transform around an ordinary
        ``drawText()`` call, rather than an unreadably small point size, is what keeps the glyphs
        looking like antialiased text rather than illegible pixel noise."""
        editor = self._editor
        real_line_height = editor.fontMetrics().height()
        if real_line_height <= 0:
            return
        scale = _MINI_LINE_HEIGHT / real_line_height
        ascent = editor.fontMetrics().ascent()

        painter.setFont(editor.font())
        painter.setPen(editor.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText))

        block = editor.firstVisibleBlock()
        index = 0
        while block.isValid() and index < max_lines:
            text = block.text()
            if text.strip():
                painter.save()
                painter.translate(2.0, index * _MINI_LINE_HEIGHT)
                painter.scale(scale, scale)
                painter.drawText(QPointF(0, ascent), text)
                painter.restore()
            block = block.next()
            index += 1


class TextEditorWidget(QPlainTextEdit):
    """One text-editor tab's content.

    Dirty tracking rides ``QTextDocument``'s own ``isModified()``/``modificationChanged`` --
    no extra state lives here.
    """

    #: PROMPT.md: "make ctrl + S a save shortcut on the keyboard when on text editor" -- emitted
    #: from keyPressEvent() below rather than a window-level QShortcut, so the binding only ever
    #: fires while a text editor genuinely has focus (see TabPane's connection of this signal).
    save_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None, *, path: Path | None = None) -> None:
        super().__init__(parent)
        self.path: Path | None = None
        self._highlighter: JsonSyntaxHighlighter | None = None
        self._fold_ranges: dict[int, int] = {}
        self._collapsed_folds: set[int] = set()
        #: Every current schema error's own ``(start, end, message)`` character span -- what
        #: :meth:`_error_message_at` hovers against to show the red-underline tooltip (PROMPT.md:
        #: "it should be a window that appears when hovering on the red underlined text").
        self._error_spans: list[tuple[int, int, str]] = []

        self._line_number_area = _LineNumberArea(self)
        self._breadcrumb = _BreadcrumbBar(self)
        self._minimap = _Minimap(self)
        # Needed for mouseMoveEvent() (below) to fire on a plain hover, not just a button-down drag
        # -- how the red-underline tooltip knows to hide again once the pointer leaves the span.
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

        self.blockCountChanged.connect(self._update_gutter_width)
        # Plain lambdas rather than self._minimap.update directly -- QWidget.update() is overloaded
        # (no-args, QRect, or four ints), and neither signal's own single `int` argument matches any
        # of those, so passing the bound method straight to connect() would raise at emit time.
        self.blockCountChanged.connect(lambda _count: self._minimap.update())
        self.verticalScrollBar().valueChanged.connect(lambda _value: self._minimap.update())
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
        # Cached rather than looked up on every _update_breadcrumb() call (cursor moves fire it
        # constantly) -- it can only actually change when the path itself does, via set_path().
        self._project_title = _find_project_title(path) if path is not None else None
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

    def refresh_project_title(self) -> None:
        """Re-reads this tab's own ancestor project's title (see :func:`_find_project_title`) and
        refreshes the breadcrumb to match -- called after a project rename (PROMPT.md: "when a
        project name is changed [via rvt or via apply settings.json change] - the project title
        should change in the tabs and in the breadcrumb"), since :attr:`_project_title` is otherwise
        only ever (re-)cached by :meth:`set_path`, which a rename doesn't itself call."""
        if self.path is not None:
            self._project_title = _find_project_title(self.path)
        self._update_breadcrumb()

    # -- gutter: line numbers + fold markers -------------------------------------------------------

    def line_number_area_width(self) -> int:
        """How wide the gutter needs to be to fit the current line count's digits plus the
        fold-marker column, with padding -- grows as a file passes 9/99/999/... lines rather than
        staying a fixed guess."""
        digits = len(str(max(1, self.blockCount())))
        numbers_width = self.fontMetrics().horizontalAdvance("9") * digits
        return _GUTTER_PADDING * 2 + numbers_width + _FOLD_MARKER_WIDTH

    def _update_gutter_width(self, _new_block_count: int = 0) -> None:
        # setViewportMargins() reserves this widget's own left/top/right edges for the gutter/
        # breadcrumb/minimap, shrinking the text viewport by exactly that much -- every reserved
        # child is positioned to fill its own strip in resizeEvent() below.
        self.setViewportMargins(self.line_number_area_width(), _BREADCRUMB_HEIGHT, _MINIMAP_WIDTH, 0)

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
        self._minimap.setGeometry(
            QRect(
                contents.right() - _MINIMAP_WIDTH + 1,
                contents.top() + _BREADCRUMB_HEIGHT,
                _MINIMAP_WIDTH,
                contents.height() - _BREADCRUMB_HEIGHT,
            )
        )

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.matches(QKeySequence.StandardKey.Save):
            self.save_requested.emit()
            return
        super().keyPressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        # PROMPT.md: "where we have a ... red underlined text we are seeing the error message at
        # the top of the text screen, it should be a window that appears when hovering on the red
        # underlined text" -- QToolTip.showText() at the live cursor position, rather than the old
        # always-on banner, so a valid file never loses any space to it and the message only shows
        # up right where the problem actually is.
        message = self._error_message_at(event.pos())
        if message is not None:
            QToolTip.showText(event.globalPosition().toPoint(), message, self)
        else:
            QToolTip.hideText()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: ANN001 -- QEvent
        QToolTip.hideText()
        super().leaveEvent(event)

    def _error_message_at(self, pos: QPoint) -> str | None:
        """The schema-error message covering the character under ``pos`` (viewport coordinates),
        if any -- what the red wavy underline's own hover tooltip shows."""
        if not self._error_spans:
            return None
        char_pos = self.cursorForPosition(pos).position()
        for start, end, message in self._error_spans:
            if start <= char_pos < end:
                return message
        return None

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        self._draw_indent_guides(event)

    def _draw_indent_guides(self, event: QPaintEvent) -> None:
        """Thin vertical lines through the viewport at each indentation level -- drawn *after* the
        base text (super().paintEvent() above) so they sit visually behind the glyphs rather than
        painting over them, same layering ``QPlainTextEdit``'s own selection/current-line
        highlighting uses."""
        space_width = self.fontMetrics().horizontalAdvance(" ")
        if space_width <= 0:
            return

        painter = QPainter(self.viewport())
        painter.setPen(self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText))
        base_x = self.contentOffset().x()

        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        while block.isValid() and top <= event.rect().bottom():
            bottom = top + round(self.blockBoundingRect(block).height())
            if block.isVisible() and bottom >= event.rect().top():
                for level in range(1, _indent_level(block.text()) + 1):
                    x = round(base_x + level * _INDENT_SIZE * space_width)
                    painter.drawLine(x, top, x, bottom)
            block = block.next()
            top = bottom
        painter.end()

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
        self._update_schema_validation()

    # -- live schema validation -----------------------------------------------------------------

    def _update_schema_validation(self) -> None:
        """VS Code-style live feedback (PROMPT.md: "highlighting and error message if schema is
        incorrect") -- a wavy red underline under every offending value, its own message shown in
        a tooltip on hover (see :meth:`mouseMoveEvent`/:meth:`_error_message_at` -- PROMPT.md: "it
        should be a window that appears when hovering on the red underlined text"), plus a red line
        in the minimap for each offending line (PROMPT.md: "it should highlight errors as a line in
        colour"). Re-evaluated on every keystroke. Purely advisory: the actual reject-on-save
        enforcement is :func:`~in_reach.ide.schema_check.validate_before_save`, called separately by
        :meth:`~in_reach.ide.tabs.TabPane._save_tab`."""
        errors = schema_check.find_errors(self.path, self.toPlainText()) if self.path is not None else None
        if not errors:
            self.setExtraSelections([])
            self._error_spans = []
            self._minimap.set_error_lines(set())
            return

        doc = self.document()
        selections = []
        spans: list[tuple[int, int, str]] = []
        error_lines: set[int] = set()
        for error in errors:
            if error.span is None:
                # A JSON-syntax error at end-of-file, say -- nothing to underline/hover, but it
                # still blocks the save (validate_before_save doesn't need a span at all).
                continue
            start, end = error.span
            cursor = QTextCursor(doc)
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            fmt = QTextCharFormat()
            fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SpellCheckUnderline)
            fmt.setUnderlineColor(QColor(_ERROR_COLOR))
            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            selection.format = fmt
            selections.append(selection)
            spans.append((start, end, error.message))
            error_lines.add(doc.findBlock(start).blockNumber())
        self.setExtraSelections(selections)
        self._error_spans = spans
        self._minimap.set_error_lines(error_lines)

    # -- breadcrumb ---------------------------------------------------------------------------------

    def _update_breadcrumb(self) -> None:
        parts: list[str] = []
        if self.path is not None:
            # PROMPT.md: "include the project name (not file dir) in the breadcrumb" -- the
            # gametype project's own title (its README's heading), not just path.parent.name (the
            # immediate containing folder, e.g. "settings"/"rvt" -- still shown too, right after).
            if self._project_title is not None:
                parts.append(self._project_title)
            parts.append(self.path.parent.name)
            parts.append(self.path.name)
            if self.path.suffix.lower() == ".json":
                parts.extend(json_breadcrumb_path(self.toPlainText(), self.textCursor().position()))
        self._breadcrumb.setText(" > ".join(parts))
