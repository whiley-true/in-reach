import logging
import pathlib
import shutil

from inreach.app import ui
from inreach.app.setup import project, setup_proj

logger = logging.getLogger(__name__)

CREATE_PROJECT = "Create new project"
EXIT = "Exit"


def run_init_menu(remove_incomplete_project=shutil.rmtree) -> None:
    """The CLI menu shown when ``inreach init`` starts.

    The ``.inreach`` project folder is only created once the user picks
    "Create new project". Setup then runs immediately and the app exits
    afterwards rather than returning to this menu. If setup doesn't finish
    - a fatal missing install, Ctrl+C, an unexpected error - the
    half-configured ``.inreach`` folder is removed rather than left
    behind, so the next run starts clean instead of resuming stale state.
    """
    options = [CREATE_PROJECT, EXIT]
    choice = options[ui.select_option("in-reach", options)]
    if choice != CREATE_PROJECT:
        return

    project_dir = project.create_project()
    if project_dir is None:
        return

    try:
        setup_proj.setup_project(project_dir)
    except BaseException:
        _cleanup_incomplete_project(project_dir, remove_incomplete_project)
        raise


def _cleanup_incomplete_project(project_dir: pathlib.Path, remove=shutil.rmtree) -> None:
    logger.warning("Setup did not complete; removing incomplete project at %s", project_dir)
    remove(project_dir, ignore_errors=True)
