import logging
import pathlib

from inreach.app import ui
from inreach.app.setup import env_file

logger = logging.getLogger(__name__)

LOCATION_LABELS = {
    "STEAM_INSTALL_LOC": "Steam install",
    "HALO_MCC_INSTALL_LOC": "Halo: MCC install",
    "REACH_MCC_INSTALL_LOC": "Halo Reach (in MCC)",
    "USER_LOCAL_FILES_LOC": "MCC local files folder",
    "HOTRELOAD_DIR_LOC": "Halo Reach hot reload folder",
    "STANDARD_VARIANTS_LOC": "Standard game variants folder",
    "HOPPER_VARIANTS_LOC": "Hopper game variants folder",
}
LOCATION_KEYS = list(LOCATION_LABELS)


def ask_user_for_path(key: str, current: str) -> str | None:
    """Default fallback: confirm with the user, then open a folder picker."""
    label = LOCATION_LABELS.get(key, key)
    ui.warning(f"Could not find {label} at '{current}'.")
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


def verify_locations(env_path: pathlib.Path, prompt_for_missing=ask_user_for_path, delay: float = 0.5) -> None:
    """Check each install location from the env file, updating any that are missing."""
    values = env_file.get_env_values(env_path)

    def _check(key: str) -> str | None:
        raw = values.get(key) or ""
        path = pathlib.Path(raw) if raw else None
        if path is not None and path.exists():
            logger.info("%s found at %s", key, path)
            return str(path)
        logger.warning("%s not found at %s", key, raw)
        return None

    items = [(key, LOCATION_LABELS[key]) for key in LOCATION_KEYS]
    missing_keys = ui.checklist("Checking install locations", items, _check, delay=delay)

    for key in missing_keys:
        chosen = prompt_for_missing(key, values.get(key) or "")
        if chosen:
            env_file.update_env_value(env_path, key, str(chosen))
            values[key] = str(chosen)
            logger.info("%s updated to %s", key, chosen)
