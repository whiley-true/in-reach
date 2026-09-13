"""The primary-sidebar VCS panel behind the activity bar's git icon (PROMPT.md: "vcs panel and
dulwich implementation").

A thin view over :mod:`in_reach.app.vcs` -- this panel never calls that module directly. Every user
action (stamp a release, create a branch, switch branches) is emitted as a request signal instead,
same convention as :class:`~in_reach.ide.activity_bar.ActivityBar`'s own ``launch_rvt_requested``/
``apply_requested``. ``MainWindow`` is the integration point that actually calls :mod:`in_reach.app.
vcs`, because switching branches can overwrite/delete real files on disk and needs to coordinate
with whatever's currently open in the editor (reload clean tabs, warn about dirty ones) -- exactly
the kind of cross-cutting concern this panel has no business knowing about.
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
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from in_reach.app import vcs

_NO_HISTORY_TEXT = "This project has no history yet."
_STAMP_LABEL_PREFIX = "Stamp: "


class GitPanel(QWidget):
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
    #: Emitted with a snapshot's sha when "Restore" is clicked for a selected history entry
    #: (PROMPT.md: "add any other functionality you think may help the user manage the project").
    restore_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        #: The active gametype project's folder -- ``None`` with no project open. Mirrors
        #: ``ExplorerPanel.current_folder``'s own naming.
        self.current_folder: Path | None = None

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
        self.history_list = QListWidget()
        # A selectable single row (not the read-only NoSelection this started as) -- picking a past
        # snapshot is what "Restore" below acts on.
        self.history_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.history_list.currentRowChanged.connect(self._on_history_row_changed)
        layout.addWidget(self.history_list, 1)
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
        """Re-reads :attr:`current_folder`'s own branch list/current branch/history from
        :mod:`in_reach.app.vcs` -- called on activation, and again by MainWindow after any action
        that changes history (stamp, new branch, switch, restore) actually completes."""
        has_history = self.current_folder is not None and vcs.is_initialized(self.current_folder)
        self.branch_combo.setEnabled(has_history)
        self.new_branch_button.setEnabled(has_history)
        self.delete_branch_button.setEnabled(has_history)
        self.stamp_button.setEnabled(has_history)
        self.compare_label.setVisible(has_history)
        self.compare_a_combo.setEnabled(has_history)
        self.compare_b_combo.setEnabled(has_history)
        self.compare_button.setEnabled(has_history)
        self.history_list.setVisible(has_history)
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

        self.history_list.clear()
        snapshots = vcs.history(self.current_folder) if has_history else []
        for snapshot in snapshots:
            label = f"* {snapshot.stamp_message}" if snapshot.is_stamp else snapshot.message
            item_index = self.history_list.count()
            self.history_list.addItem(label)
            self.history_list.item(item_index).setData(Qt.ItemDataRole.UserRole, snapshot.sha)
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

    def _on_history_row_changed(self, row: int) -> None:
        self.restore_button.setEnabled(row >= 0)

    def _on_restore_clicked(self) -> None:
        item = self.history_list.currentItem()
        if item is not None:
            self.restore_requested.emit(item.data(Qt.ItemDataRole.UserRole))

    def _ask_text(self, title: str, label: str) -> str:
        """Kept as its own method purely as a test seam -- same reasoning as ``MainWindow``'s own
        ``ask_open_folder``/``ask_export_path``."""
        from PyQt6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getText(self, title, label)
        return text.strip() if ok else ""
