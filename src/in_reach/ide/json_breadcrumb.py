"""Computes the JSON structural path (keys/array-indices) enclosing a cursor offset.

Backs the editor's breadcrumb bar for ``.json`` files (PROMPT.md: "please see vs_sample.png ...
breadcrumb"), e.g. placing the cursor inside ``"description"``'s first array element in
``{"meta": {"description": [{"index": 0, ...}]}}`` reports ``["meta", "description", "[0]"]``.

A small hand-rolled scanner rather than :mod:`json` -- the stdlib parser has no way to ask "what
container encloses offset X" mid-parse, and the text being edited is very often momentarily
invalid JSON anyway (a key typed but not yet given a value, an unclosed string, ...), so this
tolerates that by simply stopping wherever the text stops making sense rather than raising.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _Frame:
    is_array: bool
    array_index: int = 0
    pending_key: str | None = None
    awaiting_value: bool = False
    own_key: str | None = None  # the key/index this container is reached by from its parent


def json_breadcrumb_path(text: str, offset: int) -> list[str]:
    """The breadcrumb trail of keys/array-indices enclosing ``offset`` in ``text``.

    Args:
        text: The full document text (assumed to be JSON-shaped, not necessarily valid).
        offset: A 0-based character offset into ``text`` -- typically the cursor position.

    Returns:
        Each enclosing container's own key (for an object) or ``"[index]"`` (for an array),
        outermost first. Empty at the document root.
    """
    stack: list[_Frame] = []
    in_string = False
    escape = False
    string_start = 0
    last_string: str | None = None

    end = max(0, min(offset, len(text)))
    i = 0
    while i < end:
        ch = text[i]

        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
                last_string = text[string_start:i]
            i += 1
            continue

        if ch == '"':
            in_string = True
            string_start = i + 1
            i += 1
            continue

        if ch in "{[":
            is_array = ch == "["
            own_key = None
            if stack:
                top = stack[-1]
                if top.is_array:
                    own_key = f"[{top.array_index}]"
                elif top.awaiting_value:
                    own_key = top.pending_key
                    top.awaiting_value = False
            stack.append(_Frame(is_array=is_array, own_key=own_key))
            i += 1
            continue

        if ch in "}]":
            if stack:
                stack.pop()
            i += 1
            continue

        if ch == ":":
            if stack and not stack[-1].is_array and last_string is not None:
                stack[-1].pending_key = last_string
                stack[-1].awaiting_value = True
            i += 1
            continue

        if ch == ",":
            if stack:
                top = stack[-1]
                if top.is_array:
                    top.array_index += 1
                else:
                    top.awaiting_value = False
            i += 1
            continue

        i += 1

    return [frame.own_key for frame in stack if frame.own_key is not None]
