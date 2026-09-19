"""The primary sidebar's Search view: project-wide find (and replace) across the currently open
gametype project's own folder (PROMPT.md).

Laid out after VSCode's own Search view (PROMPT.md: "see search.png"): a query box with Match Case/
Match Whole Word/Use Regular Expression toggles docked inside its right edge; a chevron beside it
that reveals the replace row (a replacement box with a Preserve Case toggle, plus Replace All); and
a "..." toggle that reveals "files to include" (whose own inline toggle is "Search only in Open
Editors") and "files to exclude", each with placeholder text demonstrating the glob syntax
:mod:`in_reach.app.project_search` accepts.

Search re-runs live as any of that changes -- a gametype project's own text files are few and small
(see :mod:`in_reach.app.project_search`'s own docstring), so there's no need for a debounce timer
or a background thread the way a search across a real codebase would need. "Replace All" is the one
destructive action here, and it can touch every matched file at once, so it always confirms first
(see :meth:`SearchPanel.ask_confirm_replace`) -- matching every other bulk/hard-to-reverse action
elsewhere in this IDE.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from in_reach.app import project_search
from in_reach.ide import icons
from in_reach.ide.find_replace import toggle_button

_NO_PROJECT_TEXT = "No project opened yet -- create or load one from the Welcome tab."
_INVALID_REGEX_TEXT = "Invalid regular expression."

#: PROMPT.md: "files to include ... and files to exclude (both of which should have placeholder
#: temporary text of eg. *json, src/a/file demonstrating the search functions available)".
PATH_PLACEHOLDER = "e.g. *.json, src/a/file"

_OPEN_EDITORS_ICON_SIZE = 14


class _OptionLineEdit(QLineEdit):
    """A :class:`QLineEdit` with toggle buttons docked inside its own right edge (VSCode's Search
    view puts Match Case/Whole Word/Regex inside the query box, not beside it). The text is kept
    clear of them via :meth:`setTextMargins`, recomputed whenever the box (or its font, on a zoom
    change) resizes, since the buttons' own width follows the font."""

    def __init__(self, buttons: Iterable[QToolButton], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._buttons = list(buttons)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 3, 0)
        layout.setSpacing(1)
        layout.addStretch(1)
        for button in self._buttons:
            layout.addWidget(button)
        self._sync_text_margins()

    def _sync_text_margins(self) -> None:
        width = sum(button.sizeHint().width() + 1 for button in self._buttons)
        self.setTextMargins(0, 0, width + 4, 0)

    def resizeEvent(self, event) -> None:  # noqa: ANN001 -- QResizeEvent
        super().resizeEvent(event)
        self._sync_text_margins()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._sync_text_margins()


