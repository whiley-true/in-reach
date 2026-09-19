"""Text search and replace across a gametype project's own folder.

Backs the Search sidebar view (PROMPT.md: "should search in project folder and have find and
replace functionality"; later "we want to add Match Case, Match Whole Word, Use Regular Expression,
then in replace: Preserve case, replace all ... files to include (including an option for Search
only in Open Editors) and files to exclude"). A gametype project's own text files (``settings/``,
``script/``, ``README.md``) are small in both count and size, so nothing here needs to be fast
against a large codebase the way a real IDE's project-wide search would.

:func:`compile_search_pattern`/:func:`preserve_case` live here (rather than in the editor's own
Find/Replace bar, :mod:`in_reach.ide.find_replace`, which re-exports them) so the in-editor bar and
this project-wide search can never disagree about what "matches" or what "preserve case" does.

Every file under the project root is tried as UTF-8 text; anything that fails to decode (a
compiled ``.bin``/``.mvar``, or ``build/``'s own output) is silently skipped, the same convention
:meth:`in_reach.ide.tabs.TabPane.open_file` already uses for the same reason.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class SearchMatch:
    path: Path
    line_number: int  # 1-based
    line_text: str
    column: int  # 0-based offset of the match's start within line_text


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
    if whole_word:
        pattern = rf"\b(?:{pattern})\b"
    try:
        return re.compile(pattern, flags)
    except re.error:
        return None


def preserve_case(original: str, replacement: str) -> str:
    """VSCode's own heuristic: an all-uppercase match gets an all-uppercase replacement, a
    capitalized (title-case first letter) match gets a capitalized replacement, anything else is
    left alone."""
    if not original or not replacement:
        return replacement
    if original.isupper():
        return replacement.upper()
    if original[0].isupper() and original[1:].islower():
        return replacement[0].upper() + replacement[1:]
    return replacement


def split_globs(text: str) -> list[str]:
    """A "files to include"/"files to exclude" box's own text as individual glob patterns --
    comma-separated, blanks dropped, a leading ``./`` and a trailing ``/`` stripped."""
    patterns = []
    for part in text.split(","):
        part = part.strip().replace("\\", "/")
        if part.startswith("./"):
            part = part[2:]
        part = part.rstrip("/")
        if part:
            patterns.append(part)
    return patterns


def _glob_matches(rel_posix: str, pattern: str) -> bool:
    """One glob against a project-relative, ``/``-separated path. A pattern with no ``/`` (``*.json``,
    ``build``) matches any single path segment, so it works at any depth and a folder name covers
    everything beneath it; one with a ``/`` (``src/a/file``) is anchored to the project root and
    also covers everything beneath it if it names a folder. A leading ``**/`` is redundant with the
    first form and is dropped."""
    while pattern.startswith("**/"):
        pattern = pattern[3:]
    parts = rel_posix.split("/")
    if "/" not in pattern:
        return any(fnmatch.fnmatchcase(segment, pattern) for segment in parts)
    return fnmatch.fnmatchcase(rel_posix, pattern) or fnmatch.fnmatchcase(rel_posix, pattern + "/*")


def _passes_filters(
    rel_posix: str, include: list[str], exclude: list[str]
) -> bool:
    if include and not any(_glob_matches(rel_posix, p) for p in include):
        return False
    return not any(_glob_matches(rel_posix, p) for p in exclude)


def _iter_text_files(
    root: Path,
    *,
    include: str = "",
    exclude: str = "",
    only_paths: Iterable[Path] | None = None,
):
    include_globs = split_globs(include)
    exclude_globs = split_globs(exclude)
    allowed = None if only_paths is None else {Path(p).resolve() for p in only_paths}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if allowed is not None and path.resolve() not in allowed:
            continue
        rel_posix = path.relative_to(root).as_posix()
        if not _passes_filters(rel_posix, include_globs, exclude_globs):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        yield path, text


def search_project(
    root: Path,
    query: str,
    *,
    case_sensitive: bool = False,
    whole_word: bool = False,
    regex: bool = False,
    include: str = "",
    exclude: str = "",
    only_paths: Iterable[Path] | None = None,
) -> list[SearchMatch]:
    """Searches every text file under ``root`` for ``query``, one entry per matching *line* (a
    line with more than one match still yields a single entry, at its first match's column --
    good enough for "jump to this line", the only thing a match is used for).

    Args:
        root: The gametype project's own folder to search.
        query: What to search for -- a literal substring, or a regular expression if ``regex``.
            Empty returns no matches.
        case_sensitive: Whether the match is case-sensitive. Defaults to insensitive.
        whole_word: Only match whole words (``\\b`` on both sides).
        regex: Treat ``query`` as a regular expression. An invalid one matches nothing.
        include: Comma-separated globs (see :func:`split_globs`); when non-empty, only files
            matching at least one are searched.
        exclude: Comma-separated globs; files matching any are skipped.
        only_paths: When given, only these files are searched (the "Search only in Open Editors"
            toggle) -- on top of ``include``/``exclude``.

    Returns:
        Matches in file-then-line order. Empty if ``root`` doesn't exist, ``query`` is empty or
        an invalid regex.
    """
    pattern = compile_search_pattern(query, match_case=case_sensitive, whole_word=whole_word, regex=regex)
    if pattern is None or not root.is_dir():
        return []

    results: list[SearchMatch] = []
    for path, text in _iter_text_files(root, include=include, exclude=exclude, only_paths=only_paths):
        for line_number, line in enumerate(text.splitlines(), start=1):
            match = pattern.search(line)
            if match is not None:
                results.append(
                    SearchMatch(path=path, line_number=line_number, line_text=line, column=match.start())
                )
    return results


def replace_in_project(
    root: Path,
    query: str,
    replacement: str,
    *,
    case_sensitive: bool = False,
    whole_word: bool = False,
    regex: bool = False,
    keep_case: bool = False,
    include: str = "",
    exclude: str = "",
    only_paths: Iterable[Path] | None = None,
) -> int:
    """Replaces every occurrence of ``query`` with ``replacement`` across every text file
    :func:`search_project` would search (same options), writing changed files back to disk in place.

    Args:
        root: The gametype project's own folder to search.
        query: What to replace. A no-op (returns ``0``) if empty or an invalid regex.
        replacement: The text to substitute in its place, always inserted literally.
        keep_case: "Preserve case" -- see :func:`preserve_case`.
        (everything else: see :func:`search_project`.)

    Returns:
        How many files were actually changed (a file with no match is left untouched -- its mtime
        doesn't change either).
    """
    pattern = compile_search_pattern(query, match_case=case_sensitive, whole_word=whole_word, regex=regex)
    if pattern is None or not root.is_dir():
        return 0

    def substitute(match: re.Match) -> str:
        return preserve_case(match.group(0), replacement) if keep_case else replacement

    changed = 0
    for path, text in _iter_text_files(root, include=include, exclude=exclude, only_paths=only_paths):
        new_text = pattern.sub(substitute, text)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            changed += 1
    return changed
