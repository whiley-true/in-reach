"""File-name search across a gametype project's own folder.

Backs the Quick Access Bar's search mode (``Ctrl+P``, VSCode's own "Go to File" behavior) --
matching against file *names*/paths, not file contents (see :mod:`in_reach.app.project_search` for
that). Same "no need for fuzzy scoring or a background thread" reasoning as
``project_search.py``'s own module docstring: a gametype project's own file count is small.
"""

from __future__ import annotations

from pathlib import Path


def list_project_files(root: Path) -> list[Path]:
    """Every file under ``root``, sorted by its path relative to ``root``.

    Args:
        root: The gametype project's own folder to walk.

    Returns:
        Absolute paths, in relative-path sort order. Empty if ``root`` doesn't exist.
    """
    if not root.is_dir():
        return []
    return sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: str(p.relative_to(root)).lower())


def filter_files(files: list[Path], query: str, *, root: Path) -> list[Path]:
    """Every entry of ``files`` whose path relative to ``root`` contains ``query`` (case-insensitive
    substring match), in their original order.

    Args:
        files: Candidate file paths, e.g. from :func:`list_project_files`.
        query: The substring to match. An empty query matches everything.
        root: The folder ``files`` are relative to, for display/matching purposes.

    Returns:
        The matching subset of ``files``, order preserved.
    """
    if not query:
        return list(files)
    needle = query.lower()
    return [f for f in files if needle in str(f.relative_to(root)).lower()]
