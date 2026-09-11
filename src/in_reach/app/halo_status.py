"""Whether Halo: The Master Chief Collection is currently running -- PROMPT.md: "if the ide
detects (it should check every .5s) that Halo Mcc is running ... then the flame should be filled"
(see :class:`~in_reach.ide.activity_bar.ActivityBar`'s own status indicator, driven from
:meth:`~in_reach.ide.main_window.MainWindow._refresh_halo_status`).

Windows-only, and process-name-based rather than a window-title lookup (an earlier pass used
``FindWindowW`` against the window title "Halo: The Master Chief Collection" -- PROMPT.md:
"MCC-Win64-Shipping seems to be th[e] process/app name" corrected that; a title match is also
fragile in ways a process name isn't, e.g. while the game window is minimized/loading/renamed).
Shells out to the bundled ``tasklist`` rather than reaching for pywin32/psutil, neither of which
this project depends on -- ``CREATE_NO_WINDOW`` is what keeps that from flashing a console window
open over this otherwise console-less GUI app.
"""

from __future__ import annotations

import sys

#: The exact process/executable name Halo: The Master Chief Collection's own game runs as while
#: playing.
MCC_PROCESS_NAME = "MCC-Win64-Shipping.exe"


def is_mcc_running() -> bool:
    """Whether a process named :data:`MCC_PROCESS_NAME` currently exists.

    Returns:
        ``False`` on any non-Windows platform, or if the check itself fails for any reason --
        this is a best-effort live status indicator, not something that should ever crash the IDE.
    """
    if sys.platform != "win32":
        return False
    import subprocess

    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {MCC_PROCESS_NAME}", "/NH"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return MCC_PROCESS_NAME.lower() in result.stdout.lower()
