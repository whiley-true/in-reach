import logging
import pathlib

from inreach.app import ui, verify
from inreach.app.setup import env_file, personal_variants, processes, steam, window_tracking

logger = logging.getLogger(__name__)

MCC_PROCESS_NAME = "MCC-Win64-Shipping.exe"
LAUNCH_TIMEOUT_SECONDS = 60.0

MCC_LAUNCH_KEY = "mcc_launch"
PERSONAL_GAMETYPE_KEY = "personal_gametype"


def _is_mcc_title(title: str) -> bool:
    return "Halo" in title and "Master Chief" in title


def run_eac_launch_step(
    project_dir: pathlib.Path,
    env_path: pathlib.Path,
    confirm=ui.confirm,
    is_process_running=processes.is_process_running,
    close_process=processes.close_process,
    launch=steam.launch_mcc_eac_disabled,
    wait_for_process=processes.wait_for_process,
    record=window_tracking.poll_and_record_window,
    resolve_personal_variants=personal_variants.resolve_personal_variants,
    checklist_items_and_check=None,
    delay: float = 0,
) -> None:
    """Launch Halo: MCC with anti-cheat disabled, capture where its window
    ends up, and make sure a personal gametype folder is set up.

    Shown as two more items appended onto the exact same install checklist
    ``verify.verify_installs`` already showed (same title, same items, via
    ``verify.checklist_items_and_check``) rather than a second, separately-
    titled checklist - by the time this runs, ``verify_installs`` has
    already resolved/confirmed all of those, so re-checking them here is
    just a cheap, instant redraw (``delay=0``) that keeps the two new items
    visually part of the one list the user's already been looking at.
    """
    if checklist_items_and_check is None:
        # Resolved here rather than as the parameter's own default value -
        # this module is reached (via inreach.app.setup's package __init__
        # -> menu -> setup_proj -> mcc_launch) while inreach.app.verify is
        # still mid-import (verify.py itself imports inreach.app.setup),
        # so verify.checklist_items_and_check doesn't exist yet at that
        # point; by the time this function is actually called, verify.py
        # has long finished importing.
        checklist_items_and_check = verify.checklist_items_and_check

    if is_process_running(MCC_PROCESS_NAME):
        ui.warning("Halo: MCC is already running.")
        if not confirm("Close Halo: MCC to relaunch it with anti-cheat disabled?"):
            logger.info("User declined to close a running MCC; skipping EAC launch step.")
            return
        close_process(MCC_PROCESS_NAME)

    ui.info("Launching Halo: MCC with anti-cheat disabled - this may take a moment...")

    launched = False

    def _check_mcc_launch(key: str) -> str | None:
        nonlocal launched
        launch()
        if not wait_for_process(MCC_PROCESS_NAME, timeout=LAUNCH_TIMEOUT_SECONDS):
            logger.error("Timed out waiting for %s to launch.", MCC_PROCESS_NAME)
            return None
        logger.info("Halo: MCC launched with anti-cheat disabled.")
        record(project_dir, _is_mcc_title)
        launched = True
        return "anti-cheat disabled"

    def _check_personal_gametype(key: str) -> str | None:
        # Only attempted once MCC has actually launched - checked here,
        # while it's still open, rather than after closing it: creating
        # the folder means driving the game's own UI, which needs it
        # running, not a second re-launch.
        if not launched:
            return None
        resolve_personal_variants(env_path)
        return env_file.get_env_values(env_path).get(personal_variants.LOC_KEY) or "configured"

    preceding_items, preceding_check = checklist_items_and_check(project_dir)
    items = [
        *preceding_items,
        (MCC_LAUNCH_KEY, "Halo: MCC launch (anti-cheat disabled)"),
        (PERSONAL_GAMETYPE_KEY, "Personal gametype folder"),
    ]
    new_checks = {MCC_LAUNCH_KEY: _check_mcc_launch, PERSONAL_GAMETYPE_KEY: _check_personal_gametype}

    def check(key: str) -> str | None:
        if key in new_checks:
            return new_checks[key](key)
        return preceding_check(key)

    missing = ui.checklist(verify.CHECKLIST_TITLE, items, check, delay=delay)

    if MCC_LAUNCH_KEY in missing:
        ui.error("Halo: MCC did not start within the expected time.")
        return

    # This launch is only to verify anti-cheat-disabled mode works and
    # capture the window/screen it lands on - it shouldn't stay open
    # through the rest of setup.
    ui.info("Closing Halo: MCC.")
    close_process(MCC_PROCESS_NAME)
