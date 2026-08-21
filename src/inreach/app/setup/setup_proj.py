import logging
import pathlib
import sys
import time

from inreach.app import ui, verify
from inreach.app.setup import env_file, mcc_launch, screens, users
from inreach.logging_config import LOG_FILE

logger = logging.getLogger(__name__)

USER_WIN_NAME_KEY = "USER_WIN_NAME"
FINAL_CHECKLIST_HANG_SECONDS = 1.0


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
    verify.verify_installs(project_dir)

    mcc_launch.run_eac_launch_step(project_dir, env_path)

    # Hang on the last completed checklist for a beat before clearing it, so
    # the user actually sees it finished rather than it vanishing instantly.
    if final_hang:
        sleep(final_hang)

    ui.clear_screen()
    logger.info("Project setup complete")
    ui.success("Project setup complete.")


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
