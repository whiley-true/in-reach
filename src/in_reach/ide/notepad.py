"""The Dashboard's "Notepad" box (PROMPT.md: "in dashboard please add a 'Notepad' section that
should be box at the bottom that loads the contents of a notepad (with line nums) ... it should be
possible to load in editor tab or in popout window ... it should have a placeholder along the lines
of '- Use this space for any rough notes. For more structured Documentation use the Documentation
Panel'").

The notepad is the active project's own ``Notes.txt`` (every project already has one, see
:data:`in_reach.app.new_project.NOTES_FILENAME`), edited in place and written straight back to disk
a moment after typing stops -- no Save button, since it's meant for rough notes rather than
something the user needs to commit to. The two buttons above it hand the same file over to a real
editor tab or a popout window (MainWindow owns actually opening either, see
:attr:`NotepadBox.open_in_editor_requested`/:attr:`NotepadBox.open_in_window_requested`).

The line-number gutter is a small purpose-built one, not the full :class:`~in_reach.ide.editor.
TextEditorWidget` (which carries a minimap, breadcrumb, fold markers and a find bar -- all more
than a Dashboard box wants), following Qt's own standard "code editor" line-number recipe.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter, QPalette, QPaintEvent, QResizeEvent
from PyQt6.QtWidgets import QHBoxLayout, QPlainTextEdit, QToolButton, QVBoxLayout, QWidget

#: PROMPT.md's own placeholder text, verbatim.
NOTEPAD_PLACEHOLDER = (
    "- Use this space for any rough notes. For more structured Documentation use the "
    "Documentation Panel"
)

#: How long typing has to pause before the box writes itself back to disk.
AUTOSAVE_DELAY_MS = 600

_GUTTER_PADDING = 6


class _Gutter(QWidget):
    def __init__(self, edit: "NotepadEdit") -> None:
        super().__init__(edit)
        self._edit = edit

    def sizeHint(self) -> QSize:
        return QSize(self._edit.gutter_width(), 0)

    def paintEvent(self, event: QPaintEvent) -> None:
        self._edit.paint_gutter(event)


class NotepadEdit(QPlainTextEdit):
    """A plain-text box with a line-number gutter down its left edge."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(NOTEPAD_PLACEHOLDER)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._gutter = _Gutter(self)
        self.blockCountChanged.connect(self._update_margin)
        self.updateRequest.connect(self._on_update_request)
        self._update_margin()

    def gutter_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return _GUTTER_PADDING * 2 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_margin(self) -> None:
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)
        self._place_gutter()

    def _place_gutter(self) -> None:
        contents = self.contentsRect()
        self._gutter.setGeometry(QRect(contents.left(), contents.top(), self.gutter_width(), contents.height()))

    def _on_update_request(self, rect: QRect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_margin()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._place_gutter()

    def changeEvent(self, event) -> None:  # noqa: ANN001 -- QEvent
        super().changeEvent(event)
        if event.type() == event.Type.FontChange:
            self._update_margin()

    def paint_gutter(self, event: QPaintEvent) -> None:
        """Draws every visible block's 1-based line number, right-aligned -- walking
        ``firstVisibleBlock()`` forward keeps this correct under wrapped lines (one block can
        occupy several pixel rows)."""
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), self.palette().color(QPalette.ColorRole.AlternateBase))
        painter.setFont(self.font())
        painter.setPen(self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText))

        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.drawText(
                    0,
                    top,
                    self._gutter.width() - _GUTTER_PADDING,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    str(number + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            number += 1
        painter.end()


class NotepadBox(QWidget):
    """The Dashboard's Notepad body: an "Open in Editor"/"Open in Window" button row above a
    :class:`NotepadEdit` bound to one file."""

    #: The user asked to open the notepad file as a regular editor tab / in a popout window.
    open_in_editor_requested = pyqtSignal()
    open_in_window_requested = pyqtSignal()
    #: Emitted with the file's path right after the box writes it to disk.
    saved = pyqtSignal(Path)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path: Path | None = None
        self._loading = False
        self._dirty = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        self.open_in_editor_button = QToolButton()
        self.open_in_editor_button.setText("Open in Editor")
        self.open_in_editor_button.setToolTip("Open the notepad in an editor tab")
        self.open_in_editor_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_in_editor_button.clicked.connect(self.open_in_editor_requested.emit)
        button_row.addWidget(self.open_in_editor_button)
        self.open_in_window_button = QToolButton()
        self.open_in_window_button.setText("Open in Window")
        self.open_in_window_button.setToolTip("Open the notepad in its own popout window")
        self.open_in_window_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_in_window_button.clicked.connect(self.open_in_window_requested.emit)
        button_row.addWidget(self.open_in_window_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self.edit = NotepadEdit()
        # Small floor so the Dashboard's own minimum height stays modest -- the box itself takes
        # whatever vertical room the sidebar has left over (see ExplorerPanel's own layout).
        self.edit.setMinimumHeight(80)
        self.edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.edit, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(AUTOSAVE_DELAY_MS)
        self._timer.timeout.connect(self.flush)

        self._sync_enabled()

    # -- file binding -----------------------------------------------------------------------------

    @property
    def path(self) -> Path | None:
        return self._path

    def set_path(self, path: Path | None) -> None:
        """Points the box at ``path`` (or, for ``None``, unbinds it and disables editing) and loads
        its content. Anything typed but not yet written to the *previous* file is flushed first.
        A file that doesn't exist yet just loads as empty -- it's only created once something is
        actually typed."""
        self.flush()
        self._path = path
        self._sync_enabled()
        self.reload()

    def reload(self) -> None:
        """Re-reads the bound file from disk, discarding anything typed but not yet written."""
        self._timer.stop()
        self._dirty = False
        text = ""
        if self._path is not None:
            try:
                text = self._path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                text = ""
        self._loading = True
        try:
            self.edit.setPlainText(text)
        finally:
            self._loading = False

    def flush(self) -> None:
        """Writes any pending edit straight to disk now, instead of waiting out the autosave
        delay -- called before handing the file to an editor tab, and when the bound file changes.
        A no-op if nothing's pending."""
        self._timer.stop()
        if not self._dirty or self._path is None:
            return
        try:
            self._path.write_text(self.edit.toPlainText(), encoding="utf-8")
        except OSError:
            return
        self._dirty = False
        self.saved.emit(self._path)

    def _on_text_changed(self) -> None:
        if self._loading or self._path is None:
            return
        self._dirty = True
        self._timer.start()

    def _sync_enabled(self) -> None:
        bound = self._path is not None
        self.edit.setEnabled(bound)
        self.open_in_editor_button.setEnabled(bound)
        self.open_in_window_button.setEnabled(bound)
