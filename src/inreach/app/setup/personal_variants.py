import logging
import pathlib
import sys

from inreach.app import ui
from inreach.app.setup import env_file, gametype_bootstrap

logger = logging.getLogger(__name__)

LOC_1_KEY = "PERSONAL_VARIANTS_LOC_1"
LOC_2_KEY = "PERSONAL_VARIANTS_LOC_2"
LOC_KEY = "PERSONAL_VARIANTS_LOC"
USER_REACH_STRING_KEY = "USER_REACH_STRING"

# A folder directly under PERSONAL_VARIANTS_LOC_1 is only a real personal-
# variants folder (as opposed to some other, unrelated folder MCC/Windows
# happens to have left under LocalFiles) if it actually has this
# structure inside it - e.g.
# ...\LocalFiles\000901f158282684\HaloReach\GameType. Matches
# PERSONAL_VARIANTS_LOC_2's fixed "${USER_REACH_STRING}\HaloReach\
# GameType" template.
GAMETYPE_SUBPATH = gametype_bootstrap.GAMETYPE_SUBPATH


def _is_personal_variants_folder(candidate: pathlib.Path) -> bool:
    return candidate.is_dir() and (candidate / GAMETYPE_SUBPATH).is_dir()


def resolve_personal_variants(
    env_path: pathlib.Path,
    select_variant=ui.select_option,
    open_folder=None,
    create_gametype=gametype_bootstrap.create_temporary_gametype,
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

    subfolders = sorted(p.name for p in loc_1_path.iterdir() if _is_personal_variants_folder(p))

    just_created = False
    if not subfolders:
        logger.info("No personal variants folder found; creating one in %s.", loc_1_path)
        ui.info(
            "Setting up your personal gametype folder - this drives Halo: MCC's own UI "
            "briefly, so expect your mouse/keyboard to be taken over for a moment."
        )
        if not create_gametype(loc_1_path):
            # Without a personal-variants folder the rest of this tool
            # can't do its job, so this is fatal, not skippable - same
            # ui.error + sys.exit(1) pattern as verify.py's other fatal
            # setup failures, which menu.run_init_menu's cleanup (catches
            # BaseException, so this includes SystemExit) relies on to
            # remove the half-configured .inreach project folder rather
            # than leaving it behind.
            ui.error("Could not create a personal variants folder automatically.")
            sys.exit(1)

        after = sorted(p.name for p in loc_1_path.iterdir() if _is_personal_variants_folder(p))
        new_folders = sorted(set(after) - set(subfolders))
        if not new_folders:
            ui.error("No new personal variants folder appeared after saving the gametype.")
            sys.exit(1)
        user_reach_string = new_folders[0]
        just_created = True
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

    if just_created:
        # This folder was just created fresh by ``create_gametype`` above,
        # so the only thing in it is the throwaway gametype it saved -
        # clean that up now that its job (making Reach create the folder)
        # is done.
        gametype_dir = pathlib.Path(comb)
        for entry in gametype_dir.iterdir():
            if entry.is_file():
                entry.unlink()
        logger.info("Deleted temporary gametype file(s) in %s", gametype_dir)
