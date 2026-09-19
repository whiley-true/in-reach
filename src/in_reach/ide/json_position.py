"""Maps a pydantic validation error's ``loc`` path (e.g. ``("meta", "category")``) back to the
character span in the *original* JSON text that produced it -- what
:mod:`in_reach.ide.editor`'s live schema-check needs to draw a VS Code-style wavy underline under
the actual offending value while the user types (PROMPT.md: "we want it like in vscode, so
highlighting and error message if schema is incorrect").

A small hand-rolled tokenizer + recursive-descent walk, not a general JSON parser: it's only ever
called on text :func:`json.loads` has *already* parsed successfully (see
:func:`in_reach.ide.schema_check.find_errors`), so it doesn't need to validate syntax itself, just
track offsets while walking a document already known to be well-formed.
"""

from __future__ import annotations

import json
import re
from typing import NamedTuple

_TOKEN_RE = re.compile(
    r'(?P<string>"(?:[^"\\]|\\.)*")'
    r"|(?P<number>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
    r"|(?P<literal>true|false|null)"
    r"|(?P<punct>[{}\[\]:,])"
    r"|(?P<ws>\s+)"
)


class _Token(NamedTuple):
    text: str
    start: int
    end: int


def _tokenize(text: str) -> list[_Token]:
    tokens = []
    for match in _TOKEN_RE.finditer(text):
        if match.lastgroup == "ws":
            continue
        tokens.append(_Token(match.group(), match.start(), match.end()))
    return tokens


def _value_span(
    tokens: list[_Token], i: int, path: tuple
) -> tuple[tuple[int, int], tuple[int, int] | None, int]:
    """Parses the value starting at ``tokens[i]``, returning ``(whole_span, found_span, next_i)``
    -- ``whole_span`` covers the entire value at this position, ``found_span`` is set once ``path``
    is fully consumed (``None`` while still descending, or if ``path`` names a key/index that isn't
    actually present), and ``next_i`` is the token index just past this value."""
    tok = tokens[i]
    if tok.text == "{":
        start = tok.start
        i += 1
        found: tuple[int, int] | None = None
        if tokens[i].text == "}":
            end = tokens[i].end
            return (start, end), (None if path else (start, end)), i + 1
        while True:
            key = json.loads(tokens[i].text)
            i += 2  # the key string, then ':'
            sub_path = path[1:] if path and path[0] == key else ()
            _, sub_found, i = _value_span(tokens, i, sub_path)
            if path and path[0] == key and sub_found is not None:
                found = sub_found
            if tokens[i].text == ",":
                i += 1
                continue
            end = tokens[i].end
            i += 1
            break
        return (start, end), (found if path else (start, end)), i
    if tok.text == "[":
        start = tok.start
        i += 1
        found = None
        if tokens[i].text == "]":
            end = tokens[i].end
            return (start, end), (None if path else (start, end)), i + 1
        index = 0
        while True:
            sub_path = path[1:] if path and path[0] == index else ()
            _, sub_found, i = _value_span(tokens, i, sub_path)
            if path and path[0] == index and sub_found is not None:
                found = sub_found
            index += 1
            if tokens[i].text == ",":
                i += 1
                continue
            end = tokens[i].end
            i += 1
            break
        return (start, end), (found if path else (start, end)), i
    # Scalar: string, number, or true/false/null -- always one token.
    span = (tok.start, tok.end)
    return span, (span if not path else None), i + 1


def find_value_span(text: str, loc: tuple) -> tuple[int, int] | None:
    """The ``(start, end)`` character offsets in ``text`` of the value at pydantic path ``loc``,
    or ``None`` if ``text`` isn't parseable or ``loc`` doesn't resolve to anything (a field that's
    simply absent, e.g. a "field required" error -- there's no value in the text to underline)."""
    tokens = _tokenize(text)
    if not tokens:
        return None
    try:
        _, found, _ = _value_span(tokens, 0, tuple(loc))
    except (IndexError, ValueError):
        return None
    return found


def _collect_value_spans(
    tokens: list[_Token], i: int, path: tuple, targets: set[tuple], found: dict[tuple, tuple[int, int]]
) -> int:
    """Single-pass sibling of :func:`_value_span`: parses the value starting at ``tokens[i]``,
    recording ``found[path] = span`` for every ``path`` (built up incrementally while descending)
    that's a member of ``targets`` -- one full walk of the document locates *every* requested loc at
    once, rather than one full walk per loc (see :func:`find_value_spans`'s own docstring for why
    that distinction matters). Returns the token index just past this value."""
    tok = tokens[i]
    if tok.text == "{":
        start = tok.start
        i += 1
        if tokens[i].text == "}":
            end = tokens[i].end
            if path in targets:
                found[path] = (start, end)
            return i + 1
        while True:
            key = json.loads(tokens[i].text)
            i += 2  # the key string, then ':'
            i = _collect_value_spans(tokens, i, (*path, key), targets, found)
            if tokens[i].text == ",":
                i += 1
                continue
            end = tokens[i].end
            i += 1
            break
        if path in targets:
            found[path] = (start, end)
        return i
    if tok.text == "[":
        start = tok.start
        i += 1
        if tokens[i].text == "]":
            end = tokens[i].end
            if path in targets:
                found[path] = (start, end)
            return i + 1
        index = 0
        while True:
            i = _collect_value_spans(tokens, i, (*path, index), targets, found)
            index += 1
            if tokens[i].text == ",":
                i += 1
                continue
            end = tokens[i].end
            i += 1
            break
        if path in targets:
            found[path] = (start, end)
        return i
    # Scalar: string, number, or true/false/null -- always one token.
    if path in targets:
        found[path] = (tok.start, tok.end)
    return i + 1


def find_value_spans(text: str, locs: list[tuple]) -> list[tuple[int, int] | None]:
    """Same result as calling :func:`find_value_span` once per entry of ``locs``, in one single walk
    of ``text`` regardless of how many locs are asked for -- editor.py's own protected-field spans
    (dozens of individual fields on a large settings/script_settings.json, recomputed on every
    keystroke -- see its own ``_protected_spans_cache`` docstring) confirmed a real, severe
    performance regression calling :func:`find_value_span` in a loop instead: each call re-walks the
    *entire* parsed tree from the root looking for just its own one loc, making the total cost
    ``O(fields x document size)`` instead of this function's ``O(document size)``."""
    tokens = _tokenize(text)
    if not tokens:
        return [None for _ in locs]
    targets = {tuple(loc) for loc in locs}
    found: dict[tuple, tuple[int, int]] = {}
    try:
        _collect_value_spans(tokens, 0, (), targets, found)
    except (IndexError, ValueError):
        pass
    return [found.get(tuple(loc)) for loc in locs]
