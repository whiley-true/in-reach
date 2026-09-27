"""Starting a script project, and adding to one: the files ``script/project.toml`` and ``modules/<name>/`` need.

:func:`create_project` turns a single-file project (``script/output.mgl``) into a linked one without losing the script.
Each top-level ``for each player``/``object``/``team`` loop becomes a module of its own -- its loop, under a ``-- @loop``
header (a module's one loop needs no ``@fragment`` line) -- and the rest is the one block, ``blocks/main.mgl``, with an
``-- @import <module>`` line where each loop was: the linker builds the module's loop right there, as the same single
trigger, so every trigger keeps its place, and reading the block shows where each module comes in. A loop's ``-- @doc``/``@tags``/``@see`` lines go with
it. Everything a module can't hold stays in the block as written:
events, labelled and ``randomly`` loops, ``if``/``do`` blocks, functions, declarations, and a loop that uses a top-level
``alias`` (a module can't see it). A script that doesn't parse, uses env directives (``-- @if``, ``${NAME}``) or has no
such loop becomes one block, ``blocks/main.mgl``, exactly as written. Nothing inside any piece of code is rewritten.

:func:`create_module` adds ``modules/<name>/`` (a manifest and a starter file) and lists the module in ``project.toml``.

Neither overwrites anything: both refuse rather than replace a file that is already there.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

from in_reach.app import new_project
from in_reach.app.rvt.megalo_ast import MegaloLexError, MegaloParseError, parse

from .project import BLOCKS_DIRNAME, MODULE_FILENAME, MODULES_DIRNAME, PROJECT_FILENAME, SOURCE_SUFFIX, is_linked, script_dir

MAIN_BLOCK_FILENAME = f"main{SOURCE_SUFFIX}"
_MODULE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_MAIN_STARTER = "-- The project's own script. Blocks are files in script/blocks/; modules add fragments to them.\n"
#: The loops a fragment's ``@loop`` can name.
_FRAGMENT_LOOPS = ("player", "object", "team")
#: Env directives: preprocessed per env before linking, so text using them can't be split safely as written.
_ENV_DIRECTIVE = re.compile(r"^\s*--\s*@(?:if|else|end)\b|\$\{", re.MULTILINE)
#: Annotations that document what they sit above -- they move into the fragment header with their loop.
_DOC_ANNOTATION = re.compile(r"^\s*--\s*@(?:doc|tags|see)\b")
_MAX_NAME_WORDS = 4


def _toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass
class _LoopModule:
    """A top-level loop on its way to ``modules/<name>/``."""

    name: str
    selector: str
    header: list[str]  # its -- @doc/@tags/@see lines
    body: list[str]  # dedented; any plain comments that sat above the loop come first


@dataclass
class _Split:
    """A script as its blocks (name -> lines, in order) and the loops that became modules."""

    blocks: dict[str, list[str]] = field(default_factory=dict)
    modules: list[_LoopModule] = field(default_factory=list)


def _module_name(header: list[str], selector: str, number: int, taken: set[str]) -> str:
    """From the loop's first ``@doc`` line (its first few words), else ``<loop>_loop_<n>``; unique within ``taken``."""
    words = []
    for line in header:
        match = re.match(r"\s*--\s*@doc\s+(.*)", line)
        if match:
            words = re.findall(r"[a-z0-9]+", match.group(1).lower())[:_MAX_NAME_WORDS]
            break
    base = "_".join(words) or f"{selector}_loop_{number}"
    if base[0].isdigit():
        base = f"loop_{base}"
    name, suffix = base, 2
    while name in taken:
        name, suffix = f"{base}_{suffix}", suffix + 1
    taken.add(name)
    return name


