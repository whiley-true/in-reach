import logging
import os
import pathlib

from inreach.app import ui
from inreach.app.setup import env_file, vdf

logger = logging.getLogger(__name__)

MCC_APPID = "976730"
USER_STEAM_LOC_INT_KEY = "USER_STEAM_LOC_INT"

USERDATA_DIR_NAME = "userdata"
LOCALCONFIG_REL_PATH = pathlib.Path("config") / "localconfig.vdf"


def userdata_dir(steam_install_loc: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(steam_install_loc) / USERDATA_DIR_NAME


def list_steam_user_ids(userdata_dir: pathlib.Path) -> list[str]:
    """Return the Steam account ids under ``userdata`` that have a config."""
    if not userdata_dir.exists():
        return []

    ids = []
    for entry in sorted(userdata_dir.iterdir()):
        if entry.is_dir() and (entry / LOCALCONFIG_REL_PATH).exists():
            ids.append(entry.name)
    return ids


def read_persona_name(userdata_dir: pathlib.Path, user_id: str) -> str | None:
    """Read the PersonaName for a Steam account from its localconfig.vdf."""
    config_path = userdata_dir / user_id / LOCALCONFIG_REL_PATH
    try:
        text = config_path.read_text(encoding="utf-8", errors="replace")
        data = vdf.loads(text)
        return data["UserLocalConfigStore"]["friends"]["PersonaName"]
    except (OSError, KeyError, TypeError) as exc:
        logger.warning("Could not read PersonaName for Steam user %s: %s", user_id, exc)
        return None


_CHECKLIST_TITLE = "Checking Steam account"
CHECKLIST_LABEL = "Steam account"


def check_steam_account(env_path: pathlib.Path, steam_install_loc: pathlib.Path) -> str | None:
    """Is there an unambiguous Steam account to use?

    A single detected account, or a previously chosen one that's still
    present among several, both count as resolved. Multiple accounts with
    no prior choice is ambiguous and can't be resolved by a plain check -
    that needs :func:`resolve_steam_account_via_menu`.
    """
    data_dir = userdata_dir(steam_install_loc)
    ids = list_steam_user_ids(data_dir)
    if len(ids) == 1:
        return ids[0]
    if len(ids) > 1:
        current = env_file.get_env_values(env_path).get(USER_STEAM_LOC_INT_KEY) or ""
        return current if current in ids else None
    return None


def resolve_steam_account_via_menu(
    env_path: pathlib.Path, steam_install_loc: pathlib.Path, select_user=ui.select_option
) -> str | None:
    """Ask the user to pick among multiple detected Steam accounts."""
    data_dir = userdata_dir(steam_install_loc)
    ids = list_steam_user_ids(data_dir)
    if not ids:
        logger.warning("No Steam accounts found under %s", data_dir)
        ui.warning(f"No Steam accounts found under {data_dir}.")
        return None

    labels = []
    for user_id in ids:
        persona = read_persona_name(data_dir, user_id)
        labels.append(f"{persona} ({user_id})" if persona else user_id)
    index = select_user("Select your Steam account", labels)
    chosen = ids[index]

    env_file.update_env_value(env_path, USER_STEAM_LOC_INT_KEY, chosen)
    logger.info("%s set to %s", USER_STEAM_LOC_INT_KEY, chosen)
    return chosen


def resolve_steam_user(
    env_path: pathlib.Path, steam_install_loc: pathlib.Path, select_user=ui.select_option, delay: float = 0.5
) -> str | None:
    """Detect the Steam account to use and save it to ``USER_STEAM_LOC_INT``.

    Shown as a one-item checklist so it fills the screen consistently with
    the rest of setup. If more than one account is found, that's ambiguous
    within a single checklist tick, so it switches to a selection menu and
    then redraws the checklist afterwards to show the resolved account.
    """
    items = [(USER_STEAM_LOC_INT_KEY, CHECKLIST_LABEL)]

    def check(_key: str) -> str | None:
        return check_steam_account(env_path, steam_install_loc)

    missing = ui.checklist(_CHECKLIST_TITLE, items, check, delay=delay)

    if missing:
        chosen = resolve_steam_account_via_menu(env_path, steam_install_loc, select_user)
        # Switch back to the checklist to show the resolved account. No
        # delay - this redraws already-known state, so it should populate
        # prefilled rather than re-animating.
        ui.checklist(_CHECKLIST_TITLE, items, check, delay=0)
        return chosen

    # Nothing was missing: either a single account was auto-detected, or a
    # previously chosen account among several is still valid. Make sure
    # it's saved even if it was only just auto-detected.
    chosen = check_steam_account(env_path, steam_install_loc)
    env_file.update_env_value(env_path, USER_STEAM_LOC_INT_KEY, chosen)
    logger.info("%s set to %s", USER_STEAM_LOC_INT_KEY, chosen)
    return chosen


def launch_mcc_eac_disabled(launch_uri=None) -> None:
    """Launch Halo: MCC via Steam's anti-cheat-disabled launch option."""
    if launch_uri is None:
        launch_uri = os.startfile
    uri = f"steam://launch/{MCC_APPID}/option1"
    logger.info("Launching MCC via %s", uri)
    launch_uri(uri)
