import logging
import os
import pathlib
import sys

from dotenv import load_dotenv

_ENV_PATH = pathlib.Path(__file__).parent / ".env"
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


def setup_logging() -> None:
    logger = logging.getLogger("inreach")
    if logger.handlers:
        return
    logger.setLevel(LOG_LEVEL)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console_handler)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(file_handler)
