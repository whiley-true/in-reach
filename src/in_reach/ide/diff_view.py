"""A VSCode-style side-by-side diff view, opened as a real tab (PROMPT.md: "when clicking on
changes to a file (in the changes tab) a tab should appear showing the original on the left and
highlighted changes on the right (like vscode git)") -- the Git panel's own "Changes" list is what
opens one (see ``MainWindow.vcs_open_diff``), one file at a time, always for that file's own
uncommitted change (``HEAD`` on the left, the current on-disk content on the right; see
:func:`~in_reach.app.vcs.uncommitted_file_diff`). The Compare window (see
:mod:`in_reach.ide.diff_dialog`) reuses this same widget for two arbitrary refs, via
:func:`~in_reach.app.vcs.ref_file_diff`.

Line-aligned (:func:`_align`), not just two independent scrollable texts: a block only present on
one side gets matching blank filler lines on the other, so unrelated lines never appear side by side
just because they happen to land on the same row -- the same shape VSCode's own diff editor renders.
Each side also gets its own line-number gutter (PROMPT.md, a later pass: "where we have the changes
view - this should maintain the text colouring of the theme, and also have line numbers in the
separate views and still have the text preview on the left") showing that side's *own* real line
number (blank for an alignment filler row, which isn't a real line on that side at all), plus JSON
syntax highlighting matching the app's live theme when the file being diffed is one (``"text
colouring of the theme"`` -- the same :class:`~in_reach.ide.json_highlighter.JsonSyntaxHighlighter`
an ordinary editor tab uses, not just plain monochrome text).
"""

from __future__ import annotations

import difflib
from pathlib import Path

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QColor, QFontDatabase, QPainter, QPaintEvent, QPalette, QResizeEvent, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QTextEdit, QVBoxLayout, QWidget

from in_reach.ide.json_highlighter import JsonSyntaxHighlighter

#: Translucent so the theme's own editor background still shows through -- same "alpha over
#: whatever's there" approach as editor.py's own _GOTO_LINE_HIGHLIGHT_ALPHA.
_REMOVED_COLOR = QColor(244, 63, 94, 45)
_ADDED_COLOR = QColor(34, 197, 94, 45)
_BLANK_COLOR = QColor(128, 128, 128, 25)

_LINE_KIND_COLOR = {"removed": _REMOVED_COLOR, "added": _ADDED_COLOR, "blank": _BLANK_COLOR}

_GUTTER_PADDING = 6


def _align(
    old_lines: list[str], new_lines: list[str]
) -> tuple[list[str], list[str], list[int | None], list[str], list[str], list[int | None]]:
    """Returns ``(left_lines, left_kinds, left_linenos, right_lines, right_kinds, right_linenos)``
    -- ``old_lines``/``new_lines`` padded with blank filler lines so corresponding rows line up,
    each paired with its own per-line ``"equal"``/``"removed"``/``"added"``/``"blank"`` kind (for
    :class:`_DiffPane` to color) and 1-based line number *within that side's own original text*
    (``None`` for a filler row -- there's no real line there on that side at all). A ``"replace"``
    opcode (a block swapped for a differently-sized one) pads whichever side is shorter -- this
    renders it as a plain removed-block/added-block pair rather than trying to word-align individual
    replaced lines, the same simple line-level treatment VSCode's own diff editor defaults to."""
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    left_lines: list[str] = []
    left_kinds: list[str] = []
    left_linenos: list[int | None] = []
    right_lines: list[str] = []
    right_kinds: list[str] = []
    right_linenos: list[int | None] = []

    def _emit_left(text: str | None, kind: str, lineno: int | None) -> None:
        left_lines.append(text or "")
        left_kinds.append(kind)
        left_linenos.append(lineno)

    def _emit_right(text: str | None, kind: str, lineno: int | None) -> None:
        right_lines.append(text or "")
        right_kinds.append(kind)
        right_linenos.append(lineno)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                _emit_left(old_lines[i1 + k], "equal", i1 + k + 1)
                _emit_right(new_lines[j1 + k], "equal", j1 + k + 1)
        elif tag == "delete":
            for k in range(i2 - i1):
                _emit_left(old_lines[i1 + k], "removed", i1 + k + 1)
                _emit_right(None, "blank", None)
        elif tag == "insert":
            for k in range(j2 - j1):
                _emit_left(None, "blank", None)
                _emit_right(new_lines[j1 + k], "added", j1 + k + 1)
        elif tag == "replace":
            old_block = old_lines[i1:i2]
            new_block = new_lines[j1:j2]
            for k in range(max(len(old_block), len(new_block))):
                if k < len(old_block):
                    _emit_left(old_block[k], "removed", i1 + k + 1)
                else:
                    _emit_left(None, "blank", None)
                if k < len(new_block):
                    _emit_right(new_block[k], "added", j1 + k + 1)
                else:
                    _emit_right(None, "blank", None)
    return left_lines, left_kinds, left_linenos, right_lines, right_kinds, right_linenos


