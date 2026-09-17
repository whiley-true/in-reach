"""VSCode-style Find/Replace bar (PROMPT.md: "Under edit in the top bar, please add an option for
Find with shortcut CTRL + F and Replace with shortcut CTRL + R, see find_and_replace_red.png[:] it
should show a find and replace bar (cursored on find or replace depending on selection)[, with]
the options for match case, match whole word, match regular expression - results counts, previous
result (with shortcut for shift + enter), next match with enter, find in selection and close (with
shortcut escape)[; r]eplace should have preserve case, replace (enter) replace all (ctrl + shift +
enter) (we want to mimic vsocde essentially)").

One instance lives inside each :class:`~in_reach.ide.editor.TextEditorWidget` (see that module's
own layout), operating on that tab's own real ``QPlainTextEdit``/``QTextDocument`` -- never shown
until :meth:`FindReplaceBar.open` is called (MainWindow's own Ctrl+F/Ctrl+R shortcuts, routed
through whichever tab is currently active), and collapses back to taking no layout space at all
once closed (a hidden widget contributes nothing to its layout's sizeHint -- same trick the
activity bar's own overflow button relies on, see activity_bar.py's own _IconStrip docstring).
"""

from __future__ import annotations

import re

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QTextCursor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from in_reach.ide import icons

_BAR_STYLE = (
    "QWidget#findReplaceBar { background-color: palette(alternate-base);"
    " border-bottom: 1px solid palette(mid); }"
)
_TOGGLE_STYLE = (
    "QToolButton { border: 1px solid transparent; border-radius: 3px; padding: 1px 5px;"
    " color: palette(text); }"
    "QToolButton:checked { background-color: palette(highlight); border-color: palette(highlight);"
    " color: palette(highlighted-text); }"
)
_CLOSE_ICON_SIZE = 12


def compile_search_pattern(
    query: str, *, match_case: bool, whole_word: bool, regex: bool
) -> re.Pattern | None:
    """The compiled pattern ``query`` (under the current match-case/whole-word/regex options)
    resolves to, or ``None`` for an empty query or an invalid regex -- shared by both live
    highlighting/counting and Replace All, so the two can never disagree about what "matches".
    """
    if not query:
        return None
    flags = 0 if match_case else re.IGNORECASE
    pattern = query if regex else re.escape(query)
    if whole_word and not regex:
        pattern = rf"\b{pattern}\b"
    try:
        return re.compile(pattern, flags)
    except re.error:
        return None


def preserve_case(original: str, replacement: str) -> str:
    """PROMPT.md: "replace should have preserve case" -- VSCode's own heuristic: an all-uppercase
    match gets an all-uppercase replacement, a capitalized (title-case first letter) match gets a
    capitalized replacement, anything else is left alone."""
    if not original or not replacement:
        return replacement
    if original.isupper():
        return replacement.upper()
    if original[0].isupper() and original[1:].islower():
        return replacement[0].upper() + replacement[1:]
    return replacement


def _toggle_button(text: str, tooltip: str) -> QToolButton:
    button = QToolButton()
    button.setText(text)
    button.setCheckable(True)
    button.setToolTip(tooltip)
    button.setAutoRaise(True)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setStyleSheet(_TOGGLE_STYLE)
    return button


class _FindLineEdit(QLineEdit):
    """Relays Enter/Shift+Enter/Escape (and, for the replace field, Ctrl+Shift+Enter) to the owning
    bar -- both the find and replace fields need this, so it's shared rather than duplicated."""

    def __init__(self, bar: "FindReplaceBar", *, is_replace: bool) -> None:
        super().__init__(bar)
        self._bar = bar
        self._is_replace = is_replace

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._bar.close_bar()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            if self._is_replace:
                if ctrl and shift:
                    self._bar.replace_all()
                else:
                    self._bar.replace_current()
                return
            if shift:
                self._bar.find_previous()
            else:
                self._bar.find_next()
            return
        super().keyPressEvent(event)


