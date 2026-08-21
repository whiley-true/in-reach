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
