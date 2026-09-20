"""Syntax highlighting for Megalo script text: a project's ``.mgl`` blocks and modules, ``script/output.txt`` and the
generated ``build/Compiled.txt``.

Line-based and regex-driven rather than built on :mod:`in_reach.app.rvt.megalo_ast`'s lexer: a half-typed script is the
normal state of an editor, and colouring must never depend on the text being parseable. It knows what the language and
the module layer make significant:

* keywords (``if``/``then``/``altif``/``alt``/``do``/``end``/``for each``/``on``/``function``/``alias``/``declare``/
  ``and``/``or``/``not``/``inline``) and the built-in roots (``current_player``, ``global``, ``temporaries``, ...);
* strings, numbers and percentages;
* ``--`` comments -- and inside them the metadata that isn't a comment at all: ``-- @fragment``, ``-- @number`` and the
  other annotations, and the build-profile directives ``-- @if FLAG`` / ``-- @else`` / ``-- @end``, each coloured on
  its own;
* ``${NAME}`` placeholders, in code and in annotation arguments alike.

The palette is fixed, like :mod:`in_reach.ide.json_highlighter`'s, in a light and a dark variant chosen from the
editor's background.
"""

from __future__ import annotations

import re

from PyQt6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextDocument

from in_reach.ide.json_highlighter import _is_dark

KEYWORDS = frozenset({
    "if", "then", "altif", "alt", "do", "end", "for", "each", "on", "function", "alias", "declare",
    "and", "or", "not", "inline", "with", "label", "randomly", "network", "priority",
})
ROOTS = frozenset({
    "global", "player", "object", "team", "temporaries", "current_player", "current_object", "current_team", "game",
    "script_option", "script_widget", "script_traits", "script_stat", "no_player", "no_object", "no_team", "none",
})

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(r"(?<![A-Za-z0-9_])-?\d+%?")
_PLACEHOLDER = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")
_DIRECTIVE = re.compile(r"^--\s*@(if|else|end)\b")
_ANNOTATION = re.compile(r"^--\s*@[A-Za-z]")

# (keyword, root, string, number, comment, annotation, directive, placeholder)
_DARK = ("#569cd6", "#4ec9b0", "#ce9178", "#b5cea8", "#6a9955", "#c586c0", "#e06c9f", "#d7ba7d")
_LIGHT = ("#0000cc", "#00688b", "#8b0000", "#065e3e", "#008000", "#af00db", "#b00050", "#795e26")
_NAMES = ("keyword", "root", "string", "number", "comment", "annotation", "directive", "placeholder")


def _comment_start(text: str) -> int:
    """Where a ``--`` comment begins on ``text`` (outside any string), or ``-1``."""
    in_string = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            if char == "\\":
                index += 1
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "-" and text.startswith("--", index):
            return index
        index += 1
    return -1


def _string_spans(text: str) -> list[tuple[int, int]]:
    spans = []
    start = None
    index = 0
    while index < len(text):
        char = text[index]
        if start is not None:
            if char == "\\":
                index += 1
            elif char == '"':
                spans.append((start, index + 1))
                start = None
        elif char == '"':
            start = index
        index += 1
    if start is not None:
        spans.append((start, len(text)))  # an unterminated string still colours to the end of the line
    return spans


class MegaloSyntaxHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument, *, base_color: QColor) -> None:
        super().__init__(document)
        colors = _DARK if _is_dark(base_color) else _LIGHT
        self._formats: dict[str, QTextCharFormat] = {}
        for name, color in zip(_NAMES, colors):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            self._formats[name] = fmt
        self._formats["directive"].setFontWeight(QFont.Weight.Bold)

    def highlightBlock(self, text: str) -> None:  # noqa: N802 -- Qt's own override name
        comment_at = _comment_start(text)
        code = text if comment_at < 0 else text[:comment_at]
        self._highlight_code(code)
        if comment_at >= 0:
            self._highlight_comment(text, comment_at)

    def _highlight_code(self, code: str) -> None:
        strings = _string_spans(code)
        for start, end in strings:
            self.setFormat(start, end - start, self._formats["string"])

        def free(start: int, end: int) -> bool:
            return not any(start < s_end and end > s_start for s_start, s_end in strings)

        for match in _PLACEHOLDER.finditer(code):
            self.setFormat(match.start(), match.end() - match.start(), self._formats["placeholder"])
        for match in _NUMBER.finditer(code):
            if free(match.start(), match.end()):
                self.setFormat(match.start(), match.end() - match.start(), self._formats["number"])
        for match in _WORD.finditer(code):
            if not free(match.start(), match.end()):
                continue
            word = match.group()
            kind = "keyword" if word in KEYWORDS else "root" if word in ROOTS else None
            if kind is not None:
                self.setFormat(match.start(), match.end() - match.start(), self._formats[kind])

    def _highlight_comment(self, text: str, start: int) -> None:
        comment = text[start:]
        if _DIRECTIVE.match(comment):
            kind = "directive"
        elif _ANNOTATION.match(comment):
            kind = "annotation"
        else:
            kind = "comment"
        self.setFormat(start, len(comment), self._formats[kind])
        if kind != "comment":  # an annotation's arguments carry ${placeholders} of their own
            for match in _PLACEHOLDER.finditer(comment):
                self.setFormat(start + match.start(), match.end() - match.start(), self._formats["placeholder"])
