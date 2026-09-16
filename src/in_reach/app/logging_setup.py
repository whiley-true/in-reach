"""Wires up real logging from the ``LOG_DIR``/``LOG_FILE``/``LOG_LEVEL``/``LOG_LINES``/
``OUTPUT_TO_STREAM`` values :func:`in_reach.app.verify.verify_project` already computes and
persists into a project's ``.env`` -- those keys existed as config placeholders (see
``in_reach/.in-reach/example.env``) but nothing ever actually logged anything with them.

Every logger the rest of the app uses is a child of the ``"in_reach"`` logger configured here (see
:func:`get_logger`), never the root logger -- so this never touches logging for anything else
importing in-reach as a library, and pytest's own log capture is unaffected unless a test calls
:func:`configure_logging` itself.
"""

from __future__ import annotations

import faulthandler
import logging
from pathlib import Path

from in_reach.app import env_file

_ENV_NAME = ".env"
_LOGGER_NAME = "in_reach"
_DEFAULT_LEVEL = "INFO"
_DEFAULT_MAX_LINES = 1000
_CRASH_FILE_NAME = "crash.log"

#: Keeps the crash-dump file object alive for the whole process -- faulthandler.enable() needs its
#: file argument to stay open (it writes to the raw file descriptor from inside a signal handler,
#: which can't safely re-open anything), so this can't be a local variable that gets garbage
#: collected once enable_crash_dumps() returns.
_crash_file = None

_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


class _LineCappedFileHandler(logging.Handler):
    """Keeps ``LOG_FILE`` to at most ``max_lines`` lines -- ``LOG_LINES`` is a line count, not a
    byte size, so :class:`logging.handlers.RotatingFileHandler`'s own size/backup-count rollover
    doesn't apply here. Simple by design: this app logs at desktop-IDE volume, not service volume,
    so rewriting the (small, capped) file on every record is cheap enough not to need a smarter
    append-then-occasionally-trim scheme.
    """

    def __init__(self, path: Path, max_lines: int) -> None:
        super().__init__()
        self._path = path
        self._max_lines = max(1, max_lines)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lines: list[str] = []
        if self._path.exists():
            try:
                self._lines = self._path.read_text(encoding="utf-8").splitlines()[-self._max_lines :]
            except OSError:
                self._lines = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:  # noqa: BLE001 -- logging.Handler's own documented emit() contract
            self.handleError(record)
            return
        self._lines.extend(message.splitlines() or [""])
        if len(self._lines) > self._max_lines:
            self._lines = self._lines[-self._max_lines :]
        try:
            self._path.write_text("\n".join(self._lines) + "\n", encoding="utf-8")
        except OSError:
            self.handleError(record)


def configure_logging(project_dir: Path) -> logging.Logger:
    """(Re-)configures the ``"in_reach"`` logger from ``<project_dir>/.env``'s logging keys --
    idempotent, so calling it again (a settings change, a test) replaces the previous handlers
    rather than stacking duplicates.

    Args:
        project_dir: The project's ``.in-reach`` folder, as returned by
            :func:`in_reach.app.project.get_project_dir` -- same argument
            :func:`in_reach.app.verify.verify_project` takes, and normally called right after it
            so the logging keys are already populated.

    Returns:
        The configured ``"in_reach"`` logger, ready for :func:`get_logger` callers to use.
    """
    values = env_file.get_env_values(project_dir / _ENV_NAME)
    logger = logging.getLogger(_LOGGER_NAME)

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    level_name = (values.get("LOG_LEVEL") or _DEFAULT_LEVEL).strip().upper()
    logger.setLevel(_LEVELS.get(level_name, logging.INFO))
    # Never bubble up to the root logger -- an app embedding in-reach (or pytest) owns its own
    # root logging config, and shouldn't have this project's own file/stream handlers imposed on
    # every other logger in the process.
    logger.propagate = False

    formatter = logging.Formatter(_FORMAT)

    log_file = values.get("LOG_FILE")
    if log_file:
        try:
            max_lines = int(values.get("LOG_LINES") or _DEFAULT_MAX_LINES)
        except ValueError:
            max_lines = _DEFAULT_MAX_LINES
        file_handler = _LineCappedFileHandler(Path(log_file), max_lines)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    if (values.get("OUTPUT_TO_STREAM") or "").strip().lower() == "true":
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    if not logger.handlers:
        # No file configured and streaming off -- still avoids Python's own "No handlers could be
        # found" warning if something logs before/without configure_logging ever running.
        logger.addHandler(logging.NullHandler())

    return logger


def enable_crash_dumps(project_dir: Path) -> Path | None:
    """Enables :mod:`faulthandler` against ``<LOG_DIR>/crash.log`` -- catches what
    :func:`configure_logging`'s own Python-level logging structurally cannot: a fatal *native*
    crash (an access violation inside Qt/PyQt's own C++ code, a stack overflow, ...) that kills the
    process before Python's exception machinery -- ``sys.excepthook`` included -- ever runs at all.
    A bug report of "the whole app just disappears, nothing in the log" is exactly what that looks
    like from the outside; this is the one thing that can still leave a trace for it (a Python-level
    stack per thread, not a full native one, but far better than nothing).

    Idempotent (safe to call more than once in the same process, e.g. across tests) -- re-running it
    just re-points ``faulthandler`` at a fresh file handle rather than stacking anything.

    Args:
        project_dir: The project's ``.in-reach`` folder, same argument :func:`configure_logging`
            takes.

    Returns:
        The crash-log path, or ``None`` if it couldn't be opened (a read-only/missing ``LOG_DIR``)
        -- faulthandler is simply left disabled in that case, same as if this were never called.
    """
    global _crash_file
    values = env_file.get_env_values(project_dir / _ENV_NAME)
    log_dir = Path(values.get("LOG_DIR") or (project_dir / "logs"))
    crash_path = log_dir / _CRASH_FILE_NAME
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handle = crash_path.open("a", buffering=1, encoding="utf-8")
    except OSError:
        return None

    if _crash_file is not None:
        faulthandler.disable()
        try:
            _crash_file.close()
        except OSError:
            pass

    _crash_file = handle
    faulthandler.enable(file=_crash_file, all_threads=True)
    return crash_path


def get_logger(name: str) -> logging.Logger:
    """A child of the ``"in_reach"`` logger :func:`configure_logging` sets up -- call with
    ``__name__`` from anywhere in the app, same as the stdlib ``logging.getLogger(__name__)``
    idiom, just namespaced under ``"in_reach"`` so :func:`configure_logging` can reach every one
    of them through the single parent logger."""
    return logging.getLogger(f"{_LOGGER_NAME}.{name}")
