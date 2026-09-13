"""The VCS panel's own diff viewer (PROMPT.md: "they should be able to view branch differences[;
and] compare different stamped versions") -- a changed-file list on the left, the selected file's
unified diff on the right, same master-detail shape as any plain git GUI's own diff view.
"""

from __future__ import annotations

from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QListWidget, QPlainTextEdit, QVBoxLayout, QWidget

from in_reach.app.vcs import FileDiff

_CHANGE_PREFIX = {"added": "+ ", "removed": "- ", "modified": "M "}
_NO_DIFF_TEXT = "(no differences)"


class DiffDialog(QDialog):
    def __init__(self, parent: QWidget | None, *, title: str, diffs: list[FileDiff]) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(800, 500)
        self._diffs = diffs

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(title))

        body = QHBoxLayout()
        self.file_list = QListWidget()
        self.file_list.setFixedWidth(240)
        for file_diff in diffs:
            self.file_list.addItem(f"{_CHANGE_PREFIX.get(file_diff.change_type, '')}{file_diff.path}")
        self.file_list.currentRowChanged.connect(self._show_diff)
        body.addWidget(self.file_list)

        self.diff_text = QPlainTextEdit()
        self.diff_text.setReadOnly(True)
        self.diff_text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        body.addWidget(self.diff_text, 1)
        layout.addLayout(body, 1)

        if diffs:
            self.file_list.setCurrentRow(0)
        else:
            self.diff_text.setPlainText(_NO_DIFF_TEXT)

    def _show_diff(self, row: int) -> None:
        if 0 <= row < len(self._diffs):
            self.diff_text.setPlainText(self._diffs[row].diff_text or _NO_DIFF_TEXT)