class FindReplaceBar(QWidget):
    """The bar itself -- a find row (always present once open) and a replace row (shown only when
    opened in replace mode, or expanded via :meth:`set_replace_visible`)."""

    closed = pyqtSignal()

    def __init__(self, editor: QPlainTextEdit, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._editor = editor
        self._matches: list[tuple[int, int]] = []
        self._current: int = -1
        #: Captured the moment "Find in Selection" is turned on -- the (start, end) span matches
        #: are restricted to until it's turned back off. ``None`` means "whole document".
        self._selection_range: tuple[int, int] | None = None
        self.setObjectName("findReplaceBar")
        self.setStyleSheet(_BAR_STYLE)
        self.hide()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 4, 6, 4)
        outer.setSpacing(2)

        # -- find row ---------------------------------------------------------------------------
        find_row = QHBoxLayout()
        find_row.setSpacing(4)
        self.find_input = _FindLineEdit(self, is_replace=False)
        self.find_input.setPlaceholderText("Find")
        self.find_input.textChanged.connect(self._refresh_matches)
        find_row.addWidget(self.find_input, 1)

        self.match_case_button = _toggle_button("Aa", "Match Case")
        self.whole_word_button = _toggle_button("ab", "Match Whole Word")
        self.regex_button = _toggle_button(".*", "Use Regular Expression")
        for button in (self.match_case_button, self.whole_word_button, self.regex_button):
            button.toggled.connect(self._refresh_matches)
            find_row.addWidget(button)

        # PROMPT.md: "find in selection" -- captures the editor's current selection the moment
        # this is turned on (see _on_find_in_selection_toggled), same "snapshot once, not a live
        # binding" reasoning as _PlainTextEditor's own "$schema" line-protection span.
        self.find_in_selection_button = _toggle_button("[¶]", "Find in Selection")
        self.find_in_selection_button.toggled.connect(self._on_find_in_selection_toggled)
        find_row.addWidget(self.find_in_selection_button)

        self.count_label = QLabel("No results")
        self.count_label.setEnabled(False)
        find_row.addWidget(self.count_label)

        self.previous_button = QToolButton()
        self.previous_button.setText("↑")
        self.previous_button.setToolTip("Previous Match (Shift+Enter)")
        self.previous_button.setAutoRaise(True)
        self.previous_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.previous_button.clicked.connect(self.find_previous)
        find_row.addWidget(self.previous_button)

        self.next_button = QToolButton()
        self.next_button.setText("↓")
        self.next_button.setToolTip("Next Match (Enter)")
        self.next_button.setAutoRaise(True)
        self.next_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_button.clicked.connect(self.find_next)
        find_row.addWidget(self.next_button)

        self.close_button = QToolButton()
        self.close_button.setIcon(icons.icon("win_close", size=_CLOSE_ICON_SIZE))
        self.close_button.setToolTip("Close (Escape)")
        self.close_button.setAutoRaise(True)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.clicked.connect(self.close_bar)
        find_row.addWidget(self.close_button)

        outer.addLayout(find_row)

        # -- replace row --------------------------------------------------------------------------
        self._replace_row = QWidget()
        replace_row = QHBoxLayout(self._replace_row)
        replace_row.setContentsMargins(0, 0, 0, 0)
        replace_row.setSpacing(4)
        self.replace_input = _FindLineEdit(self, is_replace=True)
        self.replace_input.setPlaceholderText("Replace")
        replace_row.addWidget(self.replace_input, 1)

        self.preserve_case_button = _toggle_button("AB", "Preserve Case")
        replace_row.addWidget(self.preserve_case_button)

        self.replace_button = QToolButton()
        self.replace_button.setText("Replace")
        self.replace_button.setToolTip("Replace (Enter)")
        self.replace_button.setAutoRaise(True)
        self.replace_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.replace_button.clicked.connect(self.replace_current)
        replace_row.addWidget(self.replace_button)

        self.replace_all_button = QToolButton()
        self.replace_all_button.setText("Replace All")
        self.replace_all_button.setToolTip("Replace All (Ctrl+Shift+Enter)")
        self.replace_all_button.setAutoRaise(True)
        self.replace_all_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.replace_all_button.clicked.connect(self.replace_all)
        replace_row.addWidget(self.replace_all_button)

        outer.addWidget(self._replace_row)
        self._replace_row.hide()

    # -- open/close -------------------------------------------------------------------------------

    def open(self, *, replace: bool = False) -> None:
        """Shows the bar -- PROMPT.md: "cursored on find or replace depending on" which of Ctrl+F/
        Ctrl+R opened it. Re-opening (the shortcut fired again while already open) just refocuses
        the relevant field rather than resetting anything the user's already typed."""
        self.set_replace_visible(replace)
        self.show()
        target = self.replace_input if replace else self.find_input
        target.setFocus()
        target.selectAll()
        self._refresh_matches()

    def set_replace_visible(self, visible: bool) -> None:
        self._replace_row.setVisible(visible)

    def close_bar(self) -> None:
        self.hide()
        self._matches = []
        self._current = -1
        self.closed.emit()
        self._editor.setFocus()

    # -- search -------------------------------------------------------------------------------------

    def _pattern(self) -> re.Pattern | None:
        return compile_search_pattern(
            self.find_input.text(),
            match_case=self.match_case_button.isChecked(),
            whole_word=self.whole_word_button.isChecked(),
            regex=self.regex_button.isChecked(),
        )

    def _on_find_in_selection_toggled(self, checked: bool) -> None:
        if checked:
            cursor = self._editor.textCursor()
            self._selection_range = (
                (cursor.selectionStart(), cursor.selectionEnd()) if cursor.hasSelection() else None
            )
        else:
            self._selection_range = None
        self._refresh_matches()

    def _refresh_matches(self) -> None:
        pattern = self._pattern()
        text = self._editor.toPlainText()
        if pattern is None:
            self._matches = []
        else:
            search_text = text
            if self._selection_range is not None:
                start, end = self._selection_range
                search_text = text[start:end]
            else:
                start = 0
            self._matches = [
                (m.start() + start, m.end() + start) for m in pattern.finditer(search_text)
            ]
        self._current = -1
        if self._matches:
            # Jumps straight to the match at (or after) the cursor's current position, rather than
            # always restarting from the very first one -- matches VSCode's own "start typing,
            # jump to the nearest hit" behavior.
            pos = self._editor.textCursor().position()
            self._current = next(
                (i for i, (s, _e) in enumerate(self._matches) if s >= pos), 0
            )
            self._select_match(self._current)
        else:
            self._update_count_label()

    def _select_match(self, index: int) -> None:
        if not self._matches:
            return
        start, end = self._matches[index]
        cursor = self._editor.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self._editor.setTextCursor(cursor)
        self._editor.ensureCursorVisible()
        self._update_count_label()

    def _update_count_label(self) -> None:
        if not self._matches:
            self.count_label.setText("No results")
        else:
            self.count_label.setText(f"{self._current + 1} of {len(self._matches)}")

    def find_next(self) -> None:
        if not self._matches:
            self._refresh_matches()
            return
        self._current = (self._current + 1) % len(self._matches)
        self._select_match(self._current)

    def find_previous(self) -> None:
        if not self._matches:
            self._refresh_matches()
            return
        self._current = (self._current - 1) % len(self._matches)
        self._select_match(self._current)

    # -- replace ------------------------------------------------------------------------------------

    def _replacement_for(self, original: str) -> str:
        replacement = self.replace_input.text()
        if self.preserve_case_button.isChecked():
            replacement = preserve_case(original, replacement)
        return replacement

    def replace_current(self) -> None:
        if not self._matches or self._current < 0:
            return
        start, end = self._matches[self._current]
        cursor = self._editor.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        original = cursor.selectedText()
        cursor.insertText(self._replacement_for(original))
        self._refresh_matches()

    def replace_all(self) -> None:
        if not self._matches:
            return
        cursor = self._editor.textCursor()
        cursor.beginEditBlock()
        try:
            # Backwards, so replacing one match (whose replacement length may differ from the
            # original) never shifts the still-untouched offsets of the ones before it.
            for start, end in reversed(self._matches):
                match_cursor = QTextCursor(self._editor.document())
                match_cursor.setPosition(start)
                match_cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                original = match_cursor.selectedText()
                match_cursor.insertText(self._replacement_for(original))
        finally:
            cursor.endEditBlock()
        self._refresh_matches()
