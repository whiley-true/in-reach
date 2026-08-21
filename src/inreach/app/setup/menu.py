import pathlib

from inreach.app import ui
from inreach.app.setup import setup_proj

RUN_SETUP = "Run setup"
EXIT = "Exit"


def run_init_menu(project_dir: pathlib.Path) -> None:
    """The CLI menu shown after a project has been created."""
    options = [RUN_SETUP, EXIT]
    while True:
        choice = options[ui.select_option("in-reach", options)]
        if choice == RUN_SETUP:
            setup_proj.setup_project(project_dir)
        else:
            del project_dir
            break
