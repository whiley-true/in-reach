"""Which gametype projects are currently open as tabs in the Explorer panel (PROMPT.md: "make it
so that multiple projects can be loaded ... have tabs for the different projects").

Persisted the same way :mod:`in_reach.app.recent`'s own list is -- a single ``;``-separated
``.env`` value -- but in tab order rather than most-recent-first, and with no cap: however many
tabs are open when the window closes is exactly how many should come back on the next launch.
"""

from __future__ import annotations

from pathlib import Path

from in_reach.app import env_file

OPEN_PROJECTS_KEY = "OPEN_PROJECTS"

_SEPARATOR = ";"
_ENV_NAME = ".env"


def _env_path(project_dir: Path) -> Path:
    return project_dir / _ENV_NAME


def list_open(project_dir: Path) -> list[Path]:
    """Returns the projects open at last launch that still exist on disk, in tab order.

    A folder that's since been deleted or moved is silently dropped -- same reasoning as
    :func:`in_reach.app.recent.list_recent`.

    Args:
        project_dir: The project's ``.in-reach`` folder.
    """
    raw = env_file.get_env_values(_env_path(project_dir)).get(OPEN_PROJECTS_KEY, "")
    return [Path(part) for part in raw.split(_SEPARATOR) if part and Path(part).is_dir()]


def set_open(project_dir: Path, folders: list[Path]) -> None:
    """Overwrites the persisted open-tabs list with ``folders``, in order.

    Args:
        project_dir: The project's ``.in-reach`` folder.
        folders: Every currently open project, in tab order.
    """
    env_file.update_env_value(_env_path(project_dir), OPEN_PROJECTS_KEY, _SEPARATOR.join(str(f) for f in folders))
