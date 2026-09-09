"""Minimal parser for Valve's KeyValues ("VDF") text format.

Steam's ``localconfig.vdf`` files use this format: nested ``"key" { ... }`` blocks and
``"key" "value"`` pairs. :mod:`in_reach.app.system_verify` only ever needs to *read* one (to pull
the display name for a detected Steam account), never write one back, so this is a small
recursive-descent parser rather than a full-fidelity implementation -- repeated sibling keys simply
overwrite in the resulting dict.
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')


def _unescape(text: str) -> str:
    return text.replace('\\"', '"').replace("\\\\", "\\")


def loads(text: str) -> dict:
    """Parses VDF text into a nested dict.

    Args:
        text: Raw VDF file contents.

    Returns:
        A nested dict mirroring the VDF's ``"key" { ... }``/``"key" "value"`` structure.
    """
    tokens = [(m.group(1), m.group(2)) for m in _TOKEN_RE.finditer(text)]
    pos = 0

    def parse_block() -> dict:
        nonlocal pos
        result: dict = {}
        while pos < len(tokens):
            string_tok, brace_tok = tokens[pos]
            if brace_tok == "}":
                pos += 1
                return result
            key = _unescape(string_tok)
            pos += 1
            if pos >= len(tokens):
                break
            next_string, next_brace = tokens[pos]
            if next_brace == "{":
                pos += 1
                result[key] = parse_block()
            else:
                result[key] = _unescape(next_string)
                pos += 1
        return result

    return parse_block()
