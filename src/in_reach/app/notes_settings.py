"""Notes-file-format preference (PROMPT.md: the dashboard's "Notes" button "launches editor in
notes.txt OR notes.md (can be set in settings or command palette)").

Persisted the same way :mod:`in_reach.app.indent_settings` persists its own preference: one shared
key in the project-root ``.in-reach/.env``, not per individual gametype project -- which file a
project's "Notes" button opens is an IDE-wide editing preference, not something that varies project
to project.
"""

from __future__ import annotations

from pathlib import Path

from in_reach.app import env_file, new_project

NOTES_FORMAT_KEY = "NOTES_FORMAT"

FORMAT_TXT = "txt"
FORMAT_MD = "md"

DEFAULT_NOTES_FORMAT = FORMAT_TXT


def get_notes_format(env_path: Path) -> str:
    """Reads the saved notes-file-format preference.

    Args:
        env_path: Path to the project-root ``.in-reach/.env`` file.

    Returns:
        :data:`FORMAT_TXT` or :data:`FORMAT_MD` -- :data:`DEFAULT_NOTES_FORMAT` if nothing's stored
        yet (or it's unrecognized).
    """
    value = env_file.get_env_values(env_path).get(NOTES_FORMAT_KEY, "")
    return value if value in (FORMAT_TXT, FORMAT_MD) else DEFAULT_NOTES_FORMAT


def set_notes_format(env_path: Path, notes_format: str) -> None:
    """Writes ``notes_format`` back to ``env_path``.

    Args:
        env_path: Path to the project-root ``.in-reach/.env`` file.
        notes_format: :data:`FORMAT_TXT` or :data:`FORMAT_MD`.

    Raises:
        ValueError: ``notes_format`` is neither :data:`FORMAT_TXT` nor :data:`FORMAT_MD`.
    """
    if notes_format not in (FORMAT_TXT, FORMAT_MD):
        raise ValueError(f"Unknown notes format: {notes_format!r}")
    env_file.update_env_value(env_path, NOTES_FORMAT_KEY, notes_format)


def notes_filename(notes_format: str) -> str:
    """The actual filename a project's "Notes" button opens for ``notes_format`` -- ``Notes.txt``
    (see :data:`in_reach.app.new_project.NOTES_FILENAME`, always created for every new project) or
    ``Notes.md``, matched case-for-case with that same constant."""
    return "Notes.md" if notes_format == FORMAT_MD else "Notes.txt"


def ensure_notes_file(folder: Path, notes_format: str) -> Path:
    """The project ``folder``'s own notes file for ``notes_format``, creating it from the same
    template :func:`~in_reach.app.new_project.create_gametype_project` seeds ``Notes.txt`` with if
    it doesn't exist yet -- switching format for the first time (PROMPT.md: "if .md is chosen...")
    shouldn't leave a user clicking "Notes" onto a file that doesn't exist. Never touches an
    already-existing file, notably the ``Notes.txt`` every project already starts with.

    Args:
        folder: The gametype project's own folder.
        notes_format: :data:`FORMAT_TXT` or :data:`FORMAT_MD`.

    Returns:
        The notes file's path.
    """
    path = folder / notes_filename(notes_format)
    if not path.exists():
        path.write_text(new_project.NOTES_TEMPLATE, encoding="utf-8")
    return path
