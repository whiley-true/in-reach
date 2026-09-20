"""Where things are in a TOML file.

``tomllib`` returns plain dicts with no positions, but a manifest problem is only useful with a line number
("``modules/hill_score/module.toml:7``"). This scans the text for table headers and ``key =`` lines and records
where each one starts, so a validation error about ``("module", "name")`` can be pointed at its line.

It is a locator, not a parser: it trusts ``tomllib`` to have accepted the file, reads one line at a time, and
only records lines that start a key or a table -- so a key that exists only inside an inline table
(``params = { a = 1 }``) is found at the line of ``params``, which is as close as a single line allows.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

Position = tuple[int, int]  # 1-based line, 0-based column

_HEADER = re.compile(r"^\s*(\[\[?)\s*(?P<path>[^\]]+?)\s*\]\]?\s*(#.*)?$")
_KEY = re.compile(r"^(?P<indent>\s*)(?P<key>\"[^\"]*\"|'[^']*'|[A-Za-z0-9_.\-]+)\s*=")


def _split_path(text: str) -> list[str]:
    """``a."b.c".d`` -> ``["a", "b.c", "d"]``."""
    parts: list[str] = []
    for match in re.finditer(r'"([^"]*)"|\'([^\']*)\'|([^.\s]+)', text):
        parts.append(next(group for group in match.groups() if group is not None))
    return parts


def positions(text: str) -> dict[tuple[str | int, ...], Position]:
    """Every table and key in ``text``, keyed by path. An array-of-tables entry is keyed by its index:
    the first ``[[modules]]`` is ``("modules", 0)`` and its ``name`` is ``("modules", 0, "name")``."""
    found: dict[tuple[str | int, ...], Position] = {}
    table: tuple[str | int, ...] = ()
    array_counts: dict[tuple[str | int, ...], int] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        header = _HEADER.match(line)
        if header:
            path = tuple(_split_path(header["path"]))
            if header[1] == "[[":
                index = array_counts.get(path, 0)
                array_counts[path] = index + 1
                table = (*path, index)
            else:
                table = path
            found.setdefault(table, (number, len(line) - len(line.lstrip())))
            continue
        key = _KEY.match(line)
        if key:
            parts = tuple(_split_path(key["key"]))
            found.setdefault((*table, *parts), (number, len(key["indent"])))
    return found


def locate(found: dict[tuple[str | int, ...], Position], path: Sequence[str | int]) -> Position:
    """The position of ``path`` in a :func:`positions` result, or of its longest known prefix; ``(0, 0)`` if
    not even the first part is known (the problem is with the file as a whole)."""
    path = tuple(path)
    for length in range(len(path), 0, -1):
        if path[:length] in found:
            return found[path[:length]]
    return (0, 0)
