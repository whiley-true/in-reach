from inreach.app import ui
from inreach.app.setup import project, setup_proj

CREATE_PROJECT = "Create new project"
EXIT = "Exit"


def run_init_menu() -> None:
    """The CLI menu shown when ``inreach init`` starts.

    The ``.inreach`` project folder is only created once the user picks
    "Create new project". Setup then runs immediately and the app exits
    afterwards rather than returning to this menu.
    """
    options = [CREATE_PROJECT, EXIT]
    choice = options[ui.select_option("in-reach", options)]
    if choice != CREATE_PROJECT:
        return

    project_dir = project.create_project()
    if project_dir is not None:
        setup_proj.setup_project(project_dir)
