import logging
import pathlib

from inreach.app import ui
from inreach.app.setup import personal_variants, processes, steam, window_tracking

logger = logging.getLogger(__name__)

MCC_PROCESS_NAME = "MCC-Win64-Shipping.exe"
LAUNCH_TIMEOUT_SECONDS = 60.0


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
) -> None:
    """Launch Halo: MCC with anti-cheat disabled and capture where its
    window ends up."""
    if is_process_running(MCC_PROCESS_NAME):
        ui.warning("Halo: MCC is already running.")
        if not confirm("Close Halo: MCC to relaunch it with anti-cheat disabled?"):
            logger.info("User declined to close a running MCC; skipping EAC launch step.")
            return
        close_process(MCC_PROCESS_NAME)

    ui.info("Launching Halo: MCC with anti-cheat disabled - this may take a moment...")
    launch()

    if not wait_for_process(MCC_PROCESS_NAME, timeout=LAUNCH_TIMEOUT_SECONDS):
        ui.error("Halo: MCC did not start within the expected time.")
        logger.error("Timed out waiting for %s to launch.", MCC_PROCESS_NAME)
        return

    logger.info("Halo: MCC launched with anti-cheat disabled.")
    ui.success("Halo: MCC launched with anti-cheat disabled.")
    record(project_dir, _is_mcc_title)

    # Checked here, while MCC is still open, rather than after closing it:
    # once this grows to actually create the folder, that'll mean driving
    # the game's own UI, which needs it running - not a second re-launch.
    resolve_personal_variants(env_path)

    # This launch is only to verify anti-cheat-disabled mode works and
    # capture the window/screen it lands on - it shouldn't stay open
    # through the rest of setup.
    ui.info("Closing Halo: MCC.")
    close_process(MCC_PROCESS_NAME)
