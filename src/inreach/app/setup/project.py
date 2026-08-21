import logging
import pathlib
import shutil
import sys

from inreach.app import ui

logger = logging.getLogger(__name__)

PROJECT_DIR_NAME = ".inreach"
TEMPLATE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / PROJECT_DIR_NAME


def create_project(base_dir: pathlib.Path | None = None) -> pathlib.Path | None:
    """Create a new ``.inreach`` project in ``base_dir`` (defaults to cwd).

    Returns the new project directory, or ``None`` if setup should not
    proceed (unsupported platform, or a project already exists here).
    """
    if sys.platform != "win32":
        logger.error("This application is only supported on Windows.")
        ui.error("This application is only supported on Windows. Exiting.")
        return None

    base_dir = base_dir or pathlib.Path.cwd()
    project_dir = base_dir / PROJECT_DIR_NAME

    if project_dir.exists():
        logger.info("Project already exists at %s", project_dir)
        ui.warning(f"A project already exists at {project_dir}. Exiting.")
        return None

    project_dir.mkdir(parents=True)
    shutil.copyfile(TEMPLATE_DIR / "example.env", project_dir / ".env")
    shutil.copyfile(TEMPLATE_DIR / ".gitignore", project_dir / ".gitignore")

    logger.info("Created project at %s", project_dir)
    ui.success(f"Created project at {project_dir}")
    return project_dir
