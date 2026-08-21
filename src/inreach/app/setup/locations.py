import logging
import pathlib
import subprocess
import time

from inreach.app import ui
from inreach.app.setup import env_file, processes

logger = logging.getLogger(__name__)

STEAM_KEY = "STEAM_INSTALL_LOC"
HALO_MCC_KEY = "HALO_MCC_INSTALL_LOC"
REACH_KEY = "REACH_MCC_INSTALL_LOC"
HOTRELOAD_KEY = "HOTRELOAD_DIR_LOC"
STANDARD_VARIANTS_KEY = "STANDARD_VARIANTS_LOC"
HOPPER_VARIANTS_KEY = "HOPPER_VARIANTS_LOC"

LOCATION_LABELS = {
    STEAM_KEY: "Steam install",
    HALO_MCC_KEY: "Halo: MCC install",
    REACH_KEY: "Halo Reach (in MCC)",
    HOTRELOAD_KEY: "Halo Reach hot reload folder",
    STANDARD_VARIANTS_KEY: "Standard game variants folder",
    HOPPER_VARIANTS_KEY: "Hopper game variants folder",
}
# Fixed order: Steam and Halo: MCC must resolve before Reach's location can
# be (re-)checked, since REACH_MCC_INSTALL_LOC is derived from
# HALO_MCC_INSTALL_LOC via ${} interpolation in the env file.
LOCATION_KEYS = [STEAM_KEY, HALO_MCC_KEY, REACH_KEY, HOTRELOAD_KEY, STANDARD_VARIANTS_KEY, HOPPER_VARIANTS_KEY]

# Steps with no folder picker: missing means the install is invalid and
# setup can't continue.
FATAL_KEYS = {REACH_KEY, HOTRELOAD_KEY, STANDARD_VARIANTS_KEY, HOPPER_VARIANTS_KEY}

_PICKER_HINTS = {
    HALO_MCC_KEY: "This folder should contain mcclauncher.exe.",
}

STEAM_EXE_NAME = "steam.exe"


def ask_user_for_path(key: str, current: str) -> str | None:
    """Default fallback: confirm with the user, then open a folder picker."""
    label = LOCATION_LABELS.get(key, key)
    ui.warning(f"Could not find {label} at '{current}'.")
    hint = _PICKER_HINTS.get(key)
    if hint:
        ui.warning(hint)
    if not ui.confirm(f"Locate {label} manually?"):
        return None

    import tkinter
    from tkinter import filedialog

    root = tkinter.Tk()
    root.withdraw()
    try:
        selected = filedialog.askdirectory(title=f"Select folder for {label}")
    finally:
        root.destroy()
    return selected or None


def verify_steam_install(
    steam_install_dir: pathlib.Path,
    popen=subprocess.Popen,
    is_process_running=processes.is_process_running,
    close_process=processes.close_process,
    sleep=time.sleep,
    wait_seconds: float = 2.0,
) -> bool:
    """Sanity-check a manually located Steam install by launching and
    closing it. Returns whether the process was seen running."""
    steam_exe = pathlib.Path(steam_install_dir) / STEAM_EXE_NAME
    logger.info("Verifying Steam install by launching %s", steam_exe)
    popen([str(steam_exe)])
    sleep(wait_seconds)
    ok = is_process_running(STEAM_EXE_NAME)
    close_process(STEAM_EXE_NAME)
    return ok


def check_location(env_path: pathlib.Path, key: str) -> str | None:
    """Does ``key``'s env value point to a folder that exists?"""
    raw = env_file.get_env_values(env_path).get(key) or ""
    path = pathlib.Path(raw) if raw else None
    if path is not None and path.exists():
        logger.info("%s found at %s", key, path)
        return str(path)
    logger.warning("%s not found at %s", key, raw)
    return None


def resolve_missing_locations(
    env_path: pathlib.Path,
    missing_keys: list[str],
    prompt_for_missing=ask_user_for_path,
    verify_steam=verify_steam_install,
) -> bool:
    """Resolve the non-fatal location keys in ``missing_keys`` via folder
    picker, ignoring anything in ``missing_keys`` that isn't one of
    :data:`LOCATION_KEYS` (a caller may pass a combined missing list that
    also covers unrelated checklist items, e.g. the Steam account).

    Returns whether anything was actually changed, so a caller showing
    these as part of a checklist knows whether it needs to redraw.
    """
    changed = False
    for key in missing_keys:
        if key not in LOCATION_KEYS or key in FATAL_KEYS:
            continue

        values = env_file.get_env_values(env_path)
        chosen = prompt_for_missing(key, values.get(key) or "")
        if not chosen:
            continue

        env_file.update_env_value(env_path, key, str(chosen))
        logger.info("%s updated to %s", key, chosen)
        changed = True

        if key == STEAM_KEY and not verify_steam(chosen):
            ui.warning("Could not verify the Steam install by launching it.")

    return changed
