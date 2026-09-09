"""Syntax highlighting for ``.json`` files (PROMPT.md: "please see vs_sample.png ... text
colourings").

A fixed palette rather than a theme-derived one -- same call already made for the JSON file icon's
own hardcoded yellow (see :mod:`in_reach.ide.file_icons`) -- picked from VS Code's own default
JSON color theme (what ``vs_sample.png`` itself shows), just switched between a light-background
and dark-background variant of it since two of this app's three shipped themes (Dark, Whiley) sit
on a dark base. Punctuation (braces/brackets/colons/commas) is deliberately left uncolored, same as
VS Code's own default -- it's structure, not content.
"""

from __future__ import annotations

from PyQt6.QtCore import QRegularExpression
from PyQt6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat, QTextDocument

_STRING_RE = QRegularExpression(r'"(?:[^"\\]|\\.)*"')
_KEY_RE = QRegularExpression(r'"(?:[^"\\]|\\.)*"(?=\s*:)')
_NUMBER_RE = QRegularExpression(r"-?\b\d+(\.\d+)?([eE][+-]?\d+)?\b")
_LITERAL_RE = QRegularExpression(r"\btrue\b|\bfalse\b|\bnull\b")

# (key, string, number, literal) -- VS Code's own default Light+/Dark+ JSON token colors.
_LIGHT_COLORS = ("#0451a5", "#a31515", "#098658", "#0000ff")
_DARK_COLORS = ("#9cdcfe", "#ce9178", "#b5cea8", "#569cd6")


def _is_dark(color: QColor) -> bool:
    # Perceived luminance (ITU-R BT.601) -- the same weighting commonly used for this kind of
    # light/dark contrast decision.
    luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    return luminance < 128


class JsonSyntaxHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument, *, base_color: QColor) -> None:
        super().__init__(document)
        self._formats = self._build_formats(base_color)

    def _build_formats(self, base_color: QColor) -> dict[str, QTextCharFormat]:
        key_hex, string_hex, number_hex, literal_hex = _DARK_COLORS if _is_dark(base_color) else _LIGHT_COLORS
        formats = {}
        for name, hex_color in (("key", key_hex), ("string", string_hex), ("number", number_hex), ("literal", literal_hex)):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(hex_color))
            formats[name] = fmt
        return formats

    def highlightBlock(self, text: str) -> None:  # noqa: N802 -- Qt's own override name
        string_ranges = self._match_ranges(text, _STRING_RE)
        for start, end in string_ranges:
            self.setFormat(start, end - start, self._formats["string"])

        # Numbers/booleans/null only count outside a string -- otherwise "Score 100 points" would
        # get its "100" wrongly recolored as a number, mid-string.
        for start, end in self._match_ranges(text, _NUMBER_RE):
            if not self._overlaps_any(start, end, string_ranges):
                self.setFormat(start, end - start, self._formats["number"])
        for start, end in self._match_ranges(text, _LITERAL_RE):
            if not self._overlaps_any(start, end, string_ranges):
                self.setFormat(start, end - start, self._formats["literal"])

        # Applied last, over exactly the string ranges that are also keys -- so a key's own quotes
        # win over the generic string color already set above.
        for start, end in self._match_ranges(text, _KEY_RE):
            self.setFormat(start, end - start, self._formats["key"])

    @staticmethod
    def _match_ranges(text: str, pattern: QRegularExpression) -> list[tuple[int, int]]:
        ranges = []
        it = pattern.globalMatch(text)
        while it.hasNext():
            match = it.next()
            ranges.append((match.capturedStart(), match.capturedEnd()))
        return ranges

    @staticmethod
    def _overlaps_any(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
        return any(start < r_end and end > r_start for r_start, r_end in ranges)
