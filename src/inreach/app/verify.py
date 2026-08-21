import logging
import sys

import click

from inreach.app import ui
from inreach.logging_config import LOG_FILE

logger = logging.getLogger(__name__)


def verify_installs() -> None:
    click.echo(f"Logging to {LOG_FILE}")
    logger.info("Starting verification")

    status_dict = {
        "system": None,
        "inreach_files": None,
        "inreach_dependencies": None,
        "user_slug": None,
        "steam_installed": None,
        "halo_mcc_base_installed": None,
        "halo_reach_in_mcc_installed": None,
        "personal_games_folder": None,
        "halo_reach_hotreload": None,
        "standard_games": None,
        "hopper_games": None,
    }

    if sys.platform != "win32":
        logger.error("This application is only supported on Windows.")
        ui.error("This application is only supported on Windows. Exiting.")
        status_dict["system"] = False
        return

    status_dict["system"] = True

    # TODO: check the inreach package has installed all files correctly
    # TODO: check the inreach package has installed all dependencies correctly
    # TODO: get the present user slug
    # TODO: check steam installed
    # TODO: halo mcc base installed
    # TODO: halo reach in mcc installed
    # TODO: personal games folder
    # TODO: halo reach hotreload
    # TODO: standard games
    # TODO: hopper games
