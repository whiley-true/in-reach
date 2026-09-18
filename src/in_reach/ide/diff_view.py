"""A VSCode-style side-by-side diff view, opened as a real tab (PROMPT.md: "when clicking on
changes to a file (in the changes tab) a tab should appear showing the original on the left and
highlighted changes on the right (like vscode git)") -- the Git panel's own "Changes" list is what
opens one (see ``MainWindow.vcs_open_diff``), one file at a time, always for that file's own
uncommitted change (``HEAD`` on the left, the current on-disk content on the right; see
:func:`~in_reach.app.vcs.uncommitted_file_diff`).

Line-aligned (:func:`_align`), not just two independent scrollable texts: a block only present on
one side gets matching blank filler lines on the other, so unrelated lines never appear side by side
just because they happen to land on the same row -- the same shape VSCode's own diff editor renders
(and distinct from :mod:`in_reach.ide.diff_dialog`'s plain unified-diff text, which this doesn't
replace -- that one's for comparing two *committed* refs, this one's for the live working tree).
"""

from __future__ import annotations

import difflib

from PyQt6.QtGui import QColor, QFontDatabase, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QTextEdit, QVBoxLayout, QWidget

#: Translucent so the theme's own editor background still shows through -- same "alpha over
#: whatever's there" approach as editor.py's own _GOTO_LINE_HIGHLIGHT_ALPHA.
_REMOVED_COLOR = QColor(244, 63, 94, 45)
_ADDED_COLOR = QColor(34, 197, 94, 45)
_BLANK_COLOR = QColor(128, 128, 128, 25)

_LINE_KIND_COLOR = {"removed": _REMOVED_COLOR, "added": _ADDED_COLOR, "blank": _BLANK_COLOR}


def _align(old_lines: list[str], new_lines: list[str]) -> tuple[list[str], list[str], list[str], list[str]]:
    """Returns ``(left_lines, left_kinds, right_lines, right_kinds)`` -- ``old_lines``/``new_lines``
    padded with blank filler lines so corresponding rows line up, each paired with its own
    per-line ``"equal"``/``"removed"``/``"added"``/``"blank"`` kind for :class:`DiffViewWidget` to
    color. A ``"replace"`` opcode (a block swapped for a differently-sized one) pads whichever side
    is shorter -- this renders it as a plain removed-block/added-block pair rather than trying to
    word-align individual replaced lines, the same simple line-level treatment VSCode's own diff
    editor defaults to."""
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    left_lines: list[str] = []
    left_kinds: list[str] = []
    right_lines: list[str] = []
    right_kinds: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                left_lines.append(old_lines[i1 + k])
                left_kinds.append("equal")
                right_lines.append(new_lines[j1 + k])
                right_kinds.append("equal")
        elif tag == "delete":
            for k in range(i2 - i1):
                left_lines.append(old_lines[i1 + k])
                left_kinds.append("removed")
                right_lines.append("")
                right_kinds.append("blank")
        elif tag == "insert":
            for k in range(j2 - j1):
                left_lines.append("")
                left_kinds.append("blank")
                right_lines.append(new_lines[j1 + k])
                right_kinds.append("added")
        elif tag == "replace":
            old_block = old_lines[i1:i2]
            new_block = new_lines[j1:j2]
            for k in range(max(len(old_block), len(new_block))):
                if k < len(old_block):
                    left_lines.append(old_block[k])
                    left_kinds.append("removed")
                else:
                    left_lines.append("")
                    left_kinds.append("blank")
                if k < len(new_block):
                    right_lines.append(new_block[k])
                    right_kinds.append("added")
                else:
                    right_lines.append("")
                    right_kinds.append("blank")
    return left_lines, left_kinds, right_lines, right_kinds


class _DiffPane(QPlainTextEdit):
    """One read-only side of the diff -- plain except for the per-line background coloring
    :meth:`set_lines` applies."""

    def __init__(self) -> None:
        super().__init__()
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))

    def set_lines(self, lines: list[str], kinds: list[str]) -> None:
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
        left_lines, left_kinds, right_lines, right_kinds = _align(old_lines, new_lines)
        self.old_pane.set_lines(left_lines, left_kinds)
        self.new_pane.set_lines(right_lines, right_kinds)

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
