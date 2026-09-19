"""The VCS panel's own diff viewer (PROMPT.md: "they should be able to view branch differences[;
and] compare different stamped versions") -- a changed-file list on the left, the selected file's
diff on the right, same master-detail shape as any plain git GUI's own diff view.

PROMPT.md (a later pass): "please then add text colourings and line numbers in the compare window
to make the text and changes clearer and more visually appealing" -- the selected file's own diff is
now a real :class:`~in_reach.ide.diff_view.DiffViewWidget` (line-numbered, JSON-syntax-highlighted,
red/green line coloring), the exact same widget the Changes tab's own "Open Changes" already opens
as a tab, just fed by :func:`~in_reach.app.vcs.ref_file_diff` (two committed refs) instead of
:func:`~in_reach.app.vcs.uncommitted_file_diff` (``HEAD`` vs. the live working tree) -- this replaced
the plain unified-diff-text ``QPlainTextEdit`` this dialog used to show instead.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QListWidget, QVBoxLayout, QWidget

from in_reach.app import vcs
from in_reach.app.vcs import FileDiff
from in_reach.ide.diff_view import DiffViewWidget

_CHANGE_PREFIX = {"added": "+ ", "removed": "- ", "modified": "M "}
_NO_DIFF_TEXT = "(no differences)"


class DiffDialog(QDialog):
    def __init__(
        self, parent: QWidget | None, *, title: str, folder: Path, ref_a: str, ref_b: str, diffs: list[FileDiff]
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 550)
        self._folder = folder
        self._ref_a = ref_a
        self._ref_b = ref_b
        self._diffs = diffs
        self._diff_view: DiffViewWidget | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(title))

        body = QHBoxLayout()
        self.file_list = QListWidget()
        self.file_list.setFixedWidth(240)
        for file_diff in diffs:
            self.file_list.addItem(f"{_CHANGE_PREFIX.get(file_diff.change_type, '')}{file_diff.path}")
        self.file_list.currentRowChanged.connect(self._show_diff)
        body.addWidget(self.file_list)

        self._diff_area = QVBoxLayout()
        self._diff_area.setContentsMargins(0, 0, 0, 0)
        self._empty_label = QLabel(_NO_DIFF_TEXT)
        self._empty_label.setEnabled(False)
        self._diff_area.addWidget(self._empty_label)
        body.addLayout(self._diff_area, 1)
        layout.addLayout(body, 1)

        if diffs:
            self.file_list.setCurrentRow(0)

    def _show_diff(self, row: int) -> None:
        if self._diff_view is not None:
            self._diff_area.removeWidget(self._diff_view)
            self._diff_view.deleteLater()
            self._diff_view = None
        self._empty_label.hide()

        if not (0 <= row < len(self._diffs)):
            self._empty_label.show()
            return
        file_diff = self._diffs[row]
        old_text, new_text = vcs.ref_file_diff(self._folder, self._ref_a, self._ref_b, file_diff.path)
        self._diff_view = DiffViewWidget(rel_path=file_diff.path, old_text=old_text, new_text=new_text)
        self._diff_area.addWidget(self._diff_view, 1)
