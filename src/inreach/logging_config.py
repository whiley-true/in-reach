"""Logging setup for inreach, configured from the project's ``.env`` file.

Reads ``LOG_DIR``/``LOG_FILE``/``LOG_LEVEL``/``LOG_LINES``/``OUTPUT_TO_STREAM``
from ``.inreach/.env`` (via :mod:`dotenv`) and exposes the resolved values
as module-level constants, plus :func:`setup_logging` to wire up the
``"inreach"`` logger.
"""

import logging
import os
import pathlib
import re
import sys

from dotenv import load_dotenv

_ENV_PATH = pathlib.Path.cwd() / ".inreach" / ".env"
load_dotenv(_ENV_PATH)

# "Repo root" is the caller's cwd (the scripting project being worked on),
# matching _ENV_PATH above -- not the installed inreach package's own
# location, which would be wrong once inreach runs as a pip-installed tool.
_DEFAULT_LOG_DIR = pathlib.Path.cwd() / ".inreach" / "logs"
_DEFAULT_LOG_LINES = 1000

_env_log_file = os.environ.get("LOG_FILE", "").strip()
_env_log_dir = os.environ.get("LOG_DIR", "").strip()

if _env_log_file:
    LOG_FILE = pathlib.Path(_env_log_file)
elif _env_log_dir:
    LOG_FILE = pathlib.Path(_env_log_dir) / "inreach.log"
else:
    LOG_FILE = _DEFAULT_LOG_DIR / "inreach.log"

LOG_DIR = LOG_FILE.parent

_LOG_LEVEL_NAME = os.environ.get("LOG_LEVEL", "").strip().upper() or "INFO"
LOG_LEVEL = getattr(logging, _LOG_LEVEL_NAME, logging.INFO)

# Maximum number of lines kept in LOG_FILE; the file is trimmed to this
# many lines (keeping the most recent) each time setup_logging() runs.
_env_log_lines = os.environ.get("LOG_LINES", "").strip()
LOG_LINES = int(_env_log_lines) if _env_log_lines.isdigit() else _DEFAULT_LOG_LINES

# Logs only go to file unless the project's .env sets OUTPUT_TO_STREAM=true.
_output_to_stream_raw = os.environ.get("OUTPUT_TO_STREAM", "").strip().lower()
OUTPUT_TO_STREAM = _output_to_stream_raw in ("1", "true", "yes", "on")

RESOLVED_ENV_DEFAULTS = {
    "LOG_DIR": str(LOG_DIR),
    "LOG_FILE": str(LOG_FILE),
    "LOG_LEVEL": _LOG_LEVEL_NAME,
    "LOG_LINES": str(LOG_LINES),
    "OUTPUT_TO_STREAM": "true" if OUTPUT_TO_STREAM else "false",
}


def _current_env_values(lines: list) -> dict:
    """Parses ``KEY=value`` pairs out of raw ``.env`` file lines.

    Args:
        lines: Raw lines read from a ``.env`` file, in file order.

    Returns:
        A dict mapping each key to its value with surrounding whitespace
        and matching quote characters stripped. Comment lines (starting
        with ``#``) and lines without an ``=`` are ignored.
    """
    values = {}
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, raw_value = line.partition("=")
            values[key.strip()] = raw_value.strip().strip("'\"")
    return values


def _set_env_line(lines: list, key: str, value: str) -> list:
    """Sets or appends a ``KEY=value`` line within a list of ``.env`` lines.

    Args:
        lines: Raw ``.env`` file lines to update in place.
        key: Env var name to set.
        value: Value to assign. Wrapped in single quotes when non-empty;
            written as ``KEY=`` when empty.

    Returns:
        The same ``lines`` list, mutated (and returned for convenience).
    """
    quoted = f"'{value}'" if value else ""
    new_line = f"{key}={quoted}"
    pattern = re.compile(rf"^{re.escape(key)}=")
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = new_line
            return lines
    lines.append(new_line)
    return lines


def fill_resolved_env_defaults(path: pathlib.Path, resolved: dict = RESOLVED_ENV_DEFAULTS) -> None:
    """Writes the effective logging config into an env file when blank/missing.

    Mirrors how ROOT_DIR/USER_WIN_NAME get filled with the real value in use,
    rather than staying blank placeholders. Any key that already has a
    non-empty value is left untouched. No-ops if ``path`` doesn't exist yet
    (e.g. called before the project has been created).

    Args:
        path: Path to the project's ``.env`` file.
        resolved: Mapping of env var names to their resolved values to fill
            in. Defaults to :data:`RESOLVED_ENV_DEFAULTS`.
    """
    if not path.exists():
        return

    lines = path.read_text(encoding="utf-8").splitlines()
    current = _current_env_values(lines)

    changed = False
    for key, value in resolved.items():
        if not current.get(key):
            lines = _set_env_line(lines, key, value)
            changed = True

    if changed:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# Fills an existing project's .env on every run (e.g. an older project
# missing OUTPUT_TO_STREAM). A no-op on a fresh `inreach init`, since the
# project's .env doesn't exist yet at import time — project.create_project()
# calls fill_resolved_env_defaults() again right after creating it.
fill_resolved_env_defaults(_ENV_PATH)


def _trim_log_file(path: pathlib.Path, max_lines: int) -> None:
    """Trims a log file in place to its last ``max_lines`` lines.

    No-ops if the file doesn't exist yet or is already within the limit.
    Used to bound ``LOG_FILE`` size without needing size-based rotation.

    Args:
        path: Path to the log file to trim.
        max_lines: Maximum number of trailing lines to keep. Values less
            than or equal to ``0`` disable trimming.
    """
    if max_lines <= 0 or not path.exists():
        return

    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) <= max_lines:
        return

    path.write_text("\n".join(lines[-max_lines:]) + "\n", encoding="utf-8")


def setup_logging(verbosity: int = 0, stream: bool = False) -> None:
    """Configures the ``"inreach"`` logger from the resolved env values.

    Adds a file handler writing to :data:`LOG_FILE` (trimmed beforehand to
    :data:`LOG_LINES` lines), and additionally a stdout handler when
    :data:`OUTPUT_TO_STREAM` is set or ``stream`` is passed. A no-op if the
    logger already has handlers attached, so repeated calls are safe.

    Args:
        verbosity: CLI verbosity count (e.g. the number of ``-v`` flags).
            Each step lowers the effective level by 10 below
            :data:`LOG_LEVEL` (INFO -> DEBUG -> ...), floored at
            ``logging.DEBUG``. ``0`` uses :data:`LOG_LEVEL` unchanged.
        stream: Forces the stdout handler on for this run (e.g. from a CLI
            ``--log-stream`` flag), in addition to whatever
            :data:`OUTPUT_TO_STREAM` already resolved to from the env.
    """
    logger = logging.getLogger("inreach")
    if logger.handlers:
        return
    effective_level = (
        max(LOG_LEVEL - verbosity * 10, logging.DEBUG) if verbosity else LOG_LEVEL
    )
    logger.setLevel(effective_level)

    if OUTPUT_TO_STREAM or stream:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(console_handler)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _trim_log_file(LOG_FILE, LOG_LINES)
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(file_handler)
