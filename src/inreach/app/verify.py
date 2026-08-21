import logging
import pathlib
import sys

import click

from inreach.app import ui
from inreach.app.setup import env_file, locations, project, steam
from inreach.logging_config import LOG_FILE

logger = logging.getLogger(__name__)

_CHECKLIST_TITLE = "Checking install setup"


def find_project_dir(base_dir: pathlib.Path | None = None) -> pathlib.Path | None:
    """Locate an existing ``.inreach`` project under ``base_dir`` (defaults
    to cwd). Returns ``None`` if there isn't one - unlike ``init``, verify
    never creates one itself."""
    base_dir = base_dir or pathlib.Path.cwd()
    project_dir = base_dir / project.PROJECT_DIR_NAME
    return project_dir if project_dir.exists() else None


def verify_installs(
    project_dir: pathlib.Path,
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
    then this whole combined checklist is redrawn once (prefilled, not
    re-animated) from scratch so the user ends up looking at the full,
    current state again.

    Shared between ``inreach init`` (called once the project folder has
    just been created) and ``inreach verify`` (called against an existing
    project), so improvements to this checklist benefit both.
    """
    env_path = project_dir / ".env"
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
    # auto-detected (not menu-chosen) one, and its profile name, now that
    # it's resolved.
    steam_loc = env_file.get_env_values(env_path).get(locations.STEAM_KEY) or ""
    account = steam.check_steam_account(env_path, steam_loc)
    if account:
        env_file.update_env_value(env_path, steam.USER_STEAM_LOC_INT_KEY, account)
        persona = steam.read_persona_name(steam.userdata_dir(steam_loc), account)
        if persona:
            env_file.update_env_value(env_path, steam.USER_STEAM_PROFILE_NAME_KEY, persona)

    fatal_missing = [key for key in missing if key in locations.FATAL_KEYS]
    if fatal_missing:
        label = locations.LOCATION_LABELS[fatal_missing[0]]
        ui.error(f"{label} not found. Cannot continue setup.")
        sys.exit(1)


def run_verify(base_dir: pathlib.Path | None = None) -> None:
    """CLI entry for ``inreach verify``.

    Unlike ``inreach init``, this expects a ``.inreach`` project to already
    exist - it never creates one.
    """
    click.echo(f"Logging to {LOG_FILE}")
    logger.info("Starting verification")

    if sys.platform != "win32":
        logger.error("This application is only supported on Windows.")
        ui.error("This application is only supported on Windows. Exiting.")
        sys.exit(1)

    project_dir = find_project_dir(base_dir)
    if project_dir is None:
        logger.error("No .inreach project found.")
        ui.error("No .inreach project found here. Run 'inreach init' first.")
        sys.exit(1)

    verify_installs(project_dir)
    ui.success("Verification complete.")
