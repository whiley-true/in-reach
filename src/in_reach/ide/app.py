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
from in_reach.ide import theme as theme_module
from in_reach.ide.first_run_dialog import FirstRunDialog
from in_reach.ide.main_window import MainWindow

_ENV_NAME = ".env"
_FIRST_USE_KEY = "FIRST_USE"


def _is_first_use(env_path: Path) -> bool:
    value = env_file.get_env_values(env_path).get(_FIRST_USE_KEY, "true")
    return value.strip().lower() != "false"


def run(project_dir: Path) -> int:
    """Opens the IDE, fullscreen, against ``project_dir``'s ``.in-reach`` project folder.

    Blocks until the window is closed. Shows the first-run welcome popup (theme picker) exactly
    once per project, tracked by the ``FIRST_USE`` flag in ``project_dir/.env``.
    """
    env_path = project_dir / _ENV_NAME

    app = QApplication.instance() or QApplication(sys.argv)
    theme_module.apply_theme(app, theme_module.DEFAULT_THEME_NAME)

    window = MainWindow()
    window.showMaximized()

    if _is_first_use(env_path):
        dialog = FirstRunDialog(window, on_theme_changed=window.refresh_icon_colors)
        dialog.exec()
        env_file.update_env_value(env_path, _FIRST_USE_KEY, "false")

    return app.exec()
