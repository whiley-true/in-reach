import logging
import pathlib
import sys

from inreach.app import ui
from inreach.app.setup import env_file

logger = logging.getLogger(__name__)

LOC_1_KEY = "PERSONAL_VARIANTS_LOC_1"
LOC_2_KEY = "PERSONAL_VARIANTS_LOC_2"
LOC_KEY = "PERSONAL_VARIANTS_LOC"
USER_REACH_STRING_KEY = "USER_REACH_STRING"


def resolve_personal_variants(
    env_path: pathlib.Path, select_variant=ui.select_option, open_folder=None, confirm=ui.confirm
) -> None:
    if open_folder is None:
        import os

        open_folder = os.startfile

    values = env_file.get_env_values(env_path)
    loc_1 = values.get(LOC_1_KEY) or ""
    loc_1_path = pathlib.Path(loc_1) if loc_1 else None

    if loc_1_path is None or not loc_1_path.exists():
        logger.warning("%s not found; skipping personal variants setup.", LOC_1_KEY)
        # TODO: handle a missing/unset PERSONAL_VARIANTS_LOC_1 folder
        return

    subfolders = sorted(p.name for p in loc_1_path.iterdir() if p.is_dir())

    if not subfolders:
        if confirm("No personal variants folder found. Create one now?"):
            logger.info("User opted to create a personal variants folder in %s.", loc_1_path)
            # TODO: create the personal variants folder - no folder-creation
            # logic yet, revisit once there is test data for the expected
            # folder/file layout.
            return
        ui.warning("Exiting - no personal variants folder to use.")
        sys.exit(0)
    elif len(subfolders) == 1:
        user_reach_string = subfolders[0]
    else:
        index = select_variant("Select your personal Reach folder", subfolders)
        user_reach_string = subfolders[index]
        open_folder(str(loc_1_path / user_reach_string))

    env_file.update_env_value(env_path, USER_REACH_STRING_KEY, user_reach_string)
    logger.info("%s set to %s", USER_REACH_STRING_KEY, user_reach_string)

    values = env_file.get_env_values(env_path)
    loc_2 = values.get(LOC_2_KEY) or ""
    env_file.update_env_value(env_path, LOC_2_KEY, loc_2)

    comb = str(pathlib.Path(loc_1) / loc_2) if loc_2 else loc_1
    env_file.update_env_value(env_path, LOC_KEY, comb)
    logger.info("%s set to %s", LOC_KEY, comb)
