"""Tokenizer for Megalo script text (``script/output.mgl``). See ``nodes.py``'s module docstring
for why this grammar (RVT's decompiler output) rather than a binding onto the engine's own AST.

Ported verbatim from a prior prototype (``D:\\whileyRepos\\sort\\mega-ide``, PROMPT.md: "we want a
fromm scratch compiler then") -- see ``nodes.py``'s own module docstring for the full port note.

Comments (``-- text``, to end of line) are real, compileable Megalo syntax (confirmed directly via
``compile_script()``) even though the decompiler itself never emits any -- this grammar covers the
hand-authorable dialect's comments/alias/alt/altif alongside the decompiler's own output. Comments
are tokenized here (not silently skipped as whitespace) so ``parser.py`` can strip them into
``Script.comments`` -- a flat, span-tagged list rather than nodes woven into the statement tree,
since a comment carries no executable meaning and can occur between any two tokens (trailing on a
line of real code, or standalone).
"""
from __future__ import annotations

from dataclasses import dataclass

_PUNCT_2 = {"==", "!=", "<=", ">=", "+=", "-=", "*=", "/=", "%="}
_PUNCT_1 = set(".,()[]:=<>|")


class MegaloLexError(Exception):
    def __init__(self, message: str, line: int, col: int):
        super().__init__(f"{message} (line {line}, col {col})")
        self.line = line
        self.col = col


@dataclass
class Token:
    kind: str  # "int" | "percent" | "string" | "ident" | "punct" | "comment" | "eof"
    text: str  # raw source text (unquoted/unescaped for strings -- see STRING lexing below)
    value: object  # parsed value: int for int/percent, unescaped str for string, else same as text
    start_line: int
    start_col: int
    end_line: int
    end_col: int


def _is_ident_start(c: str) -> bool:
    return c.isalpha() or c == "_"


def _is_ident_cont(c: str) -> bool:
    return c.isalnum() or c == "_"


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(text)
    line = 1
    col = 0

    def advance(count: int = 1) -> None:
        nonlocal i, line, col
        for _ in range(count):
            if text[i] == "\n":
                line += 1
                col = 0
            else:
                col += 1
            i += 1

    while i < n:
        c = text[i]

        if c in " \t\r\n":
            advance()
            continue

        start_line, start_col = line, col

        if text[i:i + 2] == "--":
            j = i + 2
            while j < n and text[j] != "\n":
                j += 1
            comment_text = text[i + 2:j]
            advance(j - i)
            tokens.append(Token("comment", comment_text, comment_text, start_line, start_col, line, col))
            continue

        # Numbers -- a leading "-" fuses into the literal only when immediately followed by a
        # digit (no space): this grammar has no binary subtraction expression operator (only the
        # "-=" assignment token, handled below), so this is unambiguous.
        if c.isdigit() or (c == "-" and i + 1 < n and text[i + 1].isdigit()):
            j = i + 1 if c == "-" else i
            j += 1
            while j < n and text[j].isdigit():
                j += 1
            raw = text[i:j]
            advance(j - i)
            if i < n and text[i] == "%":
                advance()
                tokens.append(Token("percent", raw + "%", int(raw), start_line, start_col, line, col))
            else:
                tokens.append(Token("int", raw, int(raw), start_line, start_col, line, col))
            continue

        if c == '"':
            advance()
            buf = []
            while True:
                if i >= n:
                    raise MegaloLexError("unterminated string literal", start_line, start_col)
                ch = text[i]
                if ch == '"':
                    advance()
                    break
                if ch == "\\" and i + 1 < n:
                    # Pass escapes through verbatim (e.g. the literal two characters "\r" that
                    # Megalo's own text format uses for an in-game newline) -- see nodes.py's
                    # StringLiteral docstring. Only \" needs special handling here so it doesn't
                    # terminate the string; every other backslash sequence is just two literal
                    # characters copied straight through.
                    buf.append(ch)
                    buf.append(text[i + 1])
                    advance(2)
                    continue
                buf.append(ch)
                advance()
            value = "".join(buf)
            tokens.append(Token("string", value, value, start_line, start_col, line, col))
            continue

        if _is_ident_start(c):
            j = i + 1
            while j < n and _is_ident_cont(text[j]):
                j += 1
            raw = text[i:j]
            advance(j - i)
            tokens.append(Token("ident", raw, raw, start_line, start_col, line, col))
            continue

        two = text[i:i + 2]
        if two in _PUNCT_2:
            advance(2)
            tokens.append(Token("punct", two, two, start_line, start_col, line, col))
            continue

        if c in _PUNCT_1:
            advance()
            tokens.append(Token("punct", c, c, start_line, start_col, line, col))
            continue

        raise MegaloLexError(f"unexpected character {c!r}", start_line, start_col)

    tokens.append(Token("eof", "", None, line, col, line, col))
    return tokens
