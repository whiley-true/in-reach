"""Recomputes/fills a project's ``.env``, without ever printing anything itself.

``ROOT_DIR``/``IS_WINDOWS`` describe the machine and location the command is running from right
now, so they're always rewritten on every call -- the project folder may have moved, or this may
be a different machine than last time. The logging keys are only filled in when still blank, so a
user's own customization of them is left alone.
"""

from __future__ import annotations

import platform
from pathlib import Path

from in_reach.app import env_file

_ENV_NAME = ".env"
_LOG_FILE_NAME = "in-reach.log"

_DEFAULT_LOG_LEVEL = "INFO"
_DEFAULT_LOG_LINES = "1000"
_DEFAULT_OUTPUT_TO_STREAM = "false"


def verify_project(project_dir: Path) -> None:
    """Fills/rechecks ``<project_dir>/.env`` against the current environment.

    Args:
        project_dir: The project's ``.in-reach`` folder, as returned by
            :func:`in_reach.app.project.get_project_dir`.
    """
    env_path = project_dir / _ENV_NAME
    values = env_file.get_env_values(env_path)

    env_file.update_env_value(env_path, "ROOT_DIR", str(project_dir.parent))
    env_file.update_env_value(
        env_path, "IS_WINDOWS", "true" if platform.system() == "Windows" else "false"
    )

    log_dir = values.get("LOG_DIR") or str(project_dir / "logs")
    if not values.get("LOG_DIR"):
        env_file.update_env_value(env_path, "LOG_DIR", log_dir)
    if not values.get("LOG_FILE"):
        env_file.update_env_value(env_path, "LOG_FILE", str(Path(log_dir) / _LOG_FILE_NAME))
    if not values.get("LOG_LEVEL"):
        env_file.update_env_value(env_path, "LOG_LEVEL", _DEFAULT_LOG_LEVEL)
    if not values.get("LOG_LINES"):
        env_file.update_env_value(env_path, "LOG_LINES", _DEFAULT_LOG_LINES)
    if not values.get("OUTPUT_TO_STREAM"):
        env_file.update_env_value(env_path, "OUTPUT_TO_STREAM", _DEFAULT_OUTPUT_TO_STREAM)
