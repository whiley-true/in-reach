"""The primary-sidebar VCS panel behind the activity bar's git icon (PROMPT.md: "vcs panel and
dulwich implementation"; a later pass: "we also want our vcs functionality to better match vscode
functionality").

A thin view over :mod:`in_reach.app.vcs` -- this panel never calls that module directly. Every user
action (commit, stamp a release, create a branch, switch branches) is emitted as a request signal
instead, same convention as :class:`~in_reach.ide.activity_bar.ActivityBar`'s own
``launch_rvt_requested``/``apply_requested``. ``MainWindow`` is the integration point that actually
calls :mod:`in_reach.app.vcs`, because switching branches can overwrite/delete real files on disk and
needs to coordinate with whatever's currently open in the editor (reload clean tabs, warn about dirty
ones, and now -- PROMPT.md's own VSCode-style pass -- warn about *uncommitted* ones too) -- exactly
the kind of cross-cutting concern this panel has no business knowing about.

PROMPT.md (the VSCode-style pass): "we want to add committed changes and uncommitted changes[;]
when there are uncommitted changes in the repo there should be a notification icon with the number
of uncommitted changes[;] committing changes should require a commit message[;] we want to remove
the autosave entries in vcs history panel[;] we also want to show a git graph of commits, branches
and stamps instead in vscode style" -- this panel now has a live "Changes" section (an uncommitted
file list plus an inline commit-message box, see :attr:`commit_requested`) above the existing "Stamp
Release" button (kept as a *separate* action from an ordinary commit -- a stamp still explicitly
marks a release, not just "a commit with a message"), and the old flat history ``QListWidget`` is
replaced by :class:`~in_reach.ide.git_graph.GitGraphWidget`, a real lane-painted commit graph across
every branch at once.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from in_reach.app import vcs
from in_reach.ide.git_graph import GitGraphWidget

_NO_HISTORY_TEXT = "This project has no history yet."
_STAMP_LABEL_PREFIX = "Stamp: "
_CHANGE_TYPE_PREFIX = {"added": "+", "removed": "-", "modified": "M"}


class GitPanel(QWidget):
    #: Emitted with the user's typed message when "Commit" is confirmed (PROMPT.md: "committing
    #: changes should require a commit message") -- the everyday checkpoint action, distinct from
    #: :attr:`stamp_requested` below.
    commit_requested = pyqtSignal(str)
    #: Emitted with the user's typed message when "Stamp Release" is confirmed.
    stamp_requested = pyqtSignal(str)
    #: Emitted with the user's typed name when "New Branch" is confirmed.
    new_branch_requested = pyqtSignal(str)
    #: Emitted with the newly picked branch name when the branch combo's selection changes to a
    #: branch other than the currently checked-out one.
    switch_branch_requested = pyqtSignal(str)
    #: Emitted with a branch name when "Delete Branch" is confirmed.
    delete_branch_requested = pyqtSignal(str)
    #: Emitted with ``(ref_a, ref_b)`` -- each either a branch name or a stamp's sha -- when
    #: "Compare" is clicked (PROMPT.md: "view branch differences[; and] compare different stamped
    #: versions").
    compare_requested = pyqtSignal(str, str)
    #: Emitted with a snapshot's sha when "Restore" is clicked for a selected graph row
    #: (PROMPT.md: "add any other functionality you think may help the user manage the project").
    restore_requested = pyqtSignal(str)
    #: Emitted with a project-relative path when a file is clicked in the "Changes" list --
    #: PROMPT.md: "when clicking on changes to a file (in the changes tab) a tab should appear
    #: showing the original on the left and highlighted changes on the right (like vscode git)".
    diff_file_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        #: The active gametype project's folder -- ``None`` with no project open. Mirrors
        #: ``ExplorerPanel.current_folder``'s own naming.
        self.current_folder: Path | None = None
        #: How many files are currently uncommitted -- what the activity bar's own badge (see
        #: ``MainWindow._refresh_vcs_status``) mirrors next to the git icon. Kept as a plain
        #: attribute (not re-derived by callers) so the panel and the badge can never briefly
        #: disagree between one ``vcs.uncommitted_changes()`` call and the next.
        self.uncommitted_count = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        branch_row = QHBoxLayout()
        branch_row.setContentsMargins(0, 0, 0, 0)
        self.branch_combo = QComboBox()
        # Guards _on_branch_combo_changed against firing (and re-requesting a switch to the branch
        # already checked out) while refresh() repopulates the combo's own items.
        self._suppress_branch_signal = False
        self.branch_combo.currentTextChanged.connect(self._on_branch_combo_changed)
        branch_row.addWidget(self.branch_combo, 1)
        self.new_branch_button = QPushButton("New Branch")
        self.new_branch_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_branch_button.clicked.connect(self._on_new_branch_clicked)
        branch_row.addWidget(self.new_branch_button)
        self.delete_branch_button = QPushButton("Delete Branch")
        self.delete_branch_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_branch_button.clicked.connect(self._on_delete_branch_clicked)
        branch_row.addWidget(self.delete_branch_button)
        layout.addLayout(branch_row)

        divider0 = QFrame()
        divider0.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(divider0)

        # -- "Changes" -- uncommitted files + inline commit box (PROMPT.md: "add committed changes
        # and uncommitted changes ... committing changes should require a commit message") --------
        self.changes_label = QLabel("Changes")
        layout.addWidget(self.changes_label)
        self.changes_list = QListWidget()
        self.changes_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.changes_list.setMaximumHeight(120)
        self.changes_list.setCursor(Qt.CursorShape.PointingHandCursor)
        self.changes_list.itemClicked.connect(self._on_change_clicked)
        layout.addWidget(self.changes_list)
        commit_row = QHBoxLayout()
        commit_row.setContentsMargins(0, 0, 0, 0)
        self.commit_message_edit = QLineEdit()
        self.commit_message_edit.setPlaceholderText("Commit message")
        self.commit_message_edit.returnPressed.connect(self._on_commit_clicked)
        self.commit_message_edit.textChanged.connect(self._update_commit_enabled)
        commit_row.addWidget(self.commit_message_edit, 1)
        self.commit_button = QPushButton("Commit")
        self.commit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.commit_button.setEnabled(False)
        self.commit_button.clicked.connect(self._on_commit_clicked)
        commit_row.addWidget(self.commit_button)
        layout.addLayout(commit_row)

        self.stamp_button = QPushButton("Stamp Release")
        self.stamp_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stamp_button.clicked.connect(self._on_stamp_clicked)
        layout.addWidget(self.stamp_button)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(divider)

        # PROMPT.md: "when a user clicks on version control[,] they should be able to view branch
        # differences[; and] compare different stamped versions" -- one pair of combos covering
        # both (each lists branches and stamps together) rather than two separate UIs, since a diff
        # between any two refs is the exact same operation either way (see vcs.diff).
        self.compare_label = QLabel("Compare")
        self.compare_label.setEnabled(False)
        layout.addWidget(self.compare_label)
        compare_row = QHBoxLayout()
        compare_row.setContentsMargins(0, 0, 0, 0)
        self.compare_a_combo = QComboBox()
        self.compare_b_combo = QComboBox()
        compare_row.addWidget(self.compare_a_combo, 1)
        compare_row.addWidget(QLabel("vs."))
        compare_row.addWidget(self.compare_b_combo, 1)
        layout.addLayout(compare_row)
        self.compare_button = QPushButton("Compare")
        self.compare_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.compare_button.clicked.connect(self._on_compare_clicked)
        layout.addWidget(self.compare_button)

        self.history_label = QLabel("History")
        self.history_label.setEnabled(False)
        layout.addWidget(self.history_label)
        self.graph = GitGraphWidget()
        self.graph.snapshot_selected.connect(self._on_graph_selection_changed)
        self._graph_scroll = QScrollArea()
        self._graph_scroll.setWidget(self.graph)
        self._graph_scroll.setWidgetResizable(False)
        self._graph_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        layout.addWidget(self._graph_scroll, 1)
        self.restore_button = QPushButton("Restore Selected")
        self.restore_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.restore_button.setEnabled(False)
        self.restore_button.clicked.connect(self._on_restore_clicked)
        layout.addWidget(self.restore_button)

        self._empty_label = QLabel(_NO_HISTORY_TEXT)
        self._empty_label.setWordWrap(True)
        self._empty_label.setEnabled(False)
        self._empty_label.hide()
        layout.addWidget(self._empty_label)

        self.set_project(None)

    # -- activation ---------------------------------------------------------------------------

    def set_project(self, folder: Path | None) -> None:
        """Points this panel at ``folder`` (the newly active project), or clears it for ``None`` --
        called by MainWindow whenever the active project changes, mirroring ``ExplorerPanel``'s own
        activation. Refreshes every displayed field immediately."""
        self.current_folder = folder
        self.refresh()

    def refresh(self) -> None:
        """Re-reads :attr:`current_folder`'s own branch list/current branch/uncommitted changes/
        graph from :mod:`in_reach.app.vcs` -- called on activation, and again by MainWindow after
        any action that changes history (commit, stamp, new branch, switch, restore) actually
        completes."""
        has_history = self.current_folder is not None and vcs.is_initialized(self.current_folder)
        self.branch_combo.setEnabled(has_history)
        self.new_branch_button.setEnabled(has_history)
        self.delete_branch_button.setEnabled(has_history)
        self.changes_label.setVisible(has_history)
        self.changes_list.setVisible(has_history)
        self.commit_message_edit.setEnabled(has_history)
        self.stamp_button.setEnabled(has_history)
        self.compare_label.setVisible(has_history)
        self.compare_a_combo.setEnabled(has_history)
        self.compare_b_combo.setEnabled(has_history)
        self.compare_button.setEnabled(has_history)
        self._graph_scroll.setVisible(has_history)
        self.history_label.setVisible(has_history)
        self.restore_button.setVisible(has_history)
        self._empty_label.setVisible(not has_history)

        self._suppress_branch_signal = True
        self.branch_combo.clear()
        branches: list[str] = []
        if has_history:
            branches = vcs.list_branches(self.current_folder)
            self.branch_combo.addItems(branches)
            current = vcs.current_branch(self.current_folder)
            if current is not None:
                self.branch_combo.setCurrentText(current)
        self._suppress_branch_signal = False

        uncommitted = vcs.uncommitted_changes(self.current_folder) if has_history else []
        self.uncommitted_count = len(uncommitted)
        self.changes_label.setText(f"Changes ({len(uncommitted)})")
        self.changes_list.clear()
        for change in uncommitted:
            prefix = _CHANGE_TYPE_PREFIX.get(change.change_type, "?")
            item_index = self.changes_list.count()
            self.changes_list.addItem(f"{prefix}  {change.path}")
            self.changes_list.item(item_index).setData(Qt.ItemDataRole.UserRole, change.path)
        self._update_commit_enabled()

        snapshots = vcs.graph_history(self.current_folder) if has_history else []
        self.graph.set_snapshots(snapshots)
        self.restore_button.setEnabled(False)

        for combo in (self.compare_a_combo, self.compare_b_combo):
            combo.clear()
            for branch in branches:
                combo.addItem(branch, branch)
            for snapshot in snapshots:
                if snapshot.is_stamp:
                    combo.addItem(f"{_STAMP_LABEL_PREFIX}{snapshot.stamp_message}", snapshot.sha)
        if self.compare_a_combo.count() > 1:
            self.compare_b_combo.setCurrentIndex(1)

    # -- user actions ---------------------------------------------------------------------------

    def _on_change_clicked(self, item) -> None:  # noqa: ANN001 -- QListWidgetItem
        rel_path = item.data(Qt.ItemDataRole.UserRole)
        if rel_path:
            self.diff_file_requested.emit(rel_path)

    def _update_commit_enabled(self) -> None:
        has_message = bool(self.commit_message_edit.text().strip())
        self.commit_button.setEnabled(self.uncommitted_count > 0 and has_message)

    def _on_commit_clicked(self) -> None:
        message = self.commit_message_edit.text().strip()
        if message and self.uncommitted_count > 0:
            self.commit_requested.emit(message)

    def clear_commit_message(self) -> None:
        """Called by MainWindow right after a successful commit -- the message box shouldn't carry
        the just-committed text forward into whatever gets typed next."""
        self.commit_message_edit.clear()

    def _on_stamp_clicked(self) -> None:
        message = self._ask_text("Stamp Release", "Commit message:")
        if message:
            self.stamp_requested.emit(message)

    def _on_new_branch_clicked(self) -> None:
        name = self._ask_text("New Branch", "Branch name:")
        if name:
            self.new_branch_requested.emit(name)

    def _on_delete_branch_clicked(self) -> None:
        name = self.branch_combo.currentText()
        if name:
            self.delete_branch_requested.emit(name)

    def _on_branch_combo_changed(self, name: str) -> None:
        if self._suppress_branch_signal or not name or self.current_folder is None:
            return
        if name != vcs.current_branch(self.current_folder):
            self.switch_branch_requested.emit(name)

    def _on_compare_clicked(self) -> None:
        ref_a = self.compare_a_combo.currentData()
        ref_b = self.compare_b_combo.currentData()
        if ref_a and ref_b:
            self.compare_requested.emit(ref_a, ref_b)

    def _on_graph_selection_changed(self, sha: str) -> None:
        self.restore_button.setEnabled(bool(sha))

    def _on_restore_clicked(self) -> None:
        sha = self.graph.selected_sha()
        if sha:
            self.restore_requested.emit(sha)

    def _ask_text(self, title: str, label: str) -> str:
        """Kept as its own method purely as a test seam -- same reasoning as ``MainWindow``'s own
        ``ask_open_folder``/``ask_export_path``."""
        from PyQt6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getText(self, title, label)
        return text.strip() if ok else ""
