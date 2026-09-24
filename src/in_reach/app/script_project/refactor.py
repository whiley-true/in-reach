"""Text edits an editor makes to a Megalo script on request -- today, "Convert to Alias": a piece of script (a slot like
``player.number[5]``, a number, a table entry like ``script_traits[1]``) given a name, every copy of it replaced with that
name, and an ``alias`` line added that says what it stands for, below the declarations.

Only whole copies count -- ``5`` is not in ``15``, ``player.number[5]`` is not in ``player.number[50]`` -- and nothing
inside a string or a ``--`` comment is touched; a ``declare`` line keeps its slot (it declares it). Framework-free, like :mod:`.edit`: it takes text and returns text.
"""

from __future__ import annotations

import re

from in_reach.app.rvt.megalo_ast.annotations import _KEYWORDS as _RESERVED

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ALIAS_LINE = re.compile(r"^alias\s+([A-Za-z_][A-Za-z0-9_]*)\s*=", re.MULTILINE)


def _code_spans(line: str) -> list[tuple[int, int]]:
    """The stretches of ``line`` that are code -- not inside a string, not in a ``--`` comment."""
    spans, start, in_string, index = [], 0, False, 0
    while index < len(line):
        char = line[index]
        if in_string:
            if char == "\\":
                index += 1
            elif char == '"':
                in_string = False
                start = index + 1
        elif char == '"':
            spans.append((start, index))
            in_string = True
        elif line.startswith("--", index):
            spans.append((start, index))
            return [s for s in spans if s[1] > s[0]]
        index += 1
    if not in_string:
        spans.append((start, len(line)))
    return [s for s in spans if s[1] > s[0]]


def occurrences(text: str, snippet: str) -> list[tuple[int, int]]:
    """``(start, end)`` offsets in ``text`` of every whole copy of ``snippet`` in code (``snippet`` is taken as written,
    less surrounding blanks; one line only)."""
    snippet = snippet.strip()
    if not snippet or "\n" in snippet:
        return []
    word_start = snippet[0].isalnum() or snippet[0] == "_"
    word_end = snippet[-1].isalnum() or snippet[-1] == "_"
    number = re.fullmatch(r"-?\d+%?", snippet) is not None  # a value -- a slot's [index] is not a copy of it
    found = []
    offset = 0
    for line in text.split("\n"):
        for start, end in _code_spans(line):
            index = line.find(snippet, start, end)
            while index != -1:
                after = index + len(snippet)
                before_ok = not word_start or index == 0 or not (line[index - 1].isalnum() or line[index - 1] in "_.")
                after_ok = not word_end or after >= len(line) or not (line[after].isalnum() or line[after] in "_[")
                in_index = number and index > 0 and line[index - 1] == "["
                if before_ok and after_ok and not in_index:
                    found.append((offset + index, offset + after))
                index = line.find(snippet, after, end)
        offset += len(line) + 1
    return found


def check_alias_name(text: str, name: str) -> str | None:
    """Why ``name`` can't be a new alias in ``text`` -- or ``None`` if it can."""
    if not _NAME.fullmatch(name):
        return f"{name!r} isn't a name (letters, digits and _, not starting with a digit)"
    if name in _RESERVED:
        return f"{name!r} is a word Megalo already uses"
    if name in _ALIAS_LINE.findall(text):
        return f"there is already an alias named {name!r}"
    return None


def _insert_line(lines: list[str], before_line: int) -> int:
    """Where the new ``alias`` line goes: below the declarations block -- after the last top-level ``declare`` (or
    ``alias``, so a run of aliases below the declarations stays together) above the first copy -- or, with neither,
    after the comments and blank lines the file opens with."""
    last = max((i for i in range(before_line) if lines[i].startswith(("declare ", "alias "))), default=None)
    if last is not None:
        return last + 1
    index = 0
    while index < before_line and (not lines[index].strip() or lines[index].lstrip().startswith("--")):
        index += 1
    return index


def convert_to_alias(text: str, snippet: str, name: str) -> str:
    """``text`` with every whole copy of ``snippet`` (see :func:`occurrences`) replaced by ``name``, and
    ``alias name = snippet`` added where aliases go (:func:`_insert_line`).

    Raises:
        ValueError: ``name`` can't be an alias (:func:`check_alias_name`), or ``snippet`` isn't in the code."""
    problem = check_alias_name(text, name)
    if problem:
        raise ValueError(problem)
    snippet = snippet.strip()
    # A declaration names the slot itself (declare global.number[0] ...): its copy stays, and only the uses are named.
    starts = [0] + [i + 1 for i, char in enumerate(text) if char == "\n"]
    spans = [
        (start, end) for start, end in occurrences(text, snippet)
        if not text[max(s for s in starts if s <= start):].lstrip().startswith("declare ")
    ]
    if not spans:
        raise ValueError(f"{snippet!r} isn't used in the script's code (outside its declaration)")
    out, last = [], 0
    for start, end in spans:
        out += [text[last:start], name]
        last = end
    replaced = "".join(out) + text[last:]
    lines = replaced.split("\n")
    first_line = text.count("\n", 0, spans[0][0])
    at = _insert_line(lines, first_line)
    lines.insert(at, f"alias {name} = {snippet}")
    return "\n".join(lines)
