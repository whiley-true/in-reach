"""Starting a script project, and adding to one: the files ``script/project.toml`` and ``modules/<name>/`` need.

:func:`create_project` turns a single-file project (``script/output.txt``) into a linked one without losing the script:
it becomes the first block, ``blocks/main.mgl``, exactly as written. Nothing is rewritten in it -- a linked project links
hand-written code as it is, so the same script builds the same variant either way (the only difference is that the
build is now assembled by the linker, and ``script/output.txt`` is no longer what is compiled).

:func:`create_module` adds ``modules/<name>/`` (a manifest and a starter file) and lists the module in ``project.toml``.

Neither overwrites anything: both refuse rather than replace a file that is already there.
"""

from __future__ import annotations

import re
from pathlib import Path

from in_reach.app import new_project

from .project import BLOCKS_DIRNAME, MODULE_FILENAME, MODULES_DIRNAME, PROJECT_FILENAME, SOURCE_SUFFIX, is_linked, script_dir

MAIN_BLOCK_FILENAME = f"main{SOURCE_SUFFIX}"
_MODULE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_MAIN_STARTER = "-- The project's own script. Blocks are files in script/blocks/; modules add fragments to them.\n"


def _toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def create_project(folder: Path) -> list[Path]:
    """Creates ``script/project.toml`` and ``script/blocks/main.mgl`` for ``folder``, returning the files written.

    ``main.mgl`` is the existing ``script/output.txt`` verbatim (or a one-line starter if there is none, or it is empty).
    Raises :class:`ValueError` if the project is already a script project or has no ``script/`` folder."""
    scripts = script_dir(folder)
    if is_linked(folder):
        raise ValueError("this project already has a script/project.toml")
    if not scripts.is_dir():
        raise ValueError("this project has no script/ folder")
    block = scripts / BLOCKS_DIRNAME / MAIN_BLOCK_FILENAME
    if block.exists():
        raise ValueError(f"{block.relative_to(folder)} already exists")

    output = scripts / "output.txt"
    try:
        existing = output.read_text(encoding="utf-8")
    except OSError:
        existing = ""
    name = new_project.read_project_title(folder) or folder.name
    manifest = f'[project]\nname = {_toml_string(name)}\n\n[blocks]\norder = ["MAIN"]\n'

    block.parent.mkdir(parents=True, exist_ok=True)
    block.write_text(existing if existing.strip() else _MAIN_STARTER, encoding="utf-8")
    manifest_path = scripts / PROJECT_FILENAME
    manifest_path.write_text(manifest, encoding="utf-8")
    return [manifest_path, block]


BACKUPS_DIRNAME = "backups"


def backup_script(folder: Path, workspace: Path, *, stamp: str | None = None) -> Path:
    """Copies ``folder``'s whole ``script/`` into ``<workspace>/backups/<project id>/script-<stamp>/`` and returns that
    folder. ``workspace`` is the ``.in-reach`` folder beside the project -- outside the project, so the copy is in
    neither the project's own history nor its search. ``stamp`` defaults to the current local time
    (``YYYYmmdd-HHMMSS``); a copy that would land on an existing one gets a ``-2``, ``-3`` ... suffix.

    Raises:
        ValueError: The project has no ``script/`` folder."""
    import shutil
    from datetime import datetime

    scripts = script_dir(folder)
    if not scripts.is_dir():
        raise ValueError("this project has no script/ folder")
    stamp = stamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    base = workspace / BACKUPS_DIRNAME / folder.name
    target = base / f"script-{stamp}"
    suffix = 2
    while target.exists():
        target = base / f"script-{stamp}-{suffix}"
        suffix += 1
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(scripts, target)
    return target


def create_module(folder: Path, name: str) -> list[Path]:
    """Adds module ``name`` to ``folder``'s script project: ``modules/<name>/module.toml`` and ``<name>.mgl``, and a
    ``[[modules]]`` entry in ``project.toml`` (appended, so the rest of that file is untouched). Returns the files
    written. Raises :class:`ValueError` for a name that isn't an identifier, a module that already exists, or a folder
    that isn't a script project."""
    if not _MODULE_NAME.fullmatch(name):
        raise ValueError(f"{name!r} isn't a valid module name (letters, digits and underscores, not starting with a digit)")
    if not is_linked(folder):
        raise ValueError("this project has no script/project.toml -- create a script project first")
    directory = script_dir(folder) / MODULES_DIRNAME / name
    if directory.exists():
        raise ValueError(f"module {name} already exists")

    directory.mkdir(parents=True)
    manifest = directory / MODULE_FILENAME
    manifest.write_text(f'[module]\nname = {_toml_string(name)}\nversion = "0.1.0"\n', encoding="utf-8")
    source = directory / f"{name}{SOURCE_SUFFIX}"
    source.write_text(
        f"-- {name}: what this module does.\n"
        "--\n"
        "-- A module adds code to a block's loop with a fragment, and declares what it stores:\n"
        f"--   example: @fragment MAIN.{name}\n"
        "--   example: @loop player\n"
        "--   example: @number g_my_counter\n",
        encoding="utf-8",
    )

    project_toml = script_dir(folder) / PROJECT_FILENAME
    text = project_toml.read_text(encoding="utf-8")
    separator = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    project_toml.write_text(f"{text}{separator}[[modules]]\nname = {_toml_string(name)}\n", encoding="utf-8")
    return [manifest, source, project_toml]
