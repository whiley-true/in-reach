"""Generates the read-only "View Output.txt" file the Dashboard's own button opens (PROMPT.md:
"view output.txt should show output.txt but it should be locked and should always ... have a
comment ... at the top"): a fresh copy of the project's hand-edited ``script/output.txt``, with an
auto-generated banner comment prepended, written under ``build/`` -- landing it under
:func:`~in_reach.app.new_project.is_generated_file`'s own ``BUILD_DIRNAME`` check for free, so the
IDE opens it read-only with the usual padlock tab icon (see
:meth:`~in_reach.ide.tabs.TabPane.open_file`) without needing a special case there.

Regenerated fresh every time the button is clicked (see
:meth:`~in_reach.ide.main_window.MainWindow.view_output_txt`) rather than kept in sync
automatically, so it always reflects the script's current on-disk content -- there's no other
writer of ``script/output.txt`` to hook a sync into anyway (see
:mod:`~in_reach.app.rvt.decompile`'s own module docstring: it's "the one genuinely hand-editable
thing" and deliberately never auto-touched).
"""

from __future__ import annotations

from pathlib import Path

from in_reach.app.new_project import BUILD_DIRNAME, SCRIPT_DIRNAME
from in_reach.app.rvt.decompile import SCRIPT_FILENAME

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
    script_path = folder / SCRIPT_DIRNAME / SCRIPT_FILENAME
    try:
        script_text = script_path.read_text(encoding="utf-8")
    except OSError:
        script_text = ""

    view_path = output_view_path(folder)
    view_path.parent.mkdir(parents=True, exist_ok=True)
    view_path.write_text(_BANNER + script_text, encoding="utf-8")
    return view_path
