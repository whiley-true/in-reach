"""Small, text-level edits to a script project: what a front end does when a user drags something.

Everything a project is stays text -- ``project.toml`` and the ``.mgl`` files -- so a drag-and-drop board, a command or a
person with an editor all change the same files, and nothing here keeps state of its own. Each function makes the
smallest edit that says what was asked and leaves the rest of the file exactly as it was (comments, ordering, line endings):

* :func:`set_block_order` -- ``[blocks].order`` in ``project.toml``;
* :func:`set_module_enabled` -- ``enabled = false`` on a module's ``[[modules]]`` entry (a disabled module isn't built, and
  contributes no blocks, fragments, storage or resources);
* :func:`move_fragment` -- the block named on a fragment's ``-- @fragment BLOCK.name`` line.

Every function raises :class:`EditError` for a request that can't be honoured, and changes nothing when it does.
"""

from __future__ import annotations

import re
from pathlib import Path

import tomlkit

from .model import build_model
from .project import BLOCKS_DIRNAME, PROJECT_FILENAME, SOURCE_SUFFIX, is_linked, load_project, script_dir

_BLOCK_NAME = re.compile(r"[A-Z_][A-Z0-9_]*")
_FRAGMENT_HEADER = re.compile(r"(@fragment[ \t]+)([A-Za-z_][A-Za-z0-9_]*)(\.)")


class EditError(ValueError):
    """A request that can't be done (an unknown module or fragment, a bad block name, ...)."""


def _project_toml(folder: Path) -> tuple[Path, tomlkit.TOMLDocument]:
    if not is_linked(folder):
        raise EditError("this project has no script/project.toml")
    path = script_dir(folder) / PROJECT_FILENAME
    return path, tomlkit.parse(path.read_text(encoding="utf-8"))


def set_block_order(folder: Path, order: list[str]) -> None:
    """Sets ``[blocks].order`` to ``order`` (each entry a block name, no repeats). Blocks left out still build, after the
    listed ones."""
    bad = [name for name in order if not _BLOCK_NAME.fullmatch(name)]
    if bad:
        raise EditError(f"{bad[0]!r} isn't a valid block name (capitals, digits and underscores)")
    if len(set(order)) != len(order):
        raise EditError("a block is listed twice")
    path, doc = _project_toml(folder)
    if "blocks" not in doc:
        doc["blocks"] = tomlkit.table()
    array = tomlkit.array()
    array.multiline(False)
    array.extend(order)
    doc["blocks"]["order"] = array
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def set_module_enabled(folder: Path, name: str, enabled: bool) -> None:
    """Turns module ``name`` on or off. Enabling removes the ``enabled`` key rather than writing ``enabled = true``, so a
    project that never turned anything off has no trace of the feature."""
    path, doc = _project_toml(folder)
    for table in doc.get("modules", []):
        if table.get("name") == name:
            if enabled:
                table.pop("enabled", None)
            else:
                table["enabled"] = False
            path.write_text(tomlkit.dumps(doc), encoding="utf-8")
            return
    raise EditError(f"module {name} isn't listed in project.toml")


def move_fragment(folder: Path, fragment_id: str, block: str) -> Path:
    """Moves fragment ``fragment_id`` (``module.name``, as the Scripts view and the link map show it) to ``block`` by
    rewriting its ``-- @fragment`` line. An ``-- @import`` line in the block it leaves that would now place nothing (it
    named this fragment, or its module and the module has nothing else there) is removed. A module's one loop (no
    ``@fragment`` line) goes where its ``@import`` is, so that line moves instead: out of the block it leaves, onto the end
    of ``block``'s file. Returns the file the fragment now comes from -- its own, or the importing block's."""
    if not _BLOCK_NAME.fullmatch(block):
        raise EditError(f"{block!r} isn't a valid block name (capitals, digits and underscores)")
    if not is_linked(folder):
        raise EditError("this project has no script/project.toml")
    model = build_model(load_project(folder))
    fragment = next((f for f in model.fragments if f.id == fragment_id), None)
    if fragment is None:
        raise EditError(f"there is no fragment {fragment_id}")
    if fragment.block == block:
        return script_dir(folder) / fragment.file
    if fragment.implicit:
        return _move_import(folder, model, fragment, block)
    path = script_dir(folder) / fragment.file
    lines = path.read_bytes().decode("utf-8").splitlines(keepends=True)
    index = fragment.line - 1
    rewritten, count = _FRAGMENT_HEADER.subn(lambda m: f"{m[1]}{block}{m[3]}", lines[index], count=1)
    if count != 1:
        raise EditError(f"{fragment.file}:{fragment.line} isn't a -- @fragment line any more; save the file and try again")
    lines[index] = rewritten
    path.write_bytes("".join(lines).encode("utf-8"))
    _drop_stale_imports(folder, model, fragment)
    return path


def _move_import(folder: Path, model, fragment, block: str) -> Path:
    if block not in model.project.order:
        raise EditError(f"there is no block {block} in project.toml's order")
    code = model.blocks.get(block)
    target = script_dir(folder) / (code.file if code is not None else f"{BLOCKS_DIRNAME}/{block.lower()}{SOURCE_SUFFIX}")
    if fragment.block:
        _drop_stale_imports(folder, model, fragment)
    existing = target.read_bytes().decode("utf-8") if target.is_file() else ""
    newline = "\r\n" if "\r\n" in existing else "\n"
    separator = "" if not existing or existing.endswith(("\n", "\r\n")) else newline
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(f"{existing}{separator}-- @import {fragment.module}{newline}".encode("utf-8"))
    return target


def _drop_stale_imports(folder: Path, model, moved) -> None:
    code = model.blocks.get(moved.block)
    if code is None:
        return
    others = [f for f in model.fragments if f.module == moved.module and f.block == moved.block and f is not moved]
    stale = {
        a.span.start_line - 1
        for a in code.imports
        if a.module == moved.module and (a.fragment == moved.name or (a.fragment is None and not others))
    }
    if not stale:
        return
    block_file = script_dir(folder) / code.file
    lines = block_file.read_bytes().decode("utf-8").splitlines(keepends=True)
    block_file.write_bytes("".join(line for i, line in enumerate(lines) if i not in stale).encode("utf-8"))
