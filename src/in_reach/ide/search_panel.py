"""The primary sidebar's Search view: project-wide find (and replace) across the currently open
gametype project's own folder (PROMPT.md).

Search re-runs live as the query changes -- a gametype project's own text files are few and small
(see :mod:`in_reach.app.project_search`'s own docstring), so there's no need for a debounce timer
or a background thread the way a search across a real codebase would need. "Replace All" is the one
destructive action here, and it can touch every matched file at once, so it always confirms first
(see :meth:`SearchPanel.ask_confirm_replace`) -- matching every other bulk/hard-to-reverse action
elsewhere in this IDE.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from in_reach.app import project_search

_NO_PROJECT_TEXT = "No project opened yet -- create or load one from the Welcome tab."


class SearchPanel(QWidget):
    #: Emitted with a match's path and 1-based line number when a result is activated
    #: (double-clicked, or Enter).
    file_activated = pyqtSignal(Path, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project_folder: Path | None = None
        self._matches: list[project_search.SearchMatch] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search")
        self.search_edit.textChanged.connect(self._run_search)
        layout.addWidget(self.search_edit)

        replace_row = QHBoxLayout()
        replace_row.setSpacing(6)
        self.replace_edit = QLineEdit()
        self.replace_edit.setPlaceholderText("Replace")
        replace_row.addWidget(self.replace_edit, 1)
        self.replace_all_button = QPushButton("Replace All")
        self.replace_all_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.replace_all_button.clicked.connect(self.replace_all)
        replace_row.addWidget(self.replace_all_button)
        layout.addLayout(replace_row)

        self.status_label = QLabel(_NO_PROJECT_TEXT)
        self.status_label.setWordWrap(True)
        self.status_label.setEnabled(False)
        layout.addWidget(self.status_label)

        self.results_list = QListWidget()
        self.results_list.itemActivated.connect(self._on_item_activated)
        layout.addWidget(self.results_list, 1)

        self._sync_enabled()

    # -- project wiring ---------------------------------------------------------------------------

    def set_project_folder(self, folder: Path | None) -> None:
        """Points this panel at ``folder`` (the current gametype project's own folder) -- or back
        to the "no project" state for ``None``, same as the Explorer panel's own
        :meth:`~in_reach.ide.explorer.ExplorerPanel.set_project_folder`."""
        self._project_folder = folder
        self._sync_enabled()
        self._run_search()

    def _sync_enabled(self) -> None:
        has_project = self._project_folder is not None
        for widget in (self.search_edit, self.replace_edit, self.replace_all_button, self.results_list):
            widget.setEnabled(has_project)
        if not has_project:
            self.status_label.setText(_NO_PROJECT_TEXT)

    # -- search -----------------------------------------------------------------------------------

    def _run_search(self) -> None:
        query = self.search_edit.text()
        self.results_list.clear()
        if self._project_folder is None or not query:
            self._matches = []
            self.status_label.setText("" if self._project_folder is not None else _NO_PROJECT_TEXT)
            return

        self._matches = project_search.search_project(self._project_folder, query)
        for match in self._matches:
            try:
                relative = match.path.relative_to(self._project_folder)
            except ValueError:
                relative = match.path
            item = QListWidgetItem(f"{relative}:{match.line_number}  {match.line_text.strip()}")
            self.results_list.addItem(item)

        count = len(self._matches)
        self.status_label.setText(f"{count} result{'s' if count != 1 else ''}")

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        index = self.results_list.row(item)
        if 0 <= index < len(self._matches):
            match = self._matches[index]
            self.file_activated.emit(match.path, match.line_number)

    # -- replace ----------------------------------------------------------------------------------

    def replace_all(self) -> None:
        query = self.search_edit.text()
        if self._project_folder is None or not query or not self._matches:
            return
        if not self.ask_confirm_replace(len(self._matches)):
            return
        project_search.replace_in_project(self._project_folder, query, self.replace_edit.text())
        self._run_search()

    def ask_confirm_replace(self, match_count: int) -> bool:
        """Kept as its own method purely as a test seam (see ``tabs.py``'s ``_ask_save_path``)."""
        result = QMessageBox.question(
            self,
            "in-reach",
            f"Replace {match_count} occurrence{'s' if match_count != 1 else ''} across the project?"
            " This changes files on disk and can't be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return result == QMessageBox.StandardButton.Yes
