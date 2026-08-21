import logging
import pathlib

from inreach.app import ui
from inreach.app.setup import env_file

logger = logging.getLogger(__name__)

LOCATION_KEYS = [
    "STEAM_INSTALL_LOC",
    "HALO_MCC_INSTALL_LOC",
    "REACH_MCC_INSTALL_LOC",
    "USER_LOCAL_FILES_LOC",
    "HOTRELOAD_DIR_LOC",
    "STANDARD_VARIANTS_LOC",
    "HOPPER_VARIANTS_LOC",
]


def ask_user_for_path(key: str, current: str) -> str | None:
    """Default fallback: confirm with the user, then open a folder picker."""
    ui.warning(f"Could not find {key} at '{current}'.")
    if not ui.confirm(f"Locate {key} manually?"):
        return None

    import tkinter
    from tkinter import filedialog

    root = tkinter.Tk()
    root.withdraw()
    try:
        selected = filedialog.askdirectory(title=f"Select folder for {key}")
    finally:
        root.destroy()
    return selected or None


def verify_locations(env_path: pathlib.Path, prompt_for_missing=ask_user_for_path) -> None:
    """Check each install location from the env file, updating any that are missing."""
    values = env_file.get_env_values(env_path)

    for key in LOCATION_KEYS:
        raw = values.get(key) or ""
        path = pathlib.Path(raw) if raw else None

        if path is not None and path.exists():
            logger.info("%s found at %s", key, path)
            continue

        logger.warning("%s not found at %s", key, raw)
        chosen = prompt_for_missing(key, raw)
        if chosen:
            env_file.update_env_value(env_path, key, str(chosen))
            values[key] = str(chosen)
            logger.info("%s updated to %s", key, chosen)
