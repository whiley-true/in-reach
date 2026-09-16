"""Blocks ``WM_GETOBJECT`` before Qt's own Windows accessibility bridge ever answers it.

Context (see ``editor.py``'s own module docstring for the related, now-fixed viewport-margins
crash -- this is a *different* one that survived that rewrite): a WinDbg/minidump-analyzed native
access violation, reproducible only via a genuine, interactively-driven resize (never a
programmatic one), traced into a small ``Qt6Core.dll`` helper that reads a cached pointer off an
object's private data and vtable-dispatches through it -- with that pointer holding ``-1`` rather
than a valid pointer or ``NULL``. Both crash dumps' own stacks show that call immediately preceded
by ``UIAutomationCore.DLL``/``oleacc.dll`` frames. Windows sends every top-level window a
``WM_GETOBJECT`` message on essentially any resize/move, to refresh UI Automation's view of it,
regardless of whether an actual screen reader or other assistive-technology client is attached --
and ``QT_ACCESSIBILITY=0`` (Qt's own opt-out env var) does not stop Qt's Windows platform plugin
from answering that message, confirmed by testing (the crash reproduced identically either way).
Swallowing the message here, before Qt's platform plugin ever sees it, means Qt never builds or
looks up an accessible interface for anything in this app at all -- sidestepping whatever the
underlying bug is rather than needing to find and fix it inside Qt itself.
"""

from __future__ import annotations

import sys
from ctypes import wintypes

from PyQt6.QtCore import QAbstractNativeEventFilter

#: https://learn.microsoft.com/en-us/windows/win32/winauto/wm-getobject -- sent to query a window's
#: accessible object, most commonly (per Microsoft's own docs) by UI Automation itself refreshing
#: state, not only by an assistive-technology client actively in use.
WM_GETOBJECT = 0x003D


class BlockAccessibilityQueries(QAbstractNativeEventFilter):
    """Install on the ``QApplication`` via ``installNativeEventFilter`` -- see module docstring."""

    def nativeEventFilter(self, eventType, message):  # noqa: ANN001, N802 -- Qt's own signature
        if sys.platform == "win32" and eventType == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_GETOBJECT:
                return True, 0
        return False, 0