class SearchPanel(QWidget):
    #: Emitted with a match's path and 1-based line number when a result is activated
    #: (double-clicked, or Enter).
    file_activated = pyqtSignal(Path, int)

    #: "same for search relaces texts [make 10% smaller]" -- relative to the app's own current
    #: zoom-scaled font, same mechanism as :attr:`~in_reach.ide.explorer.ExplorerPanel.TEXT_SCALE`
    #: (see :meth:`refresh_font_scale`), just shrinking instead of growing.
    TEXT_SCALE = 0.9

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project_folder: Path | None = None
        self._matches: list[project_search.SearchMatch] = []
        #: Supplies the paths currently open in editor tabs, for "Search only in Open Editors" --
        #: wired up by MainWindow (see :meth:`set_open_paths_provider`).
        self._open_paths_provider: Callable[[], Iterable[Path]] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # -- query + replace -----------------------------------------------------------------------
        fields_row = QHBoxLayout()
        fields_row.setSpacing(4)

        # PROMPT.md: "we want a drop down arrow for replace (like our in editor search and replace)"
        # -- same chevron the editor's own FindReplaceBar uses, leftmost, toggling the replace row.
        self.expand_replace_button = QToolButton()
        self.expand_replace_button.setCheckable(True)
        self.expand_replace_button.setAutoRaise(True)
        self.expand_replace_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.expand_replace_button.setToolTip("Toggle Replace")
        self.expand_replace_button.setArrowType(Qt.ArrowType.RightArrow)
        self.expand_replace_button.toggled.connect(self.set_replace_visible)
        fields_row.addWidget(self.expand_replace_button, 0, Qt.AlignmentFlag.AlignTop)

        fields = QVBoxLayout()
        fields.setSpacing(4)

        self.match_case_button = toggle_button("Aa", "Match Case")
        self.whole_word_button = toggle_button("ab", "Match Whole Word")
        self.regex_button = toggle_button(".*", "Use Regular Expression")
        self.search_edit = _OptionLineEdit([self.match_case_button, self.whole_word_button, self.regex_button])
        self.search_edit.setPlaceholderText("Search")
        self.search_edit.textChanged.connect(self._run_search)
        for button in (self.match_case_button, self.whole_word_button, self.regex_button):
            button.toggled.connect(self._run_search)
        fields.addWidget(self.search_edit)

        self._replace_row = QWidget()
        replace_layout = QHBoxLayout(self._replace_row)
        replace_layout.setContentsMargins(0, 0, 0, 0)
        replace_layout.setSpacing(6)
        self.preserve_case_button = toggle_button("AB", "Preserve Case")
        self.replace_edit = _OptionLineEdit([self.preserve_case_button])
        self.replace_edit.setPlaceholderText("Replace")
        replace_layout.addWidget(self.replace_edit, 1)
        self.replace_all_button = QPushButton("Replace All")
        self.replace_all_button.setToolTip("Replace All")
        self.replace_all_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.replace_all_button.clicked.connect(self.replace_all)
        replace_layout.addWidget(self.replace_all_button)
        fields.addWidget(self._replace_row)
        self._replace_row.hide()

        fields_row.addLayout(fields, 1)
        layout.addLayout(fields_row)

        # -- search details (files to include/exclude) --------------------------------------------
        # PROMPT.md: "a toggle for search options which reveals files to include (including an
        # option for Search only in Open Editors) and files to exclude".
        details_toggle_row = QHBoxLayout()
        details_toggle_row.addStretch(1)
        self.details_button = QToolButton()
        self.details_button.setText("...")
        self.details_button.setCheckable(True)
        self.details_button.setAutoRaise(True)
        self.details_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.details_button.setToolTip("Toggle Search Details")
        self.details_button.toggled.connect(self.set_details_visible)
        details_toggle_row.addWidget(self.details_button)
        layout.addLayout(details_toggle_row)

        self._details = QWidget()
        details_layout = QVBoxLayout(self._details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(4)

        details_layout.addWidget(QLabel("files to include"))
        self.only_open_editors_button = toggle_button("", "Search only in Open Editors")
        self._refresh_open_editors_icon()
        self.include_edit = _OptionLineEdit([self.only_open_editors_button])
        self.include_edit.setPlaceholderText(PATH_PLACEHOLDER)
        self.include_edit.textChanged.connect(self._run_search)
        self.only_open_editors_button.toggled.connect(self._run_search)
        details_layout.addWidget(self.include_edit)

        details_layout.addWidget(QLabel("files to exclude"))
        self.exclude_edit = QLineEdit()
        self.exclude_edit.setPlaceholderText(PATH_PLACEHOLDER)
        self.exclude_edit.textChanged.connect(self._run_search)
        details_layout.addWidget(self.exclude_edit)

        layout.addWidget(self._details)
        self._details.hide()

        self.status_label = QLabel(_NO_PROJECT_TEXT)
        self.status_label.setWordWrap(True)
        self.status_label.setEnabled(False)
        layout.addWidget(self.status_label)

        self.results_list = QListWidget()
        self.results_list.itemActivated.connect(self._on_item_activated)
        layout.addWidget(self.results_list, 1)

        self._sync_enabled()
        self.refresh_font_scale()

    def refresh_font_scale(self) -> None:
        """(Re-)applies :data:`TEXT_SCALE` on top of the app's current font -- same mechanism (and
        same caveat: a one-time snapshot, not a live binding) as
        :meth:`in_reach.ide.explorer.ExplorerPanel.refresh_font_scale`; call again after a zoom
        change."""
        app = QApplication.instance()
        if app is None:
            return
        font = QFont(app.font())
        font.setPointSizeF(font.pointSizeF() * self.TEXT_SCALE)
        self.setFont(font)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            # The open-editors toggle carries an icon rendered in the palette's own text colour;
            # re-render it so it follows a theme switch instead of keeping the old theme's colour.
            self._refresh_open_editors_icon()

    def _refresh_open_editors_icon(self) -> None:
        color = self.palette().color(QPalette.ColorRole.Text).name()
        self.only_open_editors_button.setIcon(
            icons.icon("split", color=color, size=_OPEN_EDITORS_ICON_SIZE)
        )

    # -- toggles ----------------------------------------------------------------------------------

    def set_replace_visible(self, visible: bool) -> None:
        self._replace_row.setVisible(visible)
        self.expand_replace_button.blockSignals(True)
        self.expand_replace_button.setChecked(visible)
        self.expand_replace_button.blockSignals(False)
        self.expand_replace_button.setArrowType(Qt.ArrowType.DownArrow if visible else Qt.ArrowType.RightArrow)

    def set_details_visible(self, visible: bool) -> None:
        self._details.setVisible(visible)
        self.details_button.blockSignals(True)
        self.details_button.setChecked(visible)
        self.details_button.blockSignals(False)

    # -- project wiring ---------------------------------------------------------------------------

    def set_project_folder(self, folder: Path | None) -> None:
        """Points this panel at ``folder`` (the current gametype project's own folder) -- or back
        to the "no project" state for ``None``, same as the Explorer panel's own
        :meth:`~in_reach.ide.explorer.ExplorerPanel.set_project_folder`."""
        self._project_folder = folder
        self._sync_enabled()
        self._run_search()

    def set_open_paths_provider(self, provider: Callable[[], Iterable[Path]] | None) -> None:
        """Where "Search only in Open Editors" gets its file list from -- called fresh on every
        search, so it always reflects whichever tabs are open right now."""
        self._open_paths_provider = provider

    def _sync_enabled(self) -> None:
        has_project = self._project_folder is not None
        for widget in (
            self.search_edit,
            self.replace_edit,
            self.replace_all_button,
            self.results_list,
            self.include_edit,
            self.exclude_edit,
            self.match_case_button,
            self.whole_word_button,
            self.regex_button,
            self.preserve_case_button,
            self.only_open_editors_button,
        ):
            widget.setEnabled(has_project)
        if not has_project:
            self.status_label.setText(_NO_PROJECT_TEXT)

    # -- search -----------------------------------------------------------------------------------

    def _search_kwargs(self) -> dict:
        only_paths = None
        if self.only_open_editors_button.isChecked():
            only_paths = list(self._open_paths_provider()) if self._open_paths_provider else []
        return {
            "case_sensitive": self.match_case_button.isChecked(),
            "whole_word": self.whole_word_button.isChecked(),
            "regex": self.regex_button.isChecked(),
            "include": self.include_edit.text(),
            "exclude": self.exclude_edit.text(),
            "only_paths": only_paths,
        }

    def _run_search(self) -> None:
        query = self.search_edit.text()
        self.results_list.clear()
        if self._project_folder is None or not query:
            self._matches = []
            self.status_label.setText("" if self._project_folder is not None else _NO_PROJECT_TEXT)
            return

        kwargs = self._search_kwargs()
        if kwargs["regex"] and project_search.compile_search_pattern(
            query, match_case=True, whole_word=False, regex=True
        ) is None:
            self._matches = []
            self.status_label.setText(_INVALID_REGEX_TEXT)
            return

        self._matches = project_search.search_project(self._project_folder, query, **kwargs)
        for match in self._matches:
            try:
                relative = match.path.relative_to(self._project_folder)
            except ValueError:
                relative = match.path
            item = QListWidgetItem(f"{relative}:{match.line_number}  {match.line_text.strip()}")
            self.results_list.addItem(item)

        count = len(self._matches)
        files = len({match.path for match in self._matches})
        text = f"{count} result{'s' if count != 1 else ''} in {files} file{'s' if files != 1 else ''}"
        if kwargs["only_paths"] is not None:
            text += " -- searching only in open editors"
        self.status_label.setText(text)

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
        project_search.replace_in_project(
            self._project_folder,
            query,
            self.replace_edit.text(),
            keep_case=self.preserve_case_button.isChecked(),
            **self._search_kwargs(),
        )
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
