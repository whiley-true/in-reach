"""Entry point for the graphical IDE (``in-reach run``).

Kept separate from ``in_reach.cli`` so ``cli.py``'s ``run`` command can call this through an
injectable reference -- ``click.testing.CliRunner`` invocations must never actually construct a
``QApplication``/block on ``app.exec()``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from in_reach.app import env_file
from in_reach.ide import icons
from in_reach.ide import theme as theme_module
from in_reach.ide import zoom as zoom_module
from in_reach.ide.first_run_dialog import FirstRunDialog
from in_reach.ide.main_window import MainWindow

_ENV_NAME = ".env"
_FIRST_USE_KEY = "FIRST_USE"
_WINDOWS_APP_USER_MODEL_ID = "InReach.IDE"


def _set_windows_app_user_model_id() -> None:
    """Without this, Windows identifies the taskbar entry by the launching executable (the
    console-script shim under ``Scripts/``, or ``python.exe`` itself) rather than by this app, and
    falls back to that executable's own embedded icon -- a generic Python icon -- for the taskbar
    button instead of the window icon set below. Must run before the window (ideally before
    ``QApplication``) is created; irrelevant on non-Windows platforms.
    """
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_WINDOWS_APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        pass


def _is_first_use(env_path: Path) -> bool:
    value = env_file.get_env_values(env_path).get(_FIRST_USE_KEY, "true")
    return value.strip().lower() != "false"


def run(project_dir: Path) -> int:
    """Opens the IDE, fullscreen, against ``project_dir``'s ``.in-reach`` project folder.

    Blocks until the window is closed. Shows the first-run welcome popup (theme picker) exactly
    once per project, tracked by the ``FIRST_USE`` flag in ``project_dir/.env``.
    """
    env_path = project_dir / _ENV_NAME

    _set_windows_app_user_model_id()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setWindowIcon(icons.app_icon())
    theme = theme_module.apply_theme(app, theme_module.DEFAULT_THEME_NAME)
    # Applied before MainWindow is built, same as the theme above, so every widget it constructs
    # is polished against the saved zoom level from the start rather than jumping once on first use.
    zoom_module.apply_zoom(app, zoom_module.get_zoom(env_path))

    window = MainWindow(root_dir=project_dir.parent)
    window.on_theme_applied(theme)
    window.showMaximized()
    # refresh_icon_colors() reads isMaximized() to pick win_maximize vs win_restore -- on_theme_
    # applied() (and MainWindow.__init__ itself) both ran it before this showMaximized(), while the
    # window was still in its pre-maximized state, so without this the icon stays wrong until the
    # button's own toggle_maximize() happens to run once.
    window.refresh_icon_colors()

    if _is_first_use(env_path):
        dialog = FirstRunDialog(window, on_theme_changed=window.on_theme_applied)
        dialog.exec()
        env_file.update_env_value(env_path, _FIRST_USE_KEY, "false")

    return app.exec()
