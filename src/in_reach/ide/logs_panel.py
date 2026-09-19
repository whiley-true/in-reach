"""The bottom panel's "Logs" tab (PROMPT.md: "in the bottom panel please make the first tab logs
... please make this a fully fledged logs feature and have all actions log here") -- a live,
read-only view over every record the app's own logger (:mod:`in_reach.app.logging_setup`) emits,
not just whatever ``LOG_FILE`` happens to be configured to write to disk.

A single process-wide :class:`_LogBridge`/:class:`_BridgeLogHandler` pair is attached to the
``"in_reach"`` logger exactly once (:func:`_ensure_handler_attached`), rather than one
``logging.Handler`` per :class:`LogsPanel` instance -- a raw Python handler would outlive whichever
Qt widget it was built for the moment that widget gets destroyed (this app constructs/tears down a
lot of ``MainWindow``s over a test session), leaving a dangling reference that crashes the *next*
log call anywhere in the process. Routing every record through one long-lived ``QObject``'s signal
instead means each panel just connects/disconnects like any other Qt signal -- Qt itself already
guarantees a connection is severed the moment its receiver is destroyed, so there's nothing here to
manually clean up.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

from in_reach.app.logging_setup import LOG_FORMAT, LOGGER_NAME

#: How many lines this live view keeps on screen -- independent of (and typically larger than)
#: LOG_LINES, which caps the on-disk file instead; this is purely a "don't let the widget's own
#: document grow forever" ceiling, not a retention policy.
_MAX_DISPLAYED_LINES = 5000
_TRIM_TO_LINES = 4000


class _LogBridge(QObject):
    record_formatted = pyqtSignal(str)


_bridge = _LogBridge()


class _BridgeLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:  # noqa: BLE001 -- logging.Handler's own documented emit() contract
            self.handleError(record)
            return
        # A plain signal emit, never touching a widget directly -- safe to call from any thread
        # (PyQt marshals it onto the connected slot's own thread automatically), and never itself
        # holds a reference to any one panel -- see this module's own docstring.
        _bridge.record_formatted.emit(message)


_handler = _BridgeLogHandler()
_handler.setFormatter(logging.Formatter(LOG_FORMAT))


def _ensure_handler_attached() -> None:
    """Idempotent -- ``configure_logging()`` (:mod:`in_reach.app.logging_setup`) clears and rebuilds
    every handler on the ``"in_reach"`` logger on every call, so this re-attaches the bridge handler
    if it's ever been dropped, rather than assuming a one-time setup at import time is enough."""
    logger = logging.getLogger(LOGGER_NAME)
    if _handler not in logger.handlers:
        logger.addHandler(_handler)


class LogsPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _ensure_handler_attached()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(_MAX_DISPLAYED_LINES)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.view)

        _bridge.record_formatted.connect(self._append_line)

    def _append_line(self, line: str) -> None:
        # setMaximumBlockCount() above already caps the document itself (Qt trims from the top
        # automatically past that many blocks) -- appendPlainText() is still the right call rather
        # than rebuilding the whole document text on every record, so a busy session doesn't pay
        # an ever-growing string-join cost per line.
        at_bottom = self._is_scrolled_to_bottom()
        self.view.appendPlainText(line)
        if at_bottom:
            self._scroll_to_bottom()

    def _is_scrolled_to_bottom(self) -> bool:
        bar = self.view.verticalScrollBar()
        return bar.value() >= bar.maximum() - 1

    def _scroll_to_bottom(self) -> None:
        cursor = self.view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.view.setTextCursor(cursor)

    def clear(self) -> None:
        self.view.clear()
