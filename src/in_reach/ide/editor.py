"""Text-editor widget used for every open/Untitled tab in the main panel.

Adds, on top of the base ``QPlainTextEdit`` (PROMPT.md, across two passes):

- A line-number gutter -- the standard Qt "Code Editor Example" pattern: a small sibling widget
  repainted from ``QPlainTextEdit``'s own block-layout geometry rather than tracked as separate
  state, so it can never drift out of sync with the actual text.
- Fold markers in that same gutter, and the bracket-matching behind them (see
  :mod:`in_reach.ide.code_folding`) -- "collapsible and expandable snippets". Bracket-based, not
  JSON-specific, so it works the same for a Megalo ``script.txt`` as a settings ``.json``.
- Indent guides -- thin vertical lines through the text area at each indentation level (PROMPT.md:
  "the | symbol to show line markers"; a first pass read this as the fold arrows above instead, per
  a later PROMPT.md pass -- "we're still missing the | symbol" -- that one wasn't it).
- A breadcrumb bar pinned above the text -- the open file's own path, plus (for a ``.json`` file
  specifically) the live JSON structural path to wherever the cursor currently sits (see
  :mod:`in_reach.ide.json_breadcrumb`).
- JSON syntax highlighting (see :mod:`in_reach.ide.json_highlighter`), attached only when the
  file's own extension is ``.json``.
- A minimap pinned along the right edge, next to the vertical scrollbar (PROMPT.md: "a live code
  preview on the right hand side next to the scrollbar") -- see :class:`_Minimap`.

``TextEditorWidget`` (the class every other module imports and treats as "the editor") is a plain
``QWidget`` composing the actual ``QPlainTextEdit`` (:class:`_PlainTextEditor`) together with the
gutter/breadcrumb/minimap as ordinary, layout-managed sibling widgets, and delegates everything it
doesn't define itself straight to that inner editor (see :meth:`TextEditorWidget.__getattr__`) --
so every existing caller's ``editor.toPlainText()``/``.document()``/``.textCursor()``/etc. (and
``isinstance(x, TextEditorWidget)``) keeps working exactly as before.

This wasn't always the shape: gutter/breadcrumb/minimap used to be *overlay* children of the
``QPlainTextEdit`` itself, positioned into space ``setViewportMargins()`` reserved for them.
PROMPT.md: "if i have two tabs open (1 on welcome and one on any json) and i close the welcome,
things crash" -- that turned out to be a real, reproducible native access violation inside Qt's own
internal resize handling (confirmed via a WinDbg-analyzed crash dump), triggered specifically by
having all three margin-reserving widgets present together *and* a genuine, interactively-driven
resize (e.g. closing a sibling split-pane tab, or dragging the pane splitter) -- never reproducible
through any programmatic/scripted resize, only real mouse-driven interaction. Every attempt to
patch around it from inside the ``QPlainTextEdit`` itself (temporarily zeroing the margins across
the risky call, reentrancy guards) failed to stop it. Moving the three off ``setViewportMargins()``
entirely, as ordinary ``QGridLayout``-managed siblings instead, sidesteps the internal Qt code path
that bug lives in altogether, since the inner ``QPlainTextEdit`` now never has non-default viewport
margins at all.
"""

from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPainterPath,
    QPalette,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
)
from PyQt6.QtWidgets import (
    QApplication,
    QGridLayout,
    QLabel,
    QPlainTextDocumentLayout,
    QPlainTextEdit,
    QTextEdit,
    QToolTip,
    QWidget,
)

from in_reach.app import indent_settings
from in_reach.ide import indent_state, schema_check
from in_reach.ide.code_folding import compute_fold_ranges
from in_reach.ide.find_replace import FindReplaceBar
from in_reach.ide.json_breadcrumb import json_breadcrumb_path
from in_reach.ide.json_highlighter import JsonSyntaxHighlighter
from in_reach.ide.json_position import find_value_spans

# Padding on each side of the line-number digits, so they don't sit flush against the text or the
# panel's own edge.
_GUTTER_PADDING = 6
#: Width reserved for the fold-arrow column, to the right of the line numbers.
_FOLD_MARKER_WIDTH = 14
#: Height of the breadcrumb strip pinned above the text.
_BREADCRUMB_HEIGHT = 22
#: Width reserved for the minimap, along the editor's right edge.
_MINIMAP_WIDTH = 72
#: Fixed error red -- same reasoning as json_highlighter.py's own fixed token palette: a schema
#: error reads as unambiguously wrong regardless of which of this app's themes is active.
_ERROR_COLOR = "#f14c4c"
#: Spaces per indent level for the vertical guide lines -- matches this project's own generated
#: ``.json`` files (``json.dump(..., indent=2)``) and ``vs_sample.png`` itself.
_INDENT_SIZE = 2
#: Alpha applied to the theme's own Highlight color for the "Go to Line" target-line background --
#: same technique (and alpha, for visual consistency) as the minimap's own visible-viewport band in
#: :meth:`_Minimap.paintEvent`, just applied to a single document line instead of a page range.
_GOTO_LINE_HIGHLIGHT_ALPHA = 70