def _split_into_modules(text: str) -> _Split | None:
    """``text`` cut into blocks and one module per top-level ``for each player/object/team`` (see the module
    docstring), or ``None`` when it should stay a single block."""
    if _ENV_DIRECTIVE.search(text):
        return None
    try:
        script = parse(text)
    except (MegaloLexError, MegaloParseError):
        return None
    lines = text.split("\n")
    alias_names = [stmt.name for stmt in script.body if stmt.kind == "alias"]
    uses_alias = re.compile(r"\b(?:" + "|".join(map(re.escape, alias_names)) + r")\b") if alias_names else None

    def movable(stmt) -> bool:
        if stmt.kind != "for_each" or stmt.selector not in _FRAGMENT_LOOPS or stmt.label is not None or stmt.randomly:
            return False
        first, last = stmt.span.start_line - 1, stmt.span.end_line - 1
        if stmt.span.start_col != 0 or lines[last].strip() != "end" or first == last:
            return False  # sharing a line with other code: not a clean cut
        return uses_alias is None or not uses_alias.search("\n".join(lines[first : last + 1]))

    loops = [stmt for stmt in script.body if movable(stmt)]
    if not loops:
        return None

    split = _Split()
    taken: set[str] = set()
    replaced: dict[int, str] = {}  # first line of what a loop took -> the @import line standing in for it
    moved: set[int] = set()  # 0-based line numbers that leave the block
    for stmt in loops:
        first, last = stmt.span.start_line - 1, stmt.span.end_line - 1
        above = first
        while above > 0 and lines[above - 1].strip().startswith("--") and above - 1 not in moved:
            above -= 1
        comments = lines[above:first]
        header = [line.strip() for line in comments if _DOC_ANNOTATION.match(line)]
        plain = [line.strip() for line in comments if not _DOC_ANNOTATION.match(line)]
        body = textwrap.dedent("\n".join(lines[first + 1 : last])).split("\n")
        name = _module_name(header, stmt.selector, len(split.modules) + 1, taken)
        split.modules.append(_LoopModule(name, stmt.selector, header, plain + body))
        moved.update(range(above, last + 1))
        replaced[above] = f"-- @import {name}"

    block: list[str] = []
    for index, line in enumerate(lines):
        if index in replaced:
            block.append(replaced[index])
        elif index not in moved:
            block.append(line)
    split.blocks["MAIN"] = block
    return split


def _module_source(module: _LoopModule) -> str:
    header = [*module.header, f"-- @loop {module.selector}"]
    body = "\n".join(module.body).rstrip()
    return "\n".join(header) + "\n" + (body + "\n" if body else "")


def _block_source(lines: list[str]) -> str:
    text = "\n".join(lines).strip("\n")
    return text + "\n" if text.strip() else _MAIN_STARTER


def create_project(folder: Path, *, modules: bool = True) -> list[Path]:
    """Creates ``script/project.toml``, its blocks and -- with ``modules`` -- a module per top-level loop for ``folder``
    (see the module docstring), returning the files written.

    Without ``modules`` (or when the script can't be split), ``blocks/main.mgl`` is the existing ``script/output.mgl``
    verbatim (or a one-line starter if there is none, or it is empty). Raises :class:`ValueError` if the project is
    already a script project, has no ``script/`` folder, or already has a file this would write."""
    scripts = script_dir(folder)
    if is_linked(folder):
        raise ValueError("this project already has a script/project.toml")
    if not scripts.is_dir():
        raise ValueError("this project has no script/ folder")

    output = new_project.migrate_script_file(folder)
    try:
        existing = output.read_text(encoding="utf-8").replace("\r\n", "\n")
    except OSError:
        existing = ""
    split = _split_into_modules(existing) if modules else None
    if split is None:
        split = _Split(blocks={"MAIN": existing.split("\n") if existing.strip() else []})

    files: dict[Path, str] = {}
    for block, lines in split.blocks.items():
        files[scripts / BLOCKS_DIRNAME / f"{block.lower()}{SOURCE_SUFFIX}"] = _block_source(lines)
    for module in split.modules:
        directory = scripts / MODULES_DIRNAME / module.name
        files[directory / MODULE_FILENAME] = f'[module]\nname = {_toml_string(module.name)}\nversion = "0.1.0"\n'
        files[directory / f"{module.name}{SOURCE_SUFFIX}"] = _module_source(module)
    if split.blocks.keys() == {"MAIN"} and not split.modules and existing.strip():
        files[scripts / BLOCKS_DIRNAME / MAIN_BLOCK_FILENAME] = existing  # verbatim, trailing lines and all
    for path in files:
        if path.exists():
            raise ValueError(f"{path.relative_to(folder).as_posix()} already exists")

    name = new_project.read_project_title(folder) or folder.name
    order = ", ".join(_toml_string(block) for block in split.blocks)
    manifest = f"[project]\nname = {_toml_string(name)}\n\n[blocks]\norder = [{order}]\n"
    manifest += "".join(f"\n[[modules]]\nname = {_toml_string(module.name)}\n" for module in split.modules)
    manifest_path = scripts / PROJECT_FILENAME

    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    manifest_path.write_text(manifest, encoding="utf-8")
    return [manifest_path, *files]


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
