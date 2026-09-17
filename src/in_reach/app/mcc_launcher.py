"""Launches Halo: The Master Chief Collection via Steam (PROMPT.md: top bar "Launch" menu, "Launch
Halo MCC (greyed unless verified)").

Ported, in reduced form, from ``in-reach-v2``'s own ``app/setup/steam.py::launch_mcc_eac_disabled``
-- ``option2`` is Steam's own "Anti-Cheat Disabled" launch option (of Ask/Anti-Cheat/Anti-Cheat
Disabled), the one that also allows mods/custom content to load, which is what actually lets an
in-reach-authored gametype be selected in-game at all. Reduced to just the launch itself: v2's own
version also verified the launch actually succeeded and closed MCC again afterward, for its own
automated setup-checklist flow (not needed for a plain "Launch Halo MCC" menu action here).
"""

from __future__ import annotations

import os

#: Halo: The Master Chief Collection's own Steam application id.
MCC_STEAM_APP_ID = "976730"


def launch_mcc(open_uri=None) -> None:
    """Launches Halo: MCC via Steam's own anti-cheat-disabled launch option.

    Args:
        open_uri: Injectable URI opener, for testing. Defaults to ``os.startfile`` -- resolved
            inside the function body, not as the parameter's own default value, since
            ``os.startfile`` doesn't exist as an attribute at all on a non-Windows platform (this
            app is Windows-only in practice, but its own tests still import this module on any
            platform).
    """
    if open_uri is None:
        open_uri = os.startfile
    open_uri(f"steam://launch/{MCC_STEAM_APP_ID}/option2")
