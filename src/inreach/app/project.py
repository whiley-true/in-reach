"""Project-folder bootstrap logic shared by the setup/import/init/delete commands.

The ``.inreach`` project folder holds a scripting project's local config
(``.env``), logs, and other per-project state. It lives at the repo root
(the current working directory the CLI is invoked from) -- not inside the
installed ``inreach`` package. The package only ships a *template* copy of
it (its own ``.inreach/``, alongside this module) that gets copied out to
the repo root on first use. Resolving that template via
:func:`importlib.resources.files` (rather than a path built off
``__file__``) is what keeps this working the same whether inreach is run
from a source checkout or a pip-installed package.
"""

from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path

PROJECT_DIRNAME = ".inreach"
_TEMPLATE_ENV_NAME = "example.env"
_ENV_NAME = ".env"


def get_project_dir(root: Path | None = None) -> Path:
    """Returns the ``.inreach`` project folder path under ``root``.

    Args:
        root: Repo root to look under. Defaults to the current working
            directory.

    Returns:
        ``root / ".inreach"``, whether or not it currently exists.
    """
    return (root or Path.cwd()) / PROJECT_DIRNAME


def project_exists(root: Path | None = None) -> bool:
    """Reports whether a ``.inreach`` project folder already exists.

    Args:
        root: Repo root to check under. Defaults to the current working
            directory.

    Returns:
        ``True`` if ``<root>/.inreach`` exists.
    """
    return get_project_dir(root).exists()


def create_project(root: Path | None = None) -> Path:
    """Creates a new ``.inreach`` project folder from the packaged template.

    Copies the ``.inreach`` template folder shipped inside the installed
    ``inreach`` package to ``<root>/.inreach``, then renames the
    template's ``example.env`` to ``.env`` so it's picked up by
    :mod:`inreach.logging_config` and the rest of the app.

    Args:
        root: Repo root to create the project under. Defaults to the
            current working directory.

    Returns:
        Path to the newly created ``<root>/.inreach`` folder.

    Raises:
        FileExistsError: If ``<root>/.inreach`` already exists.
    """
    dest = get_project_dir(root)
    template = resources.files("inreach") / PROJECT_DIRNAME
    with resources.as_file(template) as template_path:
        shutil.copytree(template_path, dest)

    example_env = dest / _TEMPLATE_ENV_NAME
    if example_env.exists():
        example_env.rename(dest / _ENV_NAME)

    return dest


def delete_project(root: Path | None = None) -> bool:
    """Deletes the ``.inreach`` project folder, if one exists.

    Args:
        root: Repo root to delete the project from. Defaults to the
            current working directory.

    Returns:
        ``True`` if a project folder was found and removed, ``False`` if
        there was nothing to delete.
    """
    project_dir = get_project_dir(root)
    if not project_dir.exists():
        return False
    shutil.rmtree(project_dir)
    return True
