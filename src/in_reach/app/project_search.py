"""Plain-text search and replace across a gametype project's own folder.

Backs the Search sidebar view (PROMPT.md: "should search in project folder and have find and
replace functionality"). Deliberately simple -- a case-insensitive literal substring match, not a
regex engine -- since a gametype project's own text files (``edit/``'s settings/strings/script,
plus ``README.md``/``user_settings.json``) are small in both count and size; nothing here needs to
be fast against a large codebase the way a real IDE's project-wide search would.

Every file under the project root is tried as UTF-8 text; anything that fails to decode (a
compiled ``.bin``/``.mvar``, or ``build/``'s own output) is silently skipped, the same convention
:meth:`in_reach.ide.tabs.TabPane.open_file` already uses for the same reason.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SearchMatch:
    path: Path
    line_number: int  # 1-based
    line_text: str
    column: int  # 0-based offset of the match's start within line_text


def _iter_text_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        yield path, text


def search_project(root: Path, query: str, *, case_sensitive: bool = False) -> list[SearchMatch]:
    """Searches every text file under ``root`` for ``query``, one entry per matching *line* (a
    line with more than one match still yields a single entry, at its first match's column --
    good enough for "jump to this line", the only thing a match is used for).

    Args:
        root: The gametype project's own folder to search.
        query: The literal substring to search for. Empty returns no matches.
        case_sensitive: Whether the match is case-sensitive. Defaults to insensitive.

    Returns:
        Matches in file-then-line order. Empty if ``root`` doesn't exist or ``query`` is empty.
    """
    if not query or not root.is_dir():
        return []
    needle = query if case_sensitive else query.lower()

    results: list[SearchMatch] = []
    for path, text in _iter_text_files(root):
        for line_number, line in enumerate(text.splitlines(), start=1):
            haystack = line if case_sensitive else line.lower()
            column = haystack.find(needle)
            if column != -1:
                results.append(SearchMatch(path=path, line_number=line_number, line_text=line, column=column))
    return results


def replace_in_project(root: Path, query: str, replacement: str, *, case_sensitive: bool = False) -> int:
    """Replaces every occurrence of ``query`` with ``replacement`` across every text file under
    ``root``, writing changed files back to disk in place.

    Args:
        root: The gametype project's own folder to search.
        query: The literal substring to replace. A no-op (returns ``0``) if empty.
        replacement: The text to substitute in its place.
        case_sensitive: Whether the match is case-sensitive. Defaults to insensitive.

    Returns:
        How many files were actually changed (a file with no match is left untouched -- its mtime
        doesn't change either).
    """
    if not query or not root.is_dir():
        return 0

    if case_sensitive:
        pattern = re.compile(re.escape(query))
    else:
        pattern = re.compile(re.escape(query), re.IGNORECASE)

    changed = 0
    for path, text in _iter_text_files(root):
        new_text = pattern.sub(lambda _m: replacement, text)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            changed += 1
    return changed
