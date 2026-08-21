import logging
import pathlib
import sys
import time

from inreach.app import ui
from inreach.app.setup import env_file, locations, mcc_launch, personal_variants, screens, steam, users
from inreach.logging_config import LOG_FILE

logger = logging.getLogger(__name__)

USER_WIN_NAME_KEY = "USER_WIN_NAME"
FINAL_CHECKLIST_HANG_SECONDS = 1.0
_CHECKLIST_TITLE = "Checking install setup"


def setup_project(
    project_dir: pathlib.Path, sleep=time.sleep, final_hang: float = FINAL_CHECKLIST_HANG_SECONDS
) -> None:
    logger.info("Logging to %s", LOG_FILE)
    logger.info("Starting project setup")

    if sys.platform != "win32":
        logger.error("This application is only supported on Windows.")
        ui.error("This application is only supported on Windows. Exiting.")
        sys.exit(1)

    env_path = project_dir / ".env"

    # TODO: verify the inreach package installed all files correctly
    # TODO: verify the template folder was copied successfully
    # TODO: verify all dependencies installed correctly (list still to be finalised)

    screens.save_screen_config(project_dir)
    _set_user_win_name(env_path)
    _run_setup_checklist(env_path)

    mcc_launch.run_eac_launch_step(project_dir, env_path)
    personal_variants.resolve_personal_variants(env_path)

    # Hang on the last completed checklist for a beat before clearing it, so
    # the user actually sees it finished rather than it vanishing instantly.
    if final_hang:
        sleep(final_hang)

    ui.clear_screen()
    logger.info("Project setup complete")
    ui.success("Project setup complete.")


def _run_setup_checklist(
    env_path: pathlib.Path,
    prompt_for_missing=locations.ask_user_for_path,
    verify_steam=locations.verify_steam_install,
    select_user=ui.select_option,
    delay: float = 0.5,
) -> None:
    """Steps 1-7: install locations plus the Steam account, as one
    continuous checklist screen (rather than the Steam account item
    clearing the locations checklist away into a screen of its own).

    Any interactive resolution - a folder picker for a location, or a menu
    when multiple Steam accounts are found - happens on its own screen,
    then this whole combined checklist is redrawn once from scratch so the
    user ends up looking at the full, current state again.
    """
    items = [(key, locations.LOCATION_LABELS[key]) for key in locations.LOCATION_KEYS]
    items.append((steam.USER_STEAM_LOC_INT_KEY, steam.CHECKLIST_LABEL))

    def check(key: str) -> str | None:
        if key == steam.USER_STEAM_LOC_INT_KEY:
            steam_loc = env_file.get_env_values(env_path).get(locations.STEAM_KEY) or ""
            return steam.check_steam_account(env_path, steam_loc)
        return locations.check_location(env_path, key)

    missing = ui.checklist(_CHECKLIST_TITLE, items, check, delay=delay)

    changed = False
    if missing:
        changed = locations.resolve_missing_locations(env_path, missing, prompt_for_missing, verify_steam)

        # Re-check with fresh env values rather than trusting the earlier
        # ``missing`` list: fixing Steam's own install path can turn an
        # unresolvable account into an unambiguous one without needing the
        # menu at all.
        if check(steam.USER_STEAM_LOC_INT_KEY) is None:
            steam_loc = env_file.get_env_values(env_path).get(locations.STEAM_KEY) or ""
            steam.resolve_steam_account_via_menu(env_path, steam_loc, select_user)
            changed = True

    if changed:
        # Switch back to the checklist so the user sees the full, current
        # state rather than being left on the picker/menu screen. No delay
        # here - this is a redraw of already-known state, not a fresh
        # check, so it should populate prefilled rather than re-animating.
        missing = ui.checklist(_CHECKLIST_TITLE, items, check, delay=0)

    # `check()` only reads the Steam account for display - persist an
    # auto-detected (not menu-chosen) one now that it's resolved.
    steam_loc = env_file.get_env_values(env_path).get(locations.STEAM_KEY) or ""
    account = steam.check_steam_account(env_path, steam_loc)
    if account:
        env_file.update_env_value(env_path, steam.USER_STEAM_LOC_INT_KEY, account)

    fatal_missing = [key for key in missing if key in locations.FATAL_KEYS]
    if fatal_missing:
        label = locations.LOCATION_LABELS[fatal_missing[0]]
        ui.error(f"{label} not found. Cannot continue setup.")
        sys.exit(1)


def _set_user_win_name(env_path: pathlib.Path) -> None:
    entries = users.list_windows_users()
    if not entries:
        logger.warning("No entries found under C:/Users.")
        return

    if len(entries) == 1:
        chosen = entries[0]
    else:
        index = ui.select_option("Select your Windows user", entries)
        chosen = entries[index]

    env_file.update_env_value(env_path, USER_WIN_NAME_KEY, chosen)
    logger.info("%s set to %s", USER_WIN_NAME_KEY, chosen)