#: PROMPT.md: "add a helper text when a user hovers over schema in settings that warns the user
#: they cannot edit that section of the jsons" -- shown by :meth:`_PlainTextEditor.
#: _error_message_at`'s own hover tooltip while the pointer sits over the protected "$schema" line
#: (see :meth:`_PlainTextEditor._schema_line_range`).
_SCHEMA_LINE_WARNING = "This line is managed automatically and can't be edited."
#: PROMPT.md: "entries in forge labels (in script_settings.json) should instead not be changeable
#: (the entry in the forge_labels name must always be none editable in scrip_settings.json)" --
#: same hover-tooltip treatment as _SCHEMA_LINE_WARNING, shown over a protected forge_labels[].name
#: value (see :meth:`_PlainTextEditor._forge_label_name_spans`).
_FORGE_LABEL_NAME_WARNING = "Forge label names are fixed and can't be edited here."

#: Same "protected span" treatment as the two warnings above, extended to every other field
#: settings_writer.py's own module docstring documents as a "text field" -- a ``ReachString``
#: pointer (or, for team names, an equivalent single-write-path field) that a real Apply never
#: writes back at all, because in_reach.app.rvt.strings_writer's apply_strings() already owns that
#: same underlying data -- confirmed a real, user-facing bug (not just the Apply button staying
#: stuck "unapplied", which apply_settings.py's own _strip_never_applied_*() helpers already fixed):
#: hand-editing one of these fields directly in settings/script_settings.json visibly reverts back
#: to its real value the moment the next successful Apply's own build/dist/*.bin resync
#: (MainWindow._on_watched_bin_changed -> in_reach.app.rvt.decompile.resync_from_bin) re-decompiles
#: and overwrites settings/ with whatever's actually baked into the .bin -- which never picked up
#: the edit in the first place. Protecting these here stops the edit (and the confusing revert)
#: before it happens, the same way forge_labels[].name already does, rather than leaving users to
#: rediscover this one field at a time.
_TEAM_NAME_WARNING = "Team names are fixed here -- edit strings.json's teams[].name instead."
_DESCRIPTION_STRING_WARNING = (
    "The gametype description is fixed here -- edit strings.json's meta.description instead."
)
_CATEGORY_WARNING = "This field has no effect on the compiled variant and can't be edited here."
_SCRIPTED_TEXT_WARNING = "This text is fixed here -- edit it in strings.json instead."
_RESOLVED_NAME_WARNING = "This is a resolved display name and can't be edited here."

