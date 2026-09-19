import logging

from in_reach.app.logging_setup import LOGGER_NAME
from in_reach.ide.logs_panel import LogsPanel, _bridge


def _logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    return logger


def test_logs_panel_shows_a_log_record_emitted_after_it_was_created(qtbot) -> None:
    panel = LogsPanel()
    qtbot.addWidget(panel)

    _logger().info("hello from the test")

    assert "hello from the test" in panel.view.toPlainText()


def test_logs_panel_is_read_only(qtbot) -> None:
    panel = LogsPanel()
    qtbot.addWidget(panel)

    assert panel.view.isReadOnly() is True


def test_multiple_panels_all_receive_the_same_record(qtbot) -> None:
    first = LogsPanel()
    second = LogsPanel()
    qtbot.addWidget(first)
    qtbot.addWidget(second)

    _logger().warning("broadcast message")

    assert "broadcast message" in first.view.toPlainText()
    assert "broadcast message" in second.view.toPlainText()


def test_a_panel_created_later_does_not_see_earlier_records(qtbot) -> None:
    first = LogsPanel()
    qtbot.addWidget(first)
    _logger().info("before second panel exists")

    second = LogsPanel()
    qtbot.addWidget(second)

    assert "before second panel exists" not in second.view.toPlainText()


def test_a_destroyed_panel_does_not_crash_a_later_log_call(qtbot) -> None:
    # Regression guard: a raw logging.Handler attached per-panel would leave a dangling reference
    # once the panel it was built for is destroyed, crashing the *next* log call anywhere in the
    # process -- see logs_panel.py's own module docstring for why a single process-wide bridge is
    # used instead. Deleting the panel here (rather than just letting qtbot GC it at test end)
    # exercises that Qt itself severs the signal connection safely.
    panel = LogsPanel()
    qtbot.addWidget(panel)
    panel.deleteLater()
    qtbot.wait(10)

    _logger().info("no crash please")  # would raise/print an error if a dangling ref remained


def test_clear_empties_the_view(qtbot) -> None:
    panel = LogsPanel()
    qtbot.addWidget(panel)
    _logger().info("something")
    assert panel.view.toPlainText() != ""

    panel.clear()

    assert panel.view.toPlainText() == ""


def test_only_one_handler_instance_is_ever_attached(qtbot) -> None:
    # _ensure_handler_attached() is called on every LogsPanel construction -- must stay a no-op
    # once the bridge handler is already there, or every panel built over a session would add
    # another duplicate handler, multiplying every subsequent log line.
    LogsPanel()
    LogsPanel()
    LogsPanel()

    logger = logging.getLogger(LOGGER_NAME)
    from in_reach.ide.logs_panel import _handler

    assert logger.handlers.count(_handler) == 1


def test_bridge_signal_carries_a_formatted_record(qtbot) -> None:
    received = []
    _bridge.record_formatted.connect(received.append)

    _logger().error("formatted please")

    assert any("formatted please" in line and "ERROR" in line for line in received)
