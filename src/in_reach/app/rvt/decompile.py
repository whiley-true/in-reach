"""Decompiles a source ``.bin`` straight into a new project's own ``edit/`` layout.

The ``in-reach-v1``/``in-reach-v2`` prototypes did this as part of their own ``init`` command --
see :mod:`in_reach.app.new_project`'s module docstring for why it was left out of this repo's
first pass (the native ``_reachvarianttool`` extension wasn't ported yet). Now that it is (see
:mod:`in_reach.app.rvt.rvt_bridge`), :func:`decompile_into_project` is the thin wrapper that
replaces v1's own ``project_io.write_project_files`` for this repo's ``edit/``/``build/`` folder
naming (v1 used ``cfg/``/``dist/``) -- settings/strings extracted as validated JSON via
:mod:`in_reach.app.rvt.extraction`/``settings_io``/``strings_io``, and the Megalo script itself via
the native module's own ``decompile_script()`` (no AST reimplementation needed).
"""
from __future__ import annotations

from pathlib import Path

from in_reach.app import new_project

from . import settings_io, strings_io
from .extraction import extract_game_settings
from .models.script_settings import ScriptSettings
from .rvt_bridge import get_rvt

SETTINGS_FILENAME = "settings.json"
SCRIPT_SETTINGS_FILENAME = "script_settings.json"
STRINGS_FILENAME = "strings.json"
SCRIPT_FILENAME = "script.txt"


def decompile_into_project(bin_path: Path, folder: Path) -> None:
    """Loads ``bin_path`` through the bundled ReachVariantTool extension and writes what it decodes
    into ``folder``'s ``edit/settings/`` (settings/script settings/strings, as JSON) and
    ``edit/rvt/`` (the decompiled Megalo script, as plain text).

    Args:
        bin_path: The source ``.bin`` to decompile -- normally
            :func:`~in_reach.app.new_project.source_variant_path`'s result for ``folder``.
        folder: The gametype project folder to write into, as returned by
            :func:`~in_reach.app.new_project.create_gametype_project`.

    Raises:
        Whatever the native extension or pydantic validation raises for a ``.bin`` it can't load or
        make sense of -- callers decide whether that should block project creation or just surface
        as a warning (see that function's own handling).
    """
    rvt = get_rvt()
    variant = rvt.load(str(bin_path))

    settings_dir = folder / new_project.EDIT_DIRNAME / new_project.EDIT_SETTINGS_SUBDIR
    rvt_dir = folder / new_project.EDIT_DIRNAME / new_project.EDIT_RVT_SUBDIR
    settings_dir.mkdir(parents=True, exist_ok=True)
    rvt_dir.mkdir(parents=True, exist_ok=True)

    game_settings = extract_game_settings(variant, bin_path)
    script_settings = (
        game_settings.multiplayer.script_settings
        if game_settings.multiplayer is not None
        else ScriptSettings()
    )
    strings = strings_io.extract_strings(variant.multiplayer)

    settings_io.dump_game_settings(game_settings, settings_dir / SETTINGS_FILENAME)
    settings_io.dump_script_settings(script_settings, settings_dir / SCRIPT_SETTINGS_FILENAME)
    strings_io.write_strings_json(strings, settings_dir / STRINGS_FILENAME)
    (rvt_dir / SCRIPT_FILENAME).write_text(variant.decompile_script(), encoding="utf-8")
