"""Tesseract OCR PATH check plus the interactive winget-based installer.

``pytesseract`` (an ``inreach`` dependency) shells out to a ``tesseract``
executable it expects to find on PATH - it doesn't bundle one. This module
covers verifying that and, if missing, installing it via the bundled
``scripts/install_tesseract.bat`` (PowerShell + winget under the hood).
"""

import logging
import os
import pathlib
import shutil
import subprocess
import sys

from inreach.app import ui
from inreach.app.setup import processes

logger = logging.getLogger(__name__)

CHECKLIST_KEY = "TESSERACT_ON_PATH"
CHECKLIST_LABEL = "Tesseract OCR on PATH"

TESSERACT_EXE_NAME = "tesseract.exe"

# Package data (see pyproject.toml's [tool.setuptools.package-data]) ships
# this alongside the installed package, so it resolves the same way in an
# editable checkout and a real install.
INSTALL_SCRIPT_PATH = pathlib.Path(__file__).resolve().parent.parent.parent / "scripts" / "install_tesseract.bat"

CONFIRM_MANUAL = "Confirm installation manually"
INSTALL_NOW = "Install Tesseract now"

SCOPE_SYSTEM = "System (all users, requires admin)"
SCOPE_USER = "User (current user only)"

_PATH_REFRESH_COMMAND = (
    "[Environment]::GetEnvironmentVariable('Path','Machine') + ';' + "
    "[Environment]::GetEnvironmentVariable('Path','User')"
)


def check_tesseract_on_path(which=shutil.which) -> str | None:
    """Is ``tesseract`` resolvable on PATH right now?"""
    found = which(TESSERACT_EXE_NAME)
    if found:
        logger.info("tesseract found at %s", found)
    else:
        logger.warning("tesseract not found on PATH")
    return found


def _refresh_path_from_registry(run=subprocess.run) -> None:
    """Pull Machine + User ``Path`` straight from the registry into this
    process's environment.

    Installing/registering PATH happens inside a child ``cmd``/PowerShell
    process (the installer script) - environment changes made there never
    propagate back up to us, so we re-read the persisted values directly
    rather than relying on our own ``os.environ`` picking them up.
    """
    result = run(
        ["powershell", "-NoProfile", "-Command", _PATH_REFRESH_COMMAND],
        capture_output=True,
        text=True,
    )
    combined = result.stdout.strip()
    if combined:
        os.environ["PATH"] = combined


def _is_running_in_vscode() -> bool:
    return os.environ.get("TERM_PROGRAM") == "vscode"


def _restart_vscode(project_dir: pathlib.Path, popen=subprocess.Popen, close_process=processes.close_process) -> None:
    ui.warning("Visual Studio Code needs to restart to pick up Tesseract's new PATH entry.")
    ui.press_enter("Press enter to confirm (Will close and re-open vscode)")

    # Launch the replacement window before killing the old one - closing
    # Code.exe first would tear down the integrated terminal this process
    # is very likely running in, and we'd never reach the relaunch.
    popen(["code", str(project_dir)], shell=True)
    close_process("Code.exe")


def install_tesseract(
    project_dir: pathlib.Path,
    select_scope=ui.select_option,
    run_installer=subprocess.run,
    refresh_path=_refresh_path_from_registry,
    is_vscode=_is_running_in_vscode,
    restart_vscode=_restart_vscode,
    check=check_tesseract_on_path,
) -> bool:
    """Ask install scope, run the bundled installer script, refresh PATH.

    Returns whether tesseract is resolvable on PATH afterwards.
    """
    scope_index = select_scope("Install Tesseract for", [SCOPE_SYSTEM, SCOPE_USER])
    scope = "system" if scope_index == 0 else "user"

    ui.info(f"Installing Tesseract OCR ({scope} scope) - this may take a moment...")
    result = run_installer([str(INSTALL_SCRIPT_PATH), scope], shell=True)
    if result.returncode != 0:
        logger.error("install_tesseract.bat exited with code %s", result.returncode)
        ui.error("Tesseract installation failed.")
        return False

    refresh_path()

    if is_vscode():
        restart_vscode(project_dir)

    found = check() is not None
    if not found:
        ui.error("Tesseract still isn't resolvable on PATH after installing.")
    return found


def resolve_tesseract_via_menu(
    project_dir: pathlib.Path,
    select_option=ui.select_option,
    install=install_tesseract,
) -> None:
    """Ask the user to install Tesseract now, or bail out to fix it manually."""
    ui.warning("It appears Tesseract OCR is either not installed on not on PATH.")
    options = [CONFIRM_MANUAL, INSTALL_NOW]
    index = select_option("Tesseract OCR", options)
    if options[index] == CONFIRM_MANUAL:
        ui.warning("Cancelling setup so you can fix Tesseract's install location.")
        sys.exit(0)

    install(project_dir)