#: PROMPT.md: "please increase the font size of the 3 setting json files by 10%" -- the project's
#: own hand-relevant settings files (see :mod:`in_reach.app.new_project`'s own module docstring:
#: ``settings/settings.json``/``script_settings.json``/``strings.json``), read 10% larger than
#: every other editor tab, same "+N% on top of the live app font" pattern as
#: :data:`~in_reach.ide.explorer.ExplorerPanel.TEXT_SCALE`.
ENLARGED_FILENAMES = frozenset({"settings.json", "script_settings.json", "strings.json"})
FONT_SCALE = 1.1


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
    owns all the actual layout math (it needs the editor's own block geometry either way).

    A plain, layout-managed sibling of the editor now (see module docstring) -- its ``sizeHint()``
    is what the wrapper's ``QGridLayout`` uses to size the gutter's own column, so
    :meth:`updateGeometry` (called whenever the editor's block count changes -- see
    ``TextEditorWidget.__init__``) is what makes the column actually grow/shrink as the line-number
    digit count does, in place of the old ``setViewportMargins()`` dance.
    """

    def __init__(self, editor: "_PlainTextEditor") -> None:
        super().__init__()
        self._editor = editor
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event: QPaintEvent) -> None:
        self._editor.paint_line_numbers(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._editor.toggle_fold_at(event.pos())


class _BreadcrumbBar(QLabel):
    """A single-line strip pinned above the text -- the open file's path, plus (for JSON) the live
    structural path to the cursor (see :meth:`_PlainTextEditor._update_breadcrumb`)."""

    def __init__(self) -> None:
        super().__init__()
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
    :meth:`_PlainTextEditor._update_schema_validation`) draws as a full-width red bar behind its
    own text, so a problem stays visible even where it's only a page or two away (PROMPT.md: "it
    should highlight errors as a line in colour"). Clicking or dragging inside it scrolls the
    editor to match.
    """

    def __init__(self, editor: "_PlainTextEditor") -> None:
        super().__init__()
        self._editor = editor
        #: 0-based block numbers the live schema check currently flags -- see
        #: :meth:`set_error_lines`.
        self.error_lines: set[int] = set()
        #: 0-based block number the main editor's own "Go to Line" jumped to, if any (mirrors
        #: :attr:`_PlainTextEditor._goto_highlight_block`) -- see :meth:`set_highlight_line`.
        self.highlight_line: int | None = None
        #: Set for the duration of a press-drag -- ``(press_y, scrollbar_value_at_press)``, so a
        #: drag's own scroll delta is measured from where the mouse went down, not from wherever it
        #: last was (which would compound movement rather than track the pointer 1:1).
        self._drag_anchor: tuple[float, int] | None = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(_MINIMAP_WIDTH, 0)

    def set_error_lines(self, lines: set[int]) -> None:
        """Repaints only if ``lines`` (0-based block numbers) actually changed -- called on every
        keystroke via :meth:`_PlainTextEditor._update_schema_validation`, so a document with no
        errors (the overwhelming common case) never triggers a paint over this alone."""
        if lines != self.error_lines:
            self.error_lines = lines
            self.update()

    def set_highlight_line(self, line: int | None) -> None:
        """Mirrors the main editor's own "Go to Line" target-line highlight (PROMPT.md: the side
        preview should highlight the selected line too) -- ``line`` is a 0-based block number, or
        ``None`` once the cursor has moved off of it."""
        if line != self.highlight_line:
            self.highlight_line = line
            self.update()

    def _visible_block_count(self) -> int:
        """How many of the main editor's own blocks currently fit in its viewport -- walking block
        geometry (same technique :meth:`_PlainTextEditor._draw_indent_guides` already uses) rather
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

        if self.highlight_line is not None:
            offset = self.highlight_line - first_line
            if 0 <= offset < max_lines:
                highlight_color = palette.color(QPalette.ColorRole.Highlight)
                highlight_color.setAlpha(_GOTO_LINE_HIGHLIGHT_ALPHA)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(highlight_color)
                painter.drawRect(QRectF(0, offset * _MINI_LINE_HEIGHT, self.width(), _MINI_LINE_HEIGHT))

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


class _PlainTextEditor(QPlainTextEdit):
    """The real ``QPlainTextEdit`` -- everything about editing/highlighting/folding/schema
    validation/the breadcrumb text itself lives here, same as it always has. Never used directly
    outside this module -- see :class:`TextEditorWidget` (the public wrapper) for why, and for
    where the gutter/breadcrumb/minimap actually get laid out now.

    :attr:`_line_number_area`/:attr:`_breadcrumb`/:attr:`_minimap` are set by ``TextEditorWidget``
    right after construction (it owns and lays them out, not this class) -- every method below that
    reads them tolerates ``None`` (mid-construction, before the wrapper finishes wiring things up)
    by simply not updating a sibling that doesn't exist yet.
    """

    #: PROMPT.md: "make ctrl + S a save shortcut on the keyboard when on text editor" -- emitted
    #: from keyPressEvent() below rather than a window-level QShortcut, so the binding only ever
    #: fires while a text editor genuinely has focus (see TabPane's connection of this signal).
    save_requested = pyqtSignal()

    def __init__(self, document: QTextDocument | None = None) -> None:
        super().__init__()
        # A confirmed, reproducible PyQt6/Qt6 bug (not anything about this app's own code -- an
        # isolated, from-scratch repro with two bare, un-subclassed QPlainTextEdits and zero
        # gutter/minimap/breadcrumb/splitter code reproduces it identically, and rules out every
        # theory this investigation tried before it -- viewport margins, QSplitterHandle, Windows
        # accessibility, PyQt6/Qt6/Python version): calling ``setDocument()`` *twice* on the same
        # QPlainTextEdit -- once for whatever document it starts with, a second time to replace it
        # with a different one -- corrupts something in Qt's own control internals that crashes (a
        # real, native access violation, deep inside Qt's own QTextDocument/
        # QPlainTextDocumentLayout internals) later, once *any other* view still sharing that final
        # document repaints after the view that did the double-``setDocument()`` is destroyed. A
        # single ``setDocument()`` call per instance -- ever -- doesn't carry that corruption, no
        # matter how many separate views end up sharing the result. ``document``, when given (this
        # app's split-editor duplicate view -- see ``TextEditorWidget.__init__``), is therefore the
        # *only* document this instance is ever pointed at, from construction on -- never replaced
        # after starting out with one of its own.
        if document is None:
            # QPlainTextEdit requires its document to use QPlainTextDocumentLayout -- a bare
            # QTextDocument() defaults to QTextDocumentLayout (the rich-text layout), which
            # triggers Qt's "Document set does not support QPlainTextDocumentLayout" warning.
            document = QTextDocument(self)
            document.setDocumentLayout(QPlainTextDocumentLayout(document))
        self.setDocument(document)
        self.path: Path | None = None
        self._highlighter: JsonSyntaxHighlighter | None = None
        self._fold_ranges: dict[int, int] = {}
        self._collapsed_folds: set[int] = set()
        #: Every current schema error's own ``(start, end, message)`` character span -- what
        #: :meth:`_error_message_at` hovers against to show the red-underline tooltip (PROMPT.md:
        #: "it should be a window that appears when hovering on the red underlined text").
        self._error_spans: list[tuple[int, int, str]] = []
        #: Cached result of :meth:`_compute_protected_spans`, refreshed once per actual edit (see
        #: :meth:`_on_text_changed`) rather than recomputed on every call -- :meth:`_protected_spans`
        #: itself is now just a cheap accessor over this. Same reasoning/pattern as
        #: :attr:`_error_spans` right above: confirmed a real, reproducible perf regression
        #: (editor tabs going "very unresponsive") once protected-span coverage grew from a single
        #: cheap forge_labels[].name scan to dozens of fields each requiring their own
        #: find_value_span() call -- keyPressEvent() (every keystroke) *and* mouseMoveEvent() (every
        #: pixel the mouse moves over the editor, to drive the hover tooltip) both called
        #: :meth:`_protected_spans` directly before this, so a big settings/script_settings.json
        #: was re-parsing and re-walking its own JSON dozens of times per second just from normal
        #: mouse movement.
        self._protected_spans_cache: list[tuple[int, int, str]] = []
        #: 0-based block number "Go to Line" last jumped to, if any -- cleared the moment the
        #: cursor moves to a *different* line (see :meth:`_maybe_clear_goto_highlight`), so it
        #: behaves like a one-shot "you are here" marker rather than a permanent current-line
        #: highlight (PROMPT.md: "when going to line number, the editor should highlight the
        #: selected line").
        self._goto_highlight_block: int | None = None
        #: Set by TextEditorWidget right after construction -- see this class's own docstring.
        self._line_number_area: _LineNumberArea | None = None
        self._breadcrumb: _BreadcrumbBar | None = None
        self._minimap: _Minimap | None = None
        self._project_title: str | None = None
        # Needed for mouseMoveEvent() (below) to fire on a plain hover, not just a button-down drag
        # -- how the red-underline tooltip knows to hide again once the pointer leaves the span.
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

        self.textChanged.connect(self._on_text_changed)
        self.cursorPositionChanged.connect(self._update_breadcrumb)
        self.cursorPositionChanged.connect(self._maybe_clear_goto_highlight)

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
        self.refresh_font_scale()
        # Also re-derives fold ranges, not just the breadcrumb -- matters for the split-pane
        # duplicate path (TabPane._duplicate_current_tab), which calls this *after* swapping in
        # the shared document setDocument() points at, whose content this editor hasn't seen a
        # textChanged for yet.
        self._on_text_changed()

    def refresh_font_scale(self) -> None:
        """(Re-)applies :data:`FONT_SCALE` on top of the app's current (zoom-scaled) font for
        :data:`ENLARGED_FILENAMES` specifically -- every other file just gets the plain app font.
        Called from :meth:`set_path` (a fresh open, or a Save As landing on/off one of those
        names) and again after a live zoom change (see
        ``MainWindow._adjust_zoom()``) -- like :meth:`~in_reach.ide.explorer.ExplorerPanel.
        refresh_font_scale`, setting a font directly is a one-time snapshot, not a live binding to
        ``QApplication.font()``, so it goes stale after a zoom change unless this runs again.
        """
        app = QApplication.instance()
        if app is None:
            return
        base_font = app.font()
        if self.path is not None and self.path.name in ENLARGED_FILENAMES:
            font = QFont(base_font)
            font.setPointSizeF(font.pointSizeF() * FONT_SCALE)
            self.setFont(font)
        else:
            self.setFont(base_font)
        # The gutter column's own width is a cached sizeHint(), only ever recomputed when
        # _on_text_changed() (block count) fires -- a font-only change (the +10% enlarged-filename
        # bump above, or a live zoom change re-applying it to an already-loaded tab) never touches
        # the block count, so without this the gutter would keep painting the *new* (differently
        # sized) font's digits inside the *old* font's column width, clipping them.
        if self._line_number_area is not None:
            self._line_number_area.updateGeometry()
            self._line_number_area.update()

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

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.matches(QKeySequence.StandardKey.Save):
            self.save_requested.emit()
            return
        if self._blocks_protected_edit(event):
            return
        # PROMPT.md (Quick Access Bar work): "Indent using spaces" -- a plain Tab (no modifiers, so
        # Shift+Tab's own default Qt focus-navigation behavior is untouched) inserts the project's
        # configured indent width in spaces instead of QPlainTextEdit's own literal-tab-character
        # default, whenever that's the live setting (see in_reach.ide.indent_state).
        if event.key() == Qt.Key.Key_Tab and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            style, width = indent_state.get_indent()
            if style == indent_settings.STYLE_SPACES:
                self.insertPlainText(" " * width)
                return
        super().keyPressEvent(event)

    def insertFromMimeData(self, source) -> None:  # noqa: ANN001 -- QMimeData
        # Paste (also drag-drop/middle-click paste, which never reaches keyPressEvent at all) goes
        # through here regardless of trigger -- see _blocks_protected_edit()'s own docstring.
        cursor = self.textCursor()
        start = cursor.selectionStart() if cursor.hasSelection() else cursor.position()
        end = cursor.selectionEnd() if cursor.hasSelection() else cursor.position()
        if self._range_touches_protected(start, end):
            return
        super().insertFromMimeData(source)

    # -- protected-span editing (the "$schema" line, forge_labels[].name values) ----------------

    def _protected_spans(self) -> list[tuple[int, int, str]]:
        """Cheap accessor over :attr:`_protected_spans_cache` -- see that attribute's own docstring
        for why this doesn't just recompute on every call any more (keyPressEvent/mouseMoveEvent
        both call this very frequently)."""
        return self._protected_spans_cache

    def _compute_protected_spans(self) -> list[tuple[int, int, str]]:
        """Every character span in the current document that can't be edited, each paired with the
        hover-warning message explaining why. Started as a single "$schema"-line special case (see
        :meth:`_schema_line_range`'s own docstring) before PROMPT.md asked for a second,
        structurally different protected span: "entries in forge labels (in script_settings.json)
        should instead not be changeable (the entry in the forge_labels name must always be none
        editable in scrip_settings.json)" -- see :meth:`_forge_label_name_spans`. Only ever called
        from :meth:`_on_text_changed`, to refresh :attr:`_protected_spans_cache` -- see that
        attribute's own docstring for why nothing else should call this directly."""
        spans: list[tuple[int, int, str]] = []
        schema_range = self._schema_line_range()
        if schema_range is not None:
            spans.append((schema_range[0], schema_range[1], _SCHEMA_LINE_WARNING))
        for start, end in self._forge_label_name_spans():
            spans.append((start, end, _FORGE_LABEL_NAME_WARNING))
        spans.extend(self._never_applied_field_spans())
        return spans

    def _forge_label_name_spans(self) -> list[tuple[int, int]]:
        """Character spans of every top-level ``forge_labels[].name`` value, for a
        ``script_settings.json`` document that has a ``forge_labels`` array -- uses the same
        loc-path-to-span machinery as schema_check's own validation-error underlining
        (:func:`~in_reach.ide.json_position.find_value_spans`), so a span stays correct as edits
        elsewhere shift the labels around. Empty (not ``None``) for anything that isn't JSON, isn't
        valid JSON right now, or
        has no ``forge_labels`` array -- nothing to protect."""
        if self.path is None or self.path.suffix.lower() != ".json":
            return []
        text = self.toPlainText()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return []
        forge_labels = data.get("forge_labels") if isinstance(data, dict) else None
        if not isinstance(forge_labels, list):
            return []
        locs = [
            ("forge_labels", index, "name")
            for index, label in enumerate(forge_labels)
            if isinstance(label, dict) and "name" in label
        ]
        return [span for span in find_value_spans(text, locs) if span is not None]

    def _never_applied_field_spans(self) -> list[tuple[int, int, str]]:
        """Every other field settings_writer.py's own module docstring documents as never written
        back by a real Apply, beyond ``forge_labels[].name`` above (see the constants' own
        docstring for why these need protecting at all) -- covers both
        ``settings/settings.json`` (``metadata.description_string``/``category``,
        ``team_settings.teams[].name``) and ``settings/script_settings.json`` (every
        ``forge_labels[].required_object_type_name``/``required_team_name``, every
        ``scripted_options[]``/``scripted_player_traits[]``/``scripted_stats[]`` text field, and
        ``required_object_types.object_type_names``). Keyed off which top-level keys are actually
        present, the same structural check ``_forge_label_name_spans`` uses, not the open file's own
        name -- so this works regardless of what a hand-renamed/copied file happens to be called.
        Empty for anything that isn't JSON, isn't valid JSON right now, or has none of these keys."""
        if self.path is None or self.path.suffix.lower() != ".json":
            return []
        text = self.toPlainText()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return []
        if not isinstance(data, dict):
            return []
        # Collected as (loc, message) pairs and resolved to spans in one single batched pass at the
        # very end (find_value_spans()), rather than one find_value_span() call per field -- each of
        # which would otherwise re-tokenize this entire (possibly large) document from scratch on
        # its own. See _protected_spans_cache's own docstring for why this function's total call
        # frequency (once per keystroke) already makes that cost add up.
        requests: list[tuple[tuple, str]] = []

        def _add(loc: tuple, message: str) -> None:
            requests.append((loc, message))

        try:
            metadata = data["multiplayer"]["game_settings"]["metadata"]
        except (KeyError, TypeError):
            metadata = None
        if isinstance(metadata, dict):
            base = ("multiplayer", "game_settings", "metadata")
            if "description_string" in metadata:
                _add((*base, "description_string"), _DESCRIPTION_STRING_WARNING)
            if "category" in metadata:
                _add((*base, "category"), _CATEGORY_WARNING)

        try:
            teams = data["multiplayer"]["game_settings"]["team_settings"]["teams"]
        except (KeyError, TypeError):
            teams = None
        if isinstance(teams, list):
            base = ("multiplayer", "game_settings", "team_settings", "teams")
            for index, team in enumerate(teams):
                if isinstance(team, dict) and "name" in team:
                    _add((*base, index, "name"), _TEAM_NAME_WARNING)

        forge_labels = data.get("forge_labels")
        if isinstance(forge_labels, list):
            for index, label in enumerate(forge_labels):
                if not isinstance(label, dict):
                    continue
                for field in ("required_object_type_name", "required_team_name"):
                    if label.get(field) is not None:
                        _add(("forge_labels", index, field), _RESOLVED_NAME_WARNING)

        scripted_options = data.get("scripted_options")
        if isinstance(scripted_options, list):
            for index, option in enumerate(scripted_options):
                if not isinstance(option, dict):
                    continue
                base = ("scripted_options", index)
                for field in ("name", "desc"):
                    if field in option:
                        _add((*base, field), _SCRIPTED_TEXT_WARNING)
                values = option.get("values")
                if isinstance(values, list):
                    for v_index, value in enumerate(values):
                        if not isinstance(value, dict):
                            continue
                        v_base = (*base, "values", v_index)
                        for field in ("name", "desc"):
                            if field in value:
                                _add((*v_base, field), _SCRIPTED_TEXT_WARNING)
                for range_field in ("range_default", "range_min", "range_max"):
                    range_value = option.get(range_field)
                    if isinstance(range_value, dict):
                        r_base = (*base, range_field)
                        for field in ("name", "desc"):
                            if field in range_value:
                                _add((*r_base, field), _SCRIPTED_TEXT_WARNING)

        scripted_player_traits = data.get("scripted_player_traits")
        if isinstance(scripted_player_traits, list):
            for index, trait in enumerate(scripted_player_traits):
                if not isinstance(trait, dict):
                    continue
                base = ("scripted_player_traits", index)
                for field in ("name", "desc"):
                    if field in trait:
                        _add((*base, field), _SCRIPTED_TEXT_WARNING)

        scripted_stats = data.get("scripted_stats")
        if isinstance(scripted_stats, list):
            for index, stat in enumerate(scripted_stats):
                if isinstance(stat, dict) and "name" in stat:
                    _add(("scripted_stats", index, "name"), _SCRIPTED_TEXT_WARNING)

        required_object_types = data.get("required_object_types")
        if isinstance(required_object_types, dict):
            object_type_names = required_object_types.get("object_type_names")
            if isinstance(object_type_names, list):
                base = ("required_object_types", "object_type_names")
                for index in range(len(object_type_names)):
                    _add((*base, index), _RESOLVED_NAME_WARNING)

        spans: list[tuple[int, int, str]] = []
        found_spans = find_value_spans(text, [loc for loc, _message in requests])
        for (_loc, message), span in zip(requests, found_spans):
            if span is not None:
                spans.append((span[0], span[1], message))
        return spans

    def _schema_line_range(self) -> tuple[int, int] | None:
        """The character span (the start of its own line through the start of the *next* line --
        i.e. including its own trailing newline) of a top-level ``"$schema"`` key's line, for a
        JSON document that has one -- PROMPT.md: "the schema section of the jsons should not be
        editable". Recomputed fresh off the live text on every check rather than cached, so it
        stays correct as edits elsewhere in the document shift it up or down. ``None`` for anything
        that isn't JSON, or JSON with no ``"$schema"`` key at all (nothing to protect)."""
        if self.path is None or self.path.suffix.lower() != ".json":
            return None
        block = self.document().firstBlock()
        while block.isValid():
            if block.text().lstrip().startswith('"$schema"'):
                start = block.position()
                next_block = block.next()
                end = next_block.position() if next_block.isValid() else start + block.length()
                return start, end
            block = block.next()
        return None

    def _range_touches_protected(self, start: int, end: int) -> bool:
        return any(
            start < span_end and end > span_start
            for span_start, span_end, _ in self._protected_spans()
        )

    def _blocks_protected_edit(self, event: QKeyEvent) -> bool:
        """Whether ``event`` would insert into, or delete from, a protected span (the "$schema"
        line, or a forge label's ``name`` value) -- checked before any other key handling in
        :meth:`keyPressEvent`. A selection overlapping a span blocks *any* key that would replace
        it (typing, Backspace/Delete, Cut -- checking the selection alone covers all of these
        identically, whichever key triggered it). With a bare cursor and no selection, only
        Backspace/Delete/plain typing are destructive at all, and Backspace also blocks right at a
        span's own start -- otherwise it would merge the preceding text into it without deleting
        anything the span itself covers, silently defeating protection on the very next check."""
        cursor = self.textCursor()
        if cursor.hasSelection():
            return self._range_touches_protected(cursor.selectionStart(), cursor.selectionEnd())
        pos = cursor.position()
        for span_start, span_end, _ in self._protected_spans():
            if event.key() == Qt.Key.Key_Backspace:
                if span_start <= pos <= span_end:
                    return True
            elif event.key() == Qt.Key.Key_Delete:
                if span_start <= pos < span_end:
                    return True
            elif event.text():
                if span_start <= pos < span_end:
                    return True
        return False

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
        if any -- what the red wavy underline's own hover tooltip shows. Falls back to
        :meth:`_protected_span_warning_at` (PROMPT.md: "add a helper text when a user hovers over
        schema in settings that warns the user they cannot edit that section of the jsons") once
        there's no actual validation error to report -- the two never really overlap in practice
        (the "$schema" key itself is excluded from validation, see schema_check.find_errors), but
        checking spans first keeps a real error message from ever being shadowed either way."""
        char_pos = self.cursorForPosition(pos).position()
        for start, end, message in self._error_spans:
            if start <= char_pos < end:
                return message
        return self._protected_span_warning_at(char_pos)

    def _protected_span_warning_at(self, char_pos: int) -> str | None:
        for start, end, message in self._protected_spans():
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
        # _line_number_area is a QGridLayout-managed *sibling* of this editor, not a child of it
        # (see this module's own docstring), so it never reliably inherits this editor's own font
        # (e.g. the +10% ENLARGED_FILENAMES bump above) purely through Qt's normal parent-child
        # font cascade -- painting explicitly with this editor's *own* current font is what keeps
        # the gutter's line numbers the same size as the text they're numbering, always.
        painter.setFont(self.font())

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
        if self._line_number_area is not None:
            self._line_number_area.update()

    def _on_text_changed(self) -> None:
        self._fold_ranges = compute_fold_ranges(self.toPlainText())
        self._collapsed_folds &= self._fold_ranges.keys()
        self._apply_fold_visibility()
        self._update_breadcrumb()
        self._update_schema_validation()
        self._protected_spans_cache = self._compute_protected_spans()
        if self._line_number_area is not None:
            self._line_number_area.updateGeometry()

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
            self._error_spans = []
            if self._minimap is not None:
                self._minimap.set_error_lines(set())
            self._apply_extra_selections([])
            return

        doc = self.document()
        spans: list[tuple[int, int, str]] = []
        error_lines: set[int] = set()
        for error in errors:
            if error.span is None:
                # A JSON-syntax error at end-of-file, say -- nothing to underline/hover, but it
                # still blocks the save (validate_before_save doesn't need a span at all).
                continue
            start, end = error.span
            spans.append((start, end, error.message))
            error_lines.add(doc.findBlock(start).blockNumber())
        self._error_spans = spans
        if self._minimap is not None:
            self._minimap.set_error_lines(error_lines)
        self._apply_extra_selections(self._error_selections())

    # -- "Go to Line" highlight -----------------------------------------------------------------

    def highlight_line(self, block_number: int) -> None:
        """Highlights ``block_number`` (0-based) with a full-width background in both this editor
        and its own minimap, until the cursor moves to a different line -- PROMPT.md: "when going
        to line number, the editor should highlight the selected line (in both the main window and
        in the side preview)". Called by ``MainWindow``'s own "Go to Line" handler right after it
        moves the cursor there."""
        self._goto_highlight_block = block_number
        if self._minimap is not None:
            self._minimap.set_highlight_line(block_number)
        self._apply_extra_selections(self._error_selections())

    def _maybe_clear_goto_highlight(self) -> None:
        """Drops the "Go to Line" highlight the moment the cursor lands on a different line --
        e.g. the user starts typing or clicks elsewhere. A no-op while the cursor is still sitting
        on the just-jumped-to line, including the very ``cursorPositionChanged`` the jump itself
        fires."""
        if self._goto_highlight_block is None:
            return
        if self.textCursor().blockNumber() == self._goto_highlight_block:
            return
        self._goto_highlight_block = None
        if self._minimap is not None:
            self._minimap.set_highlight_line(None)
        self._apply_extra_selections(self._error_selections())

    def _error_selections(self) -> list[QTextEdit.ExtraSelection]:
        """Rebuilds just the schema-error underline selections (cheap: :attr:`_error_spans` is
        already computed) -- used to redraw them alongside a freshly changed "Go to Line" highlight
        without re-running the schema check itself."""
        doc = self.document()
        selections = []
        for start, end, _message in self._error_spans:
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
        return selections

    def _apply_extra_selections(self, base_selections: list[QTextEdit.ExtraSelection]) -> None:
        """``setExtraSelections()`` only ever accepts one combined list, so every source of extra
        selections (schema-error underlines, the "Go to Line" highlight) has to be merged here
        rather than each calling ``setExtraSelections()`` on its own, which would just clobber
        whichever one ran last."""
        selections = list(base_selections)
        if self._goto_highlight_block is not None:
            block = self.document().findBlockByNumber(self._goto_highlight_block)
            if block.isValid():
                cursor = QTextCursor(block)
                fmt = QTextCharFormat()
                highlight_color = self.palette().color(QPalette.ColorRole.Highlight)
                highlight_color.setAlpha(_GOTO_LINE_HIGHLIGHT_ALPHA)
                fmt.setBackground(highlight_color)
                fmt.setProperty(QTextFormat.Property.FullWidthSelection, True)
                selection = QTextEdit.ExtraSelection()
                selection.cursor = cursor
                selection.format = fmt
                selections.append(selection)
        self.setExtraSelections(selections)

    # -- breadcrumb ---------------------------------------------------------------------------------

    def _update_breadcrumb(self) -> None:
        if self._breadcrumb is None:
            return
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


class TextEditorWidget(QWidget):
    """One text-editor tab's content -- see this module's own docstring for why this is a plain
    ``QWidget`` composing the real editor rather than being one itself.

    Dirty tracking rides ``QTextDocument``'s own ``isModified()``/``modificationChanged`` --
    no extra state lives here.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        path: Path | None = None,
        document: QTextDocument | None = None,
    ) -> None:
        super().__init__(parent)
        # document, when given, is a split-editor duplicate's source document -- see
        # _PlainTextEditor.__init__'s own docstring for why this has to be handed straight to its
        # constructor rather than assigned afterward via a second setDocument() call.
        self._edit = _PlainTextEditor(document)
        self._line_number_area = _LineNumberArea(self._edit)
        self._breadcrumb = _BreadcrumbBar()
        self._minimap = _Minimap(self._edit)
        # PROMPT.md: "please add an option for Find ... and Replace" -- hidden until open()/
        # open_find() shows it, taking no layout space while closed (see find_replace.py's own
        # module docstring).
        self._find_bar = FindReplaceBar(self._edit)
        # See _PlainTextEditor's own docstring -- it reads these back through its own instance
        # attributes of the same names, set here rather than created there.
        self._edit._line_number_area = self._line_number_area
        self._edit._breadcrumb = self._breadcrumb
        self._edit._minimap = self._minimap

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._find_bar, 0, 0, 1, 3)
        layout.addWidget(self._breadcrumb, 1, 0, 1, 3)
        layout.addWidget(self._line_number_area, 2, 0)
        layout.addWidget(self._edit, 2, 1)
        layout.addWidget(self._minimap, 2, 2)
        layout.setColumnStretch(1, 1)
        layout.setRowStretch(2, 1)

        # The gutter's own column only actually grows/shrinks when something tells the layout its
        # sizeHint() changed -- _PlainTextEditor._on_text_changed() already calls this whenever the
        # block count (and so the digit width) might have; a scrollbar-only value change never
        # changes that width, so nothing needs to re-trigger it from here.
        self._edit.blockCountChanged.connect(lambda _count: self._minimap.update())
        self._edit.verticalScrollBar().valueChanged.connect(lambda _value: self._minimap.update())

        self.setFocusProxy(self._edit)
        self._edit.set_path(path)

    # -- find/replace ---------------------------------------------------------------------------

    def open_find(self, *, replace: bool = False) -> None:
        """Shows this tab's own Find/Replace bar -- MainWindow's Ctrl+F/Ctrl+R shortcuts (PROMPT.md)
        route here via ``MainWindow._active_text_editor()``, same as Undo/Redo/Cut/Copy/Paste."""
        self._find_bar.open(replace=replace)

    def close_find(self) -> None:
        self._find_bar.close_bar()

    # -- explicit forwarding for the handful of QWidget-*native* methods QPlainTextEdit also has --
    #
    # __getattr__ below only ever fires once *normal* attribute lookup (this class's own __dict__/
    # MRO) has already failed -- and since this wrapper is itself a QWidget, anything QWidget
    # already defines (font/setFont, fontMetrics, palette) resolves to *this widget's own*
    # (irrelevant, never-set) value without __getattr__ ever being consulted at all. Every caller
    # that reads one of these really means the real editor's own font/metrics/palette (e.g.
    # refresh_font_scale()'s own +10% sizing, or a test asserting against it) -- these three make
    # that the widget-level default `.font()`/`.fontMetrics()`/`.palette()` still resolve there,
    # the same way __getattr__ handles everything QWidget *doesn't* also define.
    def font(self) -> QFont:
        return self._edit.font()

    def setFont(self, font: QFont) -> None:
        self._edit.setFont(font)

    def fontMetrics(self):
        return self._edit.fontMetrics()

    def palette(self) -> QPalette:
        return self._edit.palette()

    def __getattr__(self, name):
        # Forwards anything not defined on this wrapper directly to the real QPlainTextEdit --
        # preserves this class's long-standing "acts just like a QPlainTextEdit" contract for
        # every caller across tabs.py/main_window.py (toPlainText, document, textCursor,
        # setReadOnly, blockCount, save_requested, ...) without hand-enumerating its huge method
        # surface. Only reached when normal attribute lookup (this class's own __dict__/MRO)
        # already failed, so anything defined here (or on QWidget) always wins over the fallback --
        # see the explicit font/fontMetrics/palette forwarding right above for the methods that
        # need exactly that override because QWidget already defines them.
        edit = self.__dict__.get("_edit")
        if edit is None:
            raise AttributeError(name)
        return getattr(edit, name)
