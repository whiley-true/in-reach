"""Generates the read-only "View Output.txt" file the Dashboard's own button opens (PROMPT.md:
"view output.txt should show output.txt but it should be locked and should always ... have a
comment ... at the top"): a fresh copy of the project's hand-edited ``script/output.txt``, with an
auto-generated banner comment prepended, written under ``build/`` -- landing it under
:func:`~in_reach.app.new_project.is_generated_file`'s own ``BUILD_DIRNAME`` check for free, so the
IDE opens it read-only with the usual padlock tab icon (see
:meth:`~in_reach_ide.tabs.TabPane.open_file`) without needing a special case there.

Regenerated fresh every time the button is clicked (see
:meth:`~in_reach_ide.main_window.MainWindow.view_output_txt`) rather than kept in sync
automatically, so it always reflects the script's current on-disk content -- there's no other
writer of ``script/output.txt`` to hook a sync into anyway (see
:mod:`~in_reach.app.rvt.decompile`'s own module docstring: it's "the one genuinely hand-editable
thing" and deliberately never auto-touched).
"""

from __future__ import annotations

from pathlib import Path

from in_reach.app import script_preprocess
from in_reach.app.new_project import BUILD_DIRNAME, SCRIPT_DIRNAME
from in_reach.app.rvt.decompile import SCRIPT_FILENAME
from in_reach.app.script_project import is_linked, link

#: The generated view's own filename -- deliberately distinct from :data:`SCRIPT_FILENAME`
#: (``script/output.txt``, the hand-edited source this view is generated *from*), so the two never
#: share a name even though they live in different folders.
VIEW_FILENAME = "Compiled.txt"

#: PROMPT.md: "please split this [banner] over two lines" -- each half is its own ``--`` comment
#: line (Megalo's own line-comment token, not ``//``), same as a real multi-line Megalo comment
#: would be, rather than one very long line.
_BANNER = (
    "-- This file is auto-generated and non-editable and represents the active project's present"
    " megalo script as it would appear post-compiling in RVT.\n"
    "-- It's provided for reference and debugging purposes only. Please use the in-reach's script"
    " management utilities if you want to also persist comments, modules, envs etc.\n\n"
)


def output_view_path(folder: Path) -> Path:
    """Where :func:`write_output_view` writes -- ``build/Compiled.txt``."""
    return folder / BUILD_DIRNAME / VIEW_FILENAME


def write_output_view(folder: Path) -> Path:
    """(Re)writes ``folder``'s own output view from its current ``script/output.txt``.

    Args:
        folder: The gametype project folder.

    Returns:
        The written file's path (see :func:`output_view_path`), whether or not
        ``script/output.txt`` existed yet (an empty/missing script still gets a banner-only view
        rather than this raising).
    """
    if is_linked(folder):
        return _write_linked_view(folder)
    script_path = folder / SCRIPT_DIRNAME / SCRIPT_FILENAME
    try:
        script_text = script_path.read_text(encoding="utf-8")
    except OSError:
        script_text = ""

    # What the compiler is actually given: the active profile's constants and blocks applied. If the
    # profile or script can't be preprocessed, show the source as written with the reason on top, rather
    # than raising -- this is the view a user opens to find out what's wrong.
    banner = _BANNER
    try:
        script_text = script_preprocess.preprocess_project(folder, script_text)
    except script_preprocess.PreprocessError as exc:
        where = f"line {exc.line}" if exc.path is None else f"{exc.path.name}, line {exc.line}"
        banner += f"-- NOT PREPROCESSED ({where}): {exc.message}\n\n"

    view_path = output_view_path(folder)
    view_path.parent.mkdir(parents=True, exist_ok=True)
    view_path.write_text(banner + script_text, encoding="utf-8")
    return view_path


def _write_linked_view(folder: Path) -> Path:
    """The view of a linked project (``script/project.toml``): the linker's own assembled script -- what the
    compiler is given -- without writing anything but that one file (no settings, no link map). A project that
    doesn't link shows why, as comments, in place of a script."""
    linked = link(folder, write=False)
    if linked.ok:
        text = linked.compiled
    else:
        reasons = [f"-- NOT LINKED: {d.file}:{d.line}: {d.message} [{d.code}]" for d in linked.errors]
        text = _BANNER + "\n".join(reasons) + "\n"
    view_path = output_view_path(folder)
    view_path.parent.mkdir(parents=True, exist_ok=True)
    view_path.write_text(text, encoding="utf-8")
    return view_path


#: The decompiled view's file, next to ``Compiled.txt``.
DECOMPILED_FILENAME = "Decompiled.txt"

_DECOMPILED_BANNER = (
    "-- This file is auto-generated and non-editable: the script of the built .bin as RVT shows it -- no modules,\n"
    "-- no profile, no annotations. It's provided for reference and debugging. Edit script/ and rebuild.\n\n"
)


def decompiled_view_path(folder: Path) -> Path:
    return folder / BUILD_DIRNAME / DECOMPILED_FILENAME


def write_decompiled_view(folder: Path) -> Path:
    """(Re)writes ``build/Decompiled.txt`` from the project's built ``.bin`` (``build/dist/<name>.bin``): its script decompiled
    the way ReachVariantTool shows it. Needs the native extension.

    Raises:
        OSError: There is no built ``.bin``, or it can't be read.
        ImportError: The native extension isn't available."""
    from in_reach.app import new_project
    from in_reach.app.rvt import decompile, rvt_bridge

    built = new_project.compiled_variant_path(folder)
    variant = rvt_bridge.get_rvt().load(str(built))
    text = decompile.normalize_script_text(variant.decompile_script()) if variant.multiplayer is not None else ""
    path = decompiled_view_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_DECOMPILED_BANNER + text, encoding="utf-8")
    return path