class _DiffGutter(QWidget):
    """The line-number gutter itself -- just forwards sizing/painting back to the owning
    :class:`_DiffPane`, same "Qt Code Editor Example" split as :mod:`in_reach.ide.editor`'s own
    ``_LineNumberArea``/``_PlainTextEditor``."""

    def __init__(self, pane: "_DiffPane") -> None:
        super().__init__(pane)
        self._pane = pane

    def sizeHint(self) -> QSize:
        return QSize(self._pane.gutter_width(), 0)

    def paintEvent(self, event: QPaintEvent) -> None:
        self._pane.paint_gutter(event)


class _DiffPane(QPlainTextEdit):
    """One read-only side of the diff -- per-line background coloring, a line-number gutter (its
    own side's real line numbers, blank for an alignment filler row), and JSON syntax highlighting
    when the file being diffed is one, all applied by :meth:`set_lines`."""

    def __init__(self) -> None:
        super().__init__()
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self._linenos: list[int | None] = []
        self._highlighter: JsonSyntaxHighlighter | None = None
        self._gutter = _DiffGutter(self)
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

    def set_lines(self, lines: list[str], kinds: list[str], linenos: list[int | None]) -> None:
        self._linenos = linenos
        self.setPlainText("\n".join(lines))
        selections = []
        block = self.document().firstBlock()
        for kind in kinds:
            if not block.isValid():
                break
            color = _LINE_KIND_COLOR.get(kind)
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

    # -- line-number gutter (same layout math as editor.py's own _PlainTextEditor) ----------------

    def gutter_width(self) -> int:
        digits = len(str(max((n for n in self._linenos if n is not None), default=1)))
        return _GUTTER_PADDING * 2 + self.fontMetrics().horizontalAdvance("9") * digits

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
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        text_color = self.palette().color(QPalette.ColorRole.PlaceholderText)
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                lineno = self._linenos[block_number] if block_number < len(self._linenos) else None
                if lineno is not None:
                    painter.setPen(text_color)
                    painter.drawText(
                        0,
                        top,
                        self._gutter.width() - _GUTTER_PADDING,
                        self.fontMetrics().height(),
                        Qt.AlignmentFlag.AlignRight,
                        str(lineno),
                    )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1


class DiffViewWidget(QWidget):
    """The tab's own content widget -- two :class:`_DiffPane`\\ s side by side, scrolling together.
    ``rel_path`` (the project-relative path this is a diff *of*) is what
    :meth:`~in_reach.ide.tabs.TabPane.open_diff` matches an already-open diff tab against, so
    clicking the same changed file twice switches to the existing tab rather than opening a
    duplicate."""

    def __init__(self, *, rel_path: str, old_text: str | None, new_text: str | None) -> None:
        super().__init__()
        self.rel_path = rel_path

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(8, 4, 8, 4)
        self._old_label = QLabel(f"{rel_path} (HEAD)")
        self._new_label = QLabel(f"{rel_path} (Working Tree)")
        header.addWidget(self._old_label, 1)
        header.addWidget(self._new_label, 1)
        layout.addLayout(header)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(1)
        self.old_pane = _DiffPane()
        self.new_pane = _DiffPane()
        body.addWidget(self.old_pane, 1)
        body.addWidget(self.new_pane, 1)
        layout.addLayout(body, 1)

        self._syncing_scroll = False
        self.old_pane.verticalScrollBar().valueChanged.connect(self._sync_from_old)
        self.new_pane.verticalScrollBar().valueChanged.connect(self._sync_from_new)

        # PROMPT.md: "this should maintain the text colouring of the theme" -- only for JSON today
        # (the same file types an ordinary editor tab highlights at all); anything else stays plain
        # monochrome text, same as before.
        is_json = Path(rel_path).suffix.lower() == ".json"
        self.old_pane.set_json_highlighting(is_json)
        self.new_pane.set_json_highlighting(is_json)

        self.set_diff(old_text, new_text)

    def set_diff(self, old_text: str | None, new_text: str | None) -> None:
        """(Re-)computes and displays the diff between ``old_text``/``new_text`` -- ``None`` is
        treated as an empty file (a newly added file has no ``old_text``, a removed one has no
        ``new_text``; a binary/undecodable file reads the same way -- there's nothing text-diffable
        to show either way). ``splitlines()``, not ``split("\\n")`` -- the latter turns any text
        ending in a newline (nearly all real files) into a spurious trailing empty line, padding
        the *other* side with a phantom blank row it doesn't actually have.
        """
        old_lines = (old_text or "").splitlines()
        new_lines = (new_text or "").splitlines()
        left_lines, left_kinds, left_linenos, right_lines, right_kinds, right_linenos = _align(old_lines, new_lines)
        self.old_pane.set_lines(left_lines, left_kinds, left_linenos)
        self.new_pane.set_lines(right_lines, right_kinds, right_linenos)

    def _sync_from_old(self, value: int) -> None:
        if self._syncing_scroll:
            return
        self._syncing_scroll = True
        self.new_pane.verticalScrollBar().setValue(value)
        self._syncing_scroll = False

    def _sync_from_new(self, value: int) -> None:
        if self._syncing_scroll:
            return
        self._syncing_scroll = True
        self.old_pane.verticalScrollBar().setValue(value)
        self._syncing_scroll = False
