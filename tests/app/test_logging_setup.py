import logging
from pathlib import Path

import pytest

from in_reach.app import env_file, logging_setup


@pytest.fixture(autouse=True)
def _reset_logger():
    """configure_logging() mutates a module-global ("in_reach") logger -- undo that after every
    test so one test's LOG_LEVEL/handlers can't leak into the next."""
    logger = logging.getLogger(logging_setup._LOGGER_NAME)
    original_handlers = list(logger.handlers)
    original_level = logger.level
    original_propagate = logger.propagate
    yield
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    for handler in original_handlers:
        logger.addHandler(handler)
    logger.setLevel(original_level)
    logger.propagate = original_propagate


def _set(project_dir: Path, key: str, value: str) -> None:
    env_file.update_env_value(project_dir / ".env", key, value)


def test_configure_logging_writes_records_to_the_configured_log_file(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "in-reach.log"
    _set(tmp_path, "LOG_FILE", str(log_file))
    _set(tmp_path, "LOG_LEVEL", "INFO")

    logger = logging_setup.configure_logging(tmp_path)
    logging_setup.get_logger("some.module").info("hello world")

    assert log_file.is_file()
    assert "hello world" in log_file.read_text(encoding="utf-8")
    assert logger.level == logging.INFO


def test_configure_logging_respects_log_level(tmp_path: Path) -> None:
    log_file = tmp_path / "in-reach.log"
    _set(tmp_path, "LOG_FILE", str(log_file))
    _set(tmp_path, "LOG_LEVEL", "WARNING")

    logging_setup.configure_logging(tmp_path)
    logger = logging_setup.get_logger("some.module")
    logger.info("should not appear")
    logger.warning("should appear")

    text = log_file.read_text(encoding="utf-8")
    assert "should not appear" not in text
    assert "should appear" in text


def test_configure_logging_caps_the_file_at_log_lines(tmp_path: Path) -> None:
    log_file = tmp_path / "in-reach.log"
    _set(tmp_path, "LOG_FILE", str(log_file))
    _set(tmp_path, "LOG_LEVEL", "INFO")
    _set(tmp_path, "LOG_LINES", "5")

    logging_setup.configure_logging(tmp_path)
    logger = logging_setup.get_logger("some.module")
    for i in range(20):
        logger.info("line %d", i)

    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    assert "line 19" in lines[-1]
    assert "line 15" in lines[0]


def test_configure_logging_does_not_stream_by_default(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    log_file = tmp_path / "in-reach.log"
    _set(tmp_path, "LOG_FILE", str(log_file))
    _set(tmp_path, "OUTPUT_TO_STREAM", "false")

    logging_setup.configure_logging(tmp_path)
    logging_setup.get_logger("some.module").warning("quiet please")

    captured = capsys.readouterr()
    assert "quiet please" not in captured.err
    assert "quiet please" not in captured.out


def test_configure_logging_streams_when_output_to_stream_is_true(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    log_file = tmp_path / "in-reach.log"
    _set(tmp_path, "LOG_FILE", str(log_file))
    _set(tmp_path, "OUTPUT_TO_STREAM", "true")

    logging_setup.configure_logging(tmp_path)
    logging_setup.get_logger("some.module").warning("loud please")

    captured = capsys.readouterr()
    assert "loud please" in captured.err


def test_configure_logging_never_propagates_to_the_root_logger(tmp_path: Path) -> None:
    _set(tmp_path, "LOG_FILE", str(tmp_path / "in-reach.log"))

    logging_setup.configure_logging(tmp_path)

    assert logging.getLogger(logging_setup._LOGGER_NAME).propagate is False


def test_configure_logging_is_idempotent_and_does_not_duplicate_handlers(tmp_path: Path) -> None:
    _set(tmp_path, "LOG_FILE", str(tmp_path / "in-reach.log"))

    logging_setup.configure_logging(tmp_path)
    logging_setup.configure_logging(tmp_path)
    logger = logging.getLogger(logging_setup._LOGGER_NAME)

    assert len(logger.handlers) == 1


def test_configure_logging_with_no_log_file_still_avoids_no_handler_warnings(tmp_path: Path) -> None:
    logger = logging_setup.configure_logging(tmp_path)

    assert len(logger.handlers) == 1
    assert isinstance(logger.handlers[0], logging.NullHandler)


def test_get_logger_returns_a_child_of_the_in_reach_logger() -> None:
    logger = logging_setup.get_logger("in_reach.ide.main_window")

    assert logger.name == "in_reach.in_reach.ide.main_window"
    assert logger.name.startswith(logging_setup._LOGGER_NAME + ".")


# -- enable_crash_dumps() ------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_faulthandler():
    """enable_crash_dumps() mutates process-global faulthandler state and keeps a module-global
    file handle open -- undo both after every test."""
    import faulthandler

    was_enabled = faulthandler.is_enabled()
    yield
    faulthandler.disable()
    if logging_setup._crash_file is not None:
        try:
            logging_setup._crash_file.close()
        except OSError:
            pass
        logging_setup._crash_file = None
    if was_enabled:
        faulthandler.enable()


def test_enable_crash_dumps_creates_the_crash_log_and_enables_faulthandler(tmp_path: Path) -> None:
    import faulthandler

    crash_path = logging_setup.enable_crash_dumps(tmp_path)

    assert crash_path == tmp_path / "logs" / "crash.log"
    assert crash_path.is_file()
    assert faulthandler.is_enabled() is True


def test_enable_crash_dumps_respects_a_custom_log_dir(tmp_path: Path) -> None:
    custom_dir = tmp_path / "elsewhere"
    _set(tmp_path, "LOG_DIR", str(custom_dir))

    crash_path = logging_setup.enable_crash_dumps(tmp_path)

    assert crash_path == custom_dir / "crash.log"
    assert crash_path.is_file()


def test_enable_crash_dumps_is_idempotent_and_closes_the_previous_handle(tmp_path: Path) -> None:
    logging_setup.enable_crash_dumps(tmp_path)
    first_handle = logging_setup._crash_file

    logging_setup.enable_crash_dumps(tmp_path)

    assert logging_setup._crash_file is not first_handle
    assert first_handle.closed is True
