"""Resolves and launches in-reach's own bundled copy of ReachVariantTool (RVT).

Ported from v2's own approach (see that prototype's ``app/rvt_tool/launcher.py``/``exe.py``): a
pre-built RVT (GPLv3, github.com/DavidJCobb/ReachVariantEditor) ships inside this package itself,
at ``in_reach/app/rvt_tool/bin/`` -- the executable, its Qt5 runtime DLLs/plugins, and the
``LICENSES/`` folder GPLv3 redistribution requires alongside it (all carried over verbatim from
v2's own bundle; only its offline ``help/`` documentation was dropped here, to keep this package's
own size reasonable -- RVT's own UI still works identically without it). Resolved via
``importlib.resources`` rather than a path built off ``__file__``, so this keeps working whether
in-reach is run from a source checkout or a pip-installed package -- same pattern as
:mod:`in_reach.app.project`'s own template lookup.
"""

from __future__ import annotations

import subprocess
from importlib import resources
from pathlib import Path

_RVT_TOOL_PACKAGE = "in_reach.app.rvt_tool"
_BIN_DIRNAME = "bin"
_EXE_NAME = "ReachVariantTool.exe"


def resolve_rvt_exe() -> Path:
    """Resolves the bundled ``ReachVariantTool.exe``.

    Returns:
        The executable's path. ``importlib.resources.as_file()`` extracts to a temporary location
        only for an exotic zipped install (e.g. a zipapp) -- for the normal unzipped install this
        62MB-plus bundle will actually ship as, the returned path is the real, permanent one on
        disk, so it's still valid after this function (and the ``with`` block resolving it) returns.
    """
    resource = resources.files(_RVT_TOOL_PACKAGE) / _BIN_DIRNAME / _EXE_NAME
    with resources.as_file(resource) as exe_path:
        return exe_path


def launch_rvt(target: Path | None = None, *, exe_path: Path | None = None, popen=subprocess.Popen):
    """Launches RVT, optionally passing ``target`` (a ``.bin``) as its one positional argument, and
    returns immediately -- RVT is a separate GUI application, not something this process waits on.

    Args:
        target: A game variant to open it against, if any.
        exe_path: Injectable override of :func:`resolve_rvt_exe`'s own result, for testing.
        popen: Injectable :class:`subprocess.Popen`-alike, for testing.

    Returns:
        Whatever ``popen`` returns -- a real :class:`subprocess.Popen` handle to the launched
        process by default, so a caller (see :meth:`~in_reach.ide.main_window.MainWindow.
        launch_rvt`) can later check whether it's still running and terminate it (PROMPT.md: "if
        project is closed in ide, if Reach Variant tool is open for that project it should be
        closed").
    """
    resolved = exe_path if exe_path is not None else resolve_rvt_exe()
    args = [str(resolved)]
    if target is not None:
        args.append(str(target))
    return popen(args)
