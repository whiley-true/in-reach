"""Project-folder bootstrap logic for ``in-reach run``.

The ``.in-reach`` project folder holds a project's local config (``.env``) and logs. It lives at
the repo root (the current working directory ``in-reach`` is invoked from) -- not inside the
installed ``in_reach`` package. The package only ships a *template* copy of it (its own
``.in-reach/``, alongside this module) that gets copied out to the repo root on first use.
Resolving that template via :func:`importlib.resources.files` (rather than a path built off
``__file__``) is what keeps this working the same whether ``in-reach`` is run from a source
checkout or a pip-installed package.
"""

from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path

PROJECT_DIRNAME = ".in-reach"
_TEMPLATE_ENV_NAME = "example.env"
_ENV_NAME = ".env"
_GITIGNORE_NAME = ".gitignore"
_GITIGNORE_CONTENT = "*\n"


def get_project_dir(root: Path | None = None) -> Path:
    """Returns the ``.in-reach`` project folder path under ``root``.

    Args:
        root: Repo root to look under. Defaults to the current working directory.

    Returns:
        ``root / ".in-reach"``, whether or not it currently exists.
    """
    return (root or Path.cwd()) / PROJECT_DIRNAME


def project_exists(root: Path | None = None) -> bool:
    """Reports whether a ``.in-reach`` project folder already exists.

    Args:
        root: Repo root to check under. Defaults to the current working directory.

    Returns:
        ``True`` if ``<root>/.in-reach`` exists.
    """
    return get_project_dir(root).exists()


def create_project(root: Path | None = None) -> Path:
    """Creates a new ``.in-reach`` project folder from the packaged template.

    Copies the ``.in-reach`` template folder shipped inside the installed ``in_reach`` package to
    ``<root>/.in-reach``, then renames the template's ``example.env`` to ``.env``.

    Args:
        root: Repo root to create the project under. Defaults to the current working directory.

    Returns:
        Path to the newly created ``<root>/.in-reach`` folder.

    Raises:
        FileExistsError: If ``<root>/.in-reach`` already exists.
    """
    dest = get_project_dir(root)
    template = resources.files("in_reach") / PROJECT_DIRNAME
    with resources.as_file(template) as template_path:
        shutil.copytree(template_path, dest)

    example_env = dest / _TEMPLATE_ENV_NAME
    if example_env.exists():
        example_env.rename(dest / _ENV_NAME)

    return dest


def ensure_gitignore(project_dir: Path) -> None:
    """Writes ``<project_dir>/.gitignore`` (a bare ``*``) if it doesn't already exist.

    Generated at runtime rather than shipped as a static file in the packaged template: a literal
    ``.gitignore`` containing ``*`` inside the *template* folder would ignore itself (and
    everything else in the template) from this repo's own git tracking, since gitignore rules
    apply to the directory they live in regardless of whether that directory is itself a packaged
    template or a real project. Called on every ``in-reach run``, so an existing ``.in-reach``
    folder from before this existed self-heals instead of staying untracked-by-default forever.

    Args:
        project_dir: The project's ``.in-reach`` folder, as returned by :func:`get_project_dir`.
    """
    path = project_dir / _GITIGNORE_NAME
    if not path.exists():
        path.write_text(_GITIGNORE_CONTENT, encoding="utf-8")
