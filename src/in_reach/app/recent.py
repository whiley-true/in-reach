"""The Welcome tab's "Recent" list, stored as a single ``.env`` key.

A ``;``-separated list of project folder paths, most-recent first, kept in the project's own
``.env`` alongside everything else in ``.in-reach`` rather than in a separate state file -- ``;``
being a character Windows already forbids in a path, so it can't collide with an entry.
"""

from __future__ import annotations

from pathlib import Path

from in_reach.app import env_file

RECENT_KEY = "RECENT_PROJECTS"
MAX_RECENT = 8

_SEPARATOR = ";"
_ENV_NAME = ".env"


def _env_path(project_dir: Path) -> Path:
    return project_dir / _ENV_NAME


def list_recent(project_dir: Path) -> list[Path]:
    """Returns the recently opened project folders that still exist on disk, most-recent first.

    Entries that have since been deleted or moved are filtered out on read rather than rewritten
    away -- a folder on a drive that simply isn't mounted right now shouldn't be forgotten forever.

    Args:
        project_dir: The project's ``.in-reach`` folder.
    """
    raw = env_file.get_env_values(_env_path(project_dir)).get(RECENT_KEY, "")
    return [Path(part) for part in raw.split(_SEPARATOR) if part and Path(part).is_dir()]


def add_recent(project_dir: Path, path: Path) -> None:
    """Moves ``path`` to the front of the recent list, capped at :data:`MAX_RECENT` entries.

    Args:
        project_dir: The project's ``.in-reach`` folder.
        path: The project folder that was just created or opened.
    """
    raw = env_file.get_env_values(_env_path(project_dir)).get(RECENT_KEY, "")
    existing = [part for part in raw.split(_SEPARATOR) if part and part != str(path)]
    entries = [str(path), *existing][:MAX_RECENT]
    env_file.update_env_value(_env_path(project_dir), RECENT_KEY, _SEPARATOR.join(entries))
