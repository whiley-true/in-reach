import logging
import os
import pathlib
import re
import sys

from dotenv import load_dotenv

_ENV_PATH = pathlib.Path.cwd() / ".inreach" / ".env"
load_dotenv(_ENV_PATH)

_DEFAULT_LOG_DIR = pathlib.Path.home() / ".inreach" / "logs"

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

# Logs only go to file unless the project's .env sets OUTPUT_TO_STREAM=true.
_output_to_stream_raw = os.environ.get("OUTPUT_TO_STREAM", "").strip().lower()
OUTPUT_TO_STREAM = _output_to_stream_raw in ("1", "true", "yes", "on")

RESOLVED_ENV_DEFAULTS = {
    "LOG_DIR": str(LOG_DIR),
    "LOG_FILE": str(LOG_FILE),
    "LOG_LEVEL": _LOG_LEVEL_NAME,
    "OUTPUT_TO_STREAM": "true" if OUTPUT_TO_STREAM else "false",
}


def _current_env_values(lines: list) -> dict:
    values = {}
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, raw_value = line.partition("=")
            values[key.strip()] = raw_value.strip().strip("'\"")
    return values


def _set_env_line(lines: list, key: str, value: str) -> list:
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
    """Write the effective logging config into an env file when blank/missing.

    Mirrors how ROOT_DIR/USER_WIN_NAME get filled with the real value in use,
    rather than staying blank placeholders. Any key that already has a
    non-empty value is left untouched. No-ops if ``path`` doesn't exist yet
    (e.g. called before the project has been created).
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


def setup_logging() -> None:
    logger = logging.getLogger("inreach")
    if logger.handlers:
        return
    logger.setLevel(LOG_LEVEL)

    if OUTPUT_TO_STREAM:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(console_handler)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(file_handler)
