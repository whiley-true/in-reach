import logging

import pytest

from inreach import logging_config


@pytest.fixture
def clean_inreach_logger():
    logger = logging.getLogger("inreach")
    original_handlers = list(logger.handlers)
    for handler in original_handlers:
        logger.removeHandler(handler)

    yield logger

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    for handler in original_handlers:
        logger.addHandler(handler)


def _console_handlers(logger):
    return [h for h in logger.handlers if type(h) is logging.StreamHandler]


def _file_handlers(logger):
    return [h for h in logger.handlers if isinstance(h, logging.FileHandler)]


def test_setup_logging_skips_console_handler_by_default(monkeypatch, tmp_path, clean_inreach_logger):
    monkeypatch.setattr(logging_config, "OUTPUT_TO_STREAM", False)
    monkeypatch.setattr(logging_config, "LOG_FILE", tmp_path / "inreach.log")
    monkeypatch.setattr(logging_config, "LOG_DIR", tmp_path)

    logging_config.setup_logging()

    assert _console_handlers(clean_inreach_logger) == []
    assert len(_file_handlers(clean_inreach_logger)) == 1


def test_setup_logging_adds_console_handler_when_enabled(monkeypatch, tmp_path, clean_inreach_logger):
    monkeypatch.setattr(logging_config, "OUTPUT_TO_STREAM", True)
    monkeypatch.setattr(logging_config, "LOG_FILE", tmp_path / "inreach.log")
    monkeypatch.setattr(logging_config, "LOG_DIR", tmp_path)

    logging_config.setup_logging()

    assert len(_console_handlers(clean_inreach_logger)) == 1
    assert len(_file_handlers(clean_inreach_logger)) == 1


def test_fill_resolved_env_defaults_fills_blank_and_missing_keys(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("USER_WIN_NAME=\nLOG_DIR=\n", encoding="utf-8")

    logging_config.fill_resolved_env_defaults(
        env_path,
        {"LOG_DIR": "C:\\logs", "LOG_FILE": "C:\\logs\\inreach.log", "LOG_LEVEL": "INFO", "OUTPUT_TO_STREAM": "false"},
    )

    values = {
        line.split("=", 1)[0]: line.split("=", 1)[1].strip("'\"")
        for line in env_path.read_text(encoding="utf-8").splitlines()
        if "=" in line
    }
    assert values["USER_WIN_NAME"] == ""
    assert values["LOG_DIR"] == "C:\\logs"
    assert values["LOG_FILE"] == "C:\\logs\\inreach.log"
    assert values["LOG_LEVEL"] == "INFO"
    assert values["OUTPUT_TO_STREAM"] == "false"


def test_fill_resolved_env_defaults_leaves_existing_values_untouched(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("LOG_LEVEL=DEBUG\nOUTPUT_TO_STREAM=true\n", encoding="utf-8")

    logging_config.fill_resolved_env_defaults(
        env_path,
        {"LOG_DIR": "C:\\logs", "LOG_FILE": "C:\\logs\\inreach.log", "LOG_LEVEL": "INFO", "OUTPUT_TO_STREAM": "false"},
    )

    text = env_path.read_text(encoding="utf-8")
    assert "LOG_LEVEL=DEBUG" in text
    assert "OUTPUT_TO_STREAM=true" in text
    assert "LOG_DIR='C:\\logs'" in text
    assert "LOG_FILE='C:\\logs\\inreach.log'" in text


def test_fill_resolved_env_defaults_noop_when_file_missing(tmp_path):
    env_path = tmp_path / ".env"

    logging_config.fill_resolved_env_defaults(env_path, {"LOG_DIR": "C:\\logs"})

    assert not env_path.exists()
