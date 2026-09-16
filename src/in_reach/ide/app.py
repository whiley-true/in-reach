"""Entry point for the graphical IDE (``in-reach run``).

Kept separate from ``in_reach.cli`` so ``cli.py``'s ``run`` command can call this through an
injectable reference -- ``click.testing.CliRunner`` invocations must never actually construct a
``QApplication``/block on ``app.exec()``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from in_reach.app import env_file, logging_setup
from in_reach.ide import icons
from in_reach.ide import theme as theme_module
from in_reach.ide import zoom as zoom_module
from in_reach.ide.first_run_dialog import FirstRunDialog
from in_reach.ide.main_window import MainWindow
from in_reach.ide.win_native_filter import BlockAccessibilityQueries

_ENV_NAME = ".env"
_FIRST_USE_KEY = "FIRST_USE"
_WINDOWS_APP_USER_MODEL_ID = "InReach.IDE"

_logger = logging_setup.get_logger(__name__)


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


def _install_crash_logging() -> None:
    """Logs any exception that escapes all the way to the top of the app, before whatever happens
    next (PyQt6's own default behavior for an exception raised inside a Qt slot -- print and
    otherwise treat it as fatal).

    Without this, a bug report like "the whole app just disappears, no error" was genuinely
    impossible to diagnose: ``OUTPUT_TO_STREAM`` defaults to ``false`` (see ``logging_setup``), and
    a GUI app launched via a Start Menu/desktop shortcut (rather than a terminal) has no console
    for the default ``sys.excepthook``'s own stderr print to land on anyway -- there was *nowhere*
    the traceback could have been seen. Chains to whatever ``sys.excepthook`` was already installed
    (the interpreter's own default, normally) after logging, so this only adds a log record, it
    never changes what happens to the exception afterward.
    """
    if getattr(sys.excepthook, "_in_reach_crash_logging", False):
        return  # already installed -- e.g. a second run() in the same process (tests) -- don't
        # stack another wrapper around it on top.

    previous_hook = sys.excepthook

    def _hook(exc_type, exc_value, exc_tb) -> None:
        _logger.critical("unhandled exception -- the app may be about to exit", exc_info=(exc_type, exc_value, exc_tb))
        previous_hook(exc_type, exc_value, exc_tb)

    _hook._in_reach_crash_logging = True
    sys.excepthook = _hook


def run(project_dir: Path) -> int:
    """Opens the IDE, fullscreen, against ``project_dir``'s ``.in-reach`` project folder.

    Blocks until the window is closed. Shows the first-run welcome popup (theme picker) exactly
    once per project, tracked by the ``FIRST_USE`` flag in ``project_dir/.env``.
    """
    env_path = project_dir / _ENV_NAME
    # Idempotent, and cheap -- cli.py's own "run" command already calls this before reaching here,
    # but ide_app.run() is also a valid entry point on its own (tests, a future non-CLI launcher),
    # so this makes sure logging is live either way rather than depending on the caller.
    logging_setup.configure_logging(project_dir)
    _install_crash_logging()
    crash_log_path = logging_setup.enable_crash_dumps(project_dir)
    if crash_log_path is not None:
        _logger.info("native crash dumps (if any) will be written to %s", crash_log_path)
    _logger.info("IDE starting (project_dir=%s)", project_dir)

    _set_windows_app_user_model_id()
    app = QApplication.instance() or QApplication(sys.argv)
    # Kept alive on the app itself -- installNativeEventFilter() doesn't take Python-side ownership,
    # so a local-only reference would let this get garbage-collected out from under Qt's C++ side.
    # See win_native_filter.py's own module docstring for why this exists at all.
    app._in_reach_accessibility_filter = BlockAccessibilityQueries()
    app.installNativeEventFilter(app._in_reach_accessibility_filter)
    app.setWindowIcon(icons.app_icon())
    saved_theme_name = env_file.get_env_values(env_path).get(theme_module.THEME_KEY, theme_module.DEFAULT_THEME_NAME)
    theme = theme_module.apply_theme(app, saved_theme_name)
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
        _logger.info("first use of this project -- showing the welcome dialog")
        dialog = FirstRunDialog(window, on_theme_changed=window.on_theme_applied)
        dialog.exec()
        env_file.update_env_value(env_path, _FIRST_USE_KEY, "false")

    exit_code = app.exec()
    _logger.info("IDE exiting (code=%d)", exit_code)
    return exit_code
