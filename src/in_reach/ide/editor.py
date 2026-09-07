"""Plain text-editor widget used for every open/Untitled tab in the main panel."""

from __future__ import annotations

from PyQt6.QtWidgets import QPlainTextEdit, QWidget


class TextEditorWidget(QPlainTextEdit):
    """One text-editor tab's content.

    Dirty tracking rides ``QTextDocument``'s own ``isModified()``/``modificationChanged`` --
    no extra state lives here. No syntax highlighting or file-type awareness yet.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
