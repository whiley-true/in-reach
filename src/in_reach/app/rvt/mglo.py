"""Writes a compiled game variant out as RVT's own bare "Megalo script only" save format
(``.mglo``) instead of a full ``.bin`` -- part of "Export RVT File" (PROMPT.md: "export should
launch standard rvt save as dialog ... allowing user to save as .bin or .mglo").

There's no pybind11 binding for that save flag (``GameVariantSaveProcess::flag::save_bare_mglo`` in
RVT's own C++ source), and this package's own bindings can't be extended without a full native
rebuild. Rather than that, this shells out to the bundled ``ReachVariantTool.exe``'s own headless
CLI mode instead -- ported from v2's own ``app/mglo.py`` (same underlying mechanism, generalized to
write to a caller-chosen destination path rather than always ``<bin_path>.mglo``, since here the
destination comes from the user's own Save As dialog rather than always sitting beside the source
``.bin``):

    ReachVariantTool.exe --headless <in-variant> --recompile <in-source> --dst <out-variant>

``--dst``'s own file extension decides the save format inside RVT's own save routine -- ``.mglo``
triggers the bare-Megalo-only write, anything else a normal full ``.bin``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from in_reach.app.rvt_launcher import resolve_rvt_exe


def write_mglo(bin_path: Path, script_path: Path, dest_path: Path, *, run=subprocess.run) -> bool:
    """Recompiles ``script_path`` against ``bin_path`` through the packaged RVT's headless CLI
    (see this module's own docstring) and saves the result to ``dest_path``.

    Args:
        bin_path: A fully-settings-applied ``.bin`` to recompile ``script_path`` against (normally
            :func:`~in_reach.app.new_project.compiled_variant_path`'s own result, freshly built).
        script_path: The Megalo script source that was just compiled into ``bin_path`` (normally
            ``script/output.txt``).
        dest_path: Where to save the result -- a ``.mglo`` extension writes RVT's bare/script-only
            format; anything else writes a normal full ``.bin``.
        run: Injectable :func:`subprocess.run`-alike, for testing.

    Returns:
        Whether ``dest_path`` was written successfully. Never raises for a normal failure (RVT
        missing/erroring, the script failing to recompile) -- returns ``False`` instead, so the
        caller can surface its own user-facing error message.
    """
    rvt_exe = resolve_rvt_exe()
    try:
        result = run(
            [str(rvt_exe), "--headless", str(bin_path), "--recompile", str(script_path), "--dst", str(dest_path)],
            capture_output=True,
            text=True,
            cwd=str(rvt_exe.parent),
        )
    except OSError:
        return False
    return result.returncode == 0 and dest_path.is_file()
