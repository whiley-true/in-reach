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
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QPushButton,
    QScrollArea,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from in_reach.app import vcs
from in_reach.ide.collapsible_section import CollapsibleSection
from in_reach.ide.git_graph import GitGraphWidget

_NO_HISTORY_TEXT = "This project has no history yet."
_STAMP_LABEL_PREFIX = "Stamp: "
_CHANGE_TYPE_PREFIX = {"added": "+", "removed": "-", "modified": "M"}
#: PROMPT.md: "where we have compare we need to add 2 drop downs above the left and right
#: comparison to allow the user to select between branch and stamp, which then populates the list
#: below it (to stop the dropdown being too long for containing all branches and stamps)".
_COMPARE_TYPE_BRANCH = "Branch"
_COMPARE_TYPE_STAMP = "Stamp"


class GitPanel(QWidget):
    #: Emitted with the user's typed message when "Commit" is confirmed (PROMPT.md: "committing
    #: changes should require a commit message") -- the everyday checkpoint action, distinct from
    #: :attr:`stamp_requested` below.
    commit_requested = pyqtSignal(str)
    #: Emitted with ``(message, version)`` when "Stamp Release" is confirmed -- ``version`` is
    #: always a ``"{major}.{minor}.{patch}"`` string (PROMPT.md: "we also want to add the
    #: functionality for version numbers using major, minor, patch with stamped releases").
    stamp_requested = pyqtSignal(str, str)
    #: Emitted with the user's typed name when "New Branch" is confirmed.
    new_branch_requested = pyqtSignal(str)
    #: Emitted with ``(name, source)`` when "New Branch From..." is confirmed -- ``source`` is
    #: either a branch name or a stamp's own sha, same convention as :attr:`compare_requested`
    #: (PROMPT.md: "please make new branch trigger a drop down also providing a New Branch from
    #: option").
    new_branch_from_requested = pyqtSignal(str, str)
    #: Emitted with the newly picked branch name when the branch combo's selection changes to a
    #: branch other than the currently checked-out one.
    switch_branch_requested = pyqtSignal(str)
    #: Emitted with a branch name when "Delete Branch" is confirmed.
    delete_branch_requested = pyqtSignal(str)
    #: Emitted with a source branch name when "Merge Branch" picks one to merge into whichever
    #: branch is currently checked out -- PROMPT.md, a later pass: "we also need buttons/
    #: functionality to: delete branch, merge branch (this will need History Graph update to show
    #: merging of branches)".
    merge_branch_requested = pyqtSignal(str)
    #: Emitted with ``(ref_a, ref_b)`` -- each either a branch name or a stamp's sha -- when
    #: "Compare" is clicked (PROMPT.md: "view branch differences[; and] compare different stamped
    #: versions").
    compare_requested = pyqtSignal(str, str)
    #: Emitted with a snapshot's sha when "Restore" is clicked for a selected graph row
    #: (PROMPT.md: "add any other functionality you think may help the user manage the project").
    restore_requested = pyqtSignal(str)
    #: Emitted with a project-relative path when a file is clicked in the "Changes" list, or "Open
    #: Changes" is picked from its context menu -- PROMPT.md: "when clicking on changes to a file
    #: (in the changes tab) a tab should appear showing the original on the left and highlighted
    #: changes on the right (like vscode git)".
    diff_file_requested = pyqtSignal(str)
    #: Emitted with a project-relative path when "Open File" is picked from the Changes context
    #: menu -- PROMPT.md: "in the changes it should be possible to right click the file and then
    #: see: Open changes, open files, open file (HEAD), discard changes, stage changes (or unstage
    #: changes), reveal in file explorer".
    open_file_requested = pyqtSignal(str)
    #: Emitted with a project-relative path when "Open File (HEAD)" is picked.
    open_file_head_requested = pyqtSignal(str)
    #: Emitted with a project-relative path when "Discard Changes" is picked.
    discard_requested = pyqtSignal(str)
    #: Emitted with a project-relative path when "Reveal in File Explorer" is picked.
    reveal_requested = pyqtSignal(str)
    #: Emitted with a list of project-relative paths when "Stage Changes"/"Stage All" is picked.
    stage_requested = pyqtSignal(list)
    #: Emitted with a list of project-relative paths when "Unstage Changes"/"Unstage All" is picked.
    unstage_requested = pyqtSignal(list)
    #: Emitted with a snapshot's sha when a graph row is selected -- PROMPT.md, a later pass:
    #: "please make it so that when clicking in history on commits - it extends to show a list of
    #: files changed". MainWindow answers by fetching that commit's own changed-file list and
    #: calling :meth:`set_commit_files` back.
    commit_selected = pyqtSignal(str)
    #: Emitted with ``(sha, rel_path)`` when a file is clicked in the "Files Changed" list --
    #: PROMPT.md: "(which can then be clicked on to view (please note this should be a single (not
    #: split) view, see sample.png for styling))".
    commit_diff_requested = pyqtSignal(str, str)
    #: Emitted with ``(sha, rel_path)`` when "Open File" is picked from the "Files Changed" list's
    #: own context menu -- PROMPT.md: "and right click should have the option to open file".
    commit_open_file_requested = pyqtSignal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        #: The active gametype project's folder -- ``None`` with no project open. Mirrors
        #: ``ExplorerPanel.current_folder``'s own naming.
        self.current_folder: Path | None = None
        #: How many files are currently uncommitted (staged + unstaged combined) -- what the
        #: activity bar's own badge (see ``MainWindow._refresh_vcs_status``) mirrors next to the
        #: git icon. Kept as a plain attribute (not re-derived by callers) so the panel and the
        #: badge can never briefly disagree between one ``vcs.uncommitted_changes()`` call and the
        #: next.
        self.uncommitted_count = 0
        #: How many of those are staged -- what :meth:`_update_commit_enabled` gates "Commit" on
        #: (PROMPT.md, a later pass: "changes should be staged, and then committed").
        self.staged_count = 0
        #: The graph's own currently-selected commit sha, if any -- what :meth:`set_commit_files`
        #: cross-checks a fetch against (see its own docstring) and the "Files Changed" list's own
        #: click/context-menu handlers act on.
        self._selected_commit_sha: str | None = None
        #: Whether the active project's ``settings/`` has already been compiled with no changes
        #: since (PROMPT.md: "it also should not be possible to stamp a non compiled gametype") --
        #: set by :meth:`set_stamp_enabled` (MainWindow calls it alongside the activity bar's own
        #: Apply-enabled state, see ``MainWindow._refresh_apply_enabled``), and combined with
        #: ``has_history`` inside :meth:`refresh` to decide whether :attr:`stamp_button` is
        #: actually clickable. Defaults to ``True`` so a panel nobody's ever called this on (most
        #: tests) doesn't spuriously disable stamping.
        self._compiled = True
        #: Mirrors :meth:`refresh`'s own ``has_history`` -- cached so :meth:`set_stamp_enabled` can
        #: recombine it with a fresh ``_compiled`` value without needing a full :meth:`refresh`.
        self._has_history = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # PROMPT.md: "please add section headings to the vcs sub panel to make it clearer" -- same
        # VSCode-style collapsible-header treatment the Dashboard already uses (see
        # in_reach.ide.collapsible_section, factored out of explorer.py for exactly this reuse).
        # Cached snapshot/branch lists (see refresh()) so the Compare type combos below can
        # re-populate their own ref combo without needing a full refresh() every time.
        self._branches: list[str] = []
        self._snapshots: list[vcs.Snapshot] = []

        branches_body = QWidget()
        branch_row = QHBoxLayout(branches_body)
        branch_row.setContentsMargins(0, 0, 0, 0)
        self.branch_combo = QComboBox()
        # Guards _on_branch_combo_changed against firing (and re-requesting a switch to the branch
        # already checked out) while refresh() repopulates the combo's own items.
        self._suppress_branch_signal = False
        self.branch_combo.currentTextChanged.connect(self._on_branch_combo_changed)
        branch_row.addWidget(self.branch_combo, 1)
        # PROMPT.md: "please make new branch trigger a drop down also providing a New Branch from
        # option (if not use present)" -- a dropdown (not a plain click) offering the original
        # "branch off whatever's currently checked out" behavior alongside a new "New Branch
        # From..." option that lets the user pick a specific source branch or stamp instead.
        self.new_branch_button = QToolButton()
        self.new_branch_button.setText("New Branch")
        self.new_branch_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_branch_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        new_branch_menu = QMenu(self.new_branch_button)
        new_branch_menu.addAction("New Branch", self._on_new_branch_clicked)
        new_branch_menu.addAction("New Branch From...", self._on_new_branch_from_clicked)
        self.new_branch_button.setMenu(new_branch_menu)
        branch_row.addWidget(self.new_branch_button)
        self.delete_branch_button = QPushButton("Delete Branch")
        self.delete_branch_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_branch_button.clicked.connect(self._on_delete_branch_clicked)
        branch_row.addWidget(self.delete_branch_button)
        self.merge_branch_button = QPushButton("Merge Branch")
        self.merge_branch_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.merge_branch_button.clicked.connect(self._on_merge_branch_clicked)
        branch_row.addWidget(self.merge_branch_button)
        self.branches_section = CollapsibleSection("Branches", branches_body, collapsed=False)
        layout.addWidget(self.branches_section)

        # -- "Changes" -- staged/unstaged files + inline commit box (PROMPT.md: "add committed
        # changes and uncommitted changes ... committing changes should require a commit message";
        # a later pass: "changes should be staged, and then committed") -- VSCode's own two-list
        # shape: "Staged Changes" (what the next Commit actually includes) above "Changes" (not yet
        # staged), each with its own right-click menu (see _build_change_context_menu) and a
        # Stage-All/Unstage-All button of its own.
        changes_body = QWidget()
        changes_layout = QVBoxLayout(changes_body)
        changes_layout.setContentsMargins(0, 0, 0, 0)

        staged_header = QHBoxLayout()
        staged_header.setContentsMargins(0, 0, 0, 0)
        self.staged_label = QLabel("Staged Changes (0)")
        staged_header.addWidget(self.staged_label, 1)
        self.unstage_all_button = QPushButton("Unstage All")
        self.unstage_all_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.unstage_all_button.clicked.connect(self._on_unstage_all_clicked)
        staged_header.addWidget(self.unstage_all_button)
        changes_layout.addLayout(staged_header)
        self.staged_list = QListWidget()
        self.staged_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.staged_list.setMaximumHeight(100)
        self.staged_list.setCursor(Qt.CursorShape.PointingHandCursor)
        self.staged_list.itemClicked.connect(self._on_change_clicked)
        self.staged_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.staged_list.customContextMenuRequested.connect(
            lambda pos: self._show_change_context_menu(self.staged_list, pos)
        )
        changes_layout.addWidget(self.staged_list)

        changes_header = QHBoxLayout()
        changes_header.setContentsMargins(0, 0, 0, 0)
        self.changes_label = QLabel("Changes (0)")
        changes_header.addWidget(self.changes_label, 1)
        self.stage_all_button = QPushButton("Stage All")
        self.stage_all_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stage_all_button.clicked.connect(self._on_stage_all_clicked)
        changes_header.addWidget(self.stage_all_button)
        changes_layout.addLayout(changes_header)
        self.changes_list = QListWidget()
        self.changes_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.changes_list.setMaximumHeight(100)
        self.changes_list.setCursor(Qt.CursorShape.PointingHandCursor)
        self.changes_list.itemClicked.connect(self._on_change_clicked)
        self.changes_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.changes_list.customContextMenuRequested.connect(
            lambda pos: self._show_change_context_menu(self.changes_list, pos)
        )
        changes_layout.addWidget(self.changes_list)

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
        changes_layout.addLayout(commit_row)
        self.changes_section = CollapsibleSection("Changes", changes_body, collapsed=False)
        layout.addWidget(self.changes_section)

        release_body = QWidget()
        release_layout = QVBoxLayout(release_body)
        release_layout.setContentsMargins(0, 0, 0, 0)
        self.stamp_button = QPushButton("Stamp Release")
        self.stamp_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stamp_button.clicked.connect(self._on_stamp_clicked)
        release_layout.addWidget(self.stamp_button)
        self.release_section = CollapsibleSection("Release", release_body, collapsed=False)
        layout.addWidget(self.release_section)

        # PROMPT.md: "when a user clicks on version control[,] they should be able to view branch
        # differences[; and] compare different stamped versions" -- a type combo (Branch/Stamp)
        # above each side's own ref combo, PROMPT.md (a later pass): "we need to add 2 drop downs
        # above the left and right comparison to allow the user to select between branch and stamp,
        # which then populates the list below it (to stop the dropdown being too long for
        # containing all branches and stamps)" -- see _populate_compare_combo().
        compare_body = QWidget()
        compare_layout = QVBoxLayout(compare_body)
        compare_layout.setContentsMargins(0, 0, 0, 0)
        compare_type_row = QHBoxLayout()
        compare_type_row.setContentsMargins(0, 0, 0, 0)
        self.compare_a_type_combo = QComboBox()
        self.compare_a_type_combo.addItems([_COMPARE_TYPE_BRANCH, _COMPARE_TYPE_STAMP])
        self.compare_a_type_combo.currentTextChanged.connect(
            lambda type_name: self._populate_compare_combo(self.compare_a_combo, type_name)
        )
        compare_type_row.addWidget(self.compare_a_type_combo, 1)
        self.compare_b_type_combo = QComboBox()
        self.compare_b_type_combo.addItems([_COMPARE_TYPE_BRANCH, _COMPARE_TYPE_STAMP])
        self.compare_b_type_combo.currentTextChanged.connect(
            lambda type_name: self._populate_compare_combo(self.compare_b_combo, type_name)
        )
        compare_type_row.addWidget(self.compare_b_type_combo, 1)
        compare_layout.addLayout(compare_type_row)
        compare_row = QHBoxLayout()
        compare_row.setContentsMargins(0, 0, 0, 0)
        self.compare_a_combo = QComboBox()
        self.compare_b_combo = QComboBox()
        compare_row.addWidget(self.compare_a_combo, 1)
        compare_row.addWidget(QLabel("vs."))
        compare_row.addWidget(self.compare_b_combo, 1)
        compare_layout.addLayout(compare_row)
        self.compare_button = QPushButton("Compare")
        self.compare_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.compare_button.clicked.connect(self._on_compare_clicked)
        compare_layout.addWidget(self.compare_button)
        self.compare_section = CollapsibleSection("Compare", compare_body, collapsed=False)
        layout.addWidget(self.compare_section)

        history_body = QWidget()
        history_layout = QVBoxLayout(history_body)
        history_layout.setContentsMargins(0, 0, 0, 0)
        self.graph = GitGraphWidget()
        self.graph.snapshot_selected.connect(self._on_graph_selection_changed)
        self._graph_scroll = QScrollArea()
        self._graph_scroll.setWidget(self.graph)
        # PROMPT.md: "history text is not always expanding with side panel" -- False here used to
        # pin the graph at its own fixed sizeHint() width forever, so widening the sidebar just left
        # blank space instead of giving the text column more room (see GitGraphWidget's own
        # paintEvent, which sizes/elides its text against self.width() -- whatever width the widget
        # actually ends up with). True lets a QScrollArea stretch its child up to fill a wider
        # viewport (never below the graph's own setMinimumWidth() -- see _update_geometry -- so a
        # graph with many lanes/long text still scrolls horizontally exactly as before).
        self._graph_scroll.setWidgetResizable(True)
        self._graph_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.restore_button = QPushButton("Restore Selected")
        self.restore_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.restore_button.setEnabled(False)
        self.restore_button.clicked.connect(self._on_restore_clicked)

        # PROMPT.md, a later pass: "please make it so that when clicking in history on commits - it
        # extends to show a list of files changed (which can then be clicked on to view (please
        # note this should be a single (not split) view, see sample.png for styling)) - and right
        # click should have the option to open file" -- populated via set_commit_files() once
        # MainWindow fetches the selected commit's own changed-file list (this panel never calls
        # in_reach.app.vcs directly, see this module's own docstring).
        self.commit_files_label = QLabel("Files Changed")
        self.commit_files_label.hide()
        self.commit_files_list = QListWidget()
        self.commit_files_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.commit_files_list.setCursor(Qt.CursorShape.PointingHandCursor)
        self.commit_files_list.itemClicked.connect(self._on_commit_file_clicked)
        self.commit_files_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.commit_files_list.customContextMenuRequested.connect(self._show_commit_file_context_menu)
        self.commit_files_list.hide()

        # PROMPT.md: "please also add a menu line divider under the restore button in vcs allowing
        # the menu to be dragged vertically up to reveal more of the files changed" -- the graph
        # (plus Restore Selected) sits above a draggable splitter handle from the Files Changed list
        # below it, in place of the fixed setMaximumHeight(120) the list used to be capped at, so
        # dragging that handle up hands the list more room instead of it just being clipped.
        graph_pane = QWidget()
        graph_pane_layout = QVBoxLayout(graph_pane)
        graph_pane_layout.setContentsMargins(0, 0, 0, 0)
        graph_pane_layout.addWidget(self._graph_scroll, 1)
        graph_pane_layout.addWidget(self.restore_button)

        self._files_pane = QWidget()
        files_pane_layout = QVBoxLayout(self._files_pane)
        files_pane_layout.setContentsMargins(0, 0, 0, 0)
        files_pane_layout.addWidget(self.commit_files_label)
        files_pane_layout.addWidget(self.commit_files_list, 1)
        self._files_pane.hide()  # no commit selected yet -- see refresh()/_on_graph_selection_changed

        self._history_splitter = QSplitter(Qt.Orientation.Vertical)
        self._history_splitter.addWidget(graph_pane)
        self._history_splitter.addWidget(self._files_pane)
        self._history_splitter.setStretchFactor(0, 1)
        self._history_splitter.setStretchFactor(1, 0)
        # A sensible initial split (mostly graph, a real but modest slice for Files Changed) for
        # whenever the files pane first becomes visible -- QSplitter has no notion of an initial
        # ratio for a still-hidden widget otherwise, and would default to splitting evenly instead.
        self._history_splitter.setSizes([300, 120])
        history_layout.addWidget(self._history_splitter, 1)

        self.history_section = CollapsibleSection("History", history_body, collapsed=False)
        layout.addWidget(self.history_section, 1)

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

    def set_stamp_enabled(self, compiled: bool) -> None:
        """Whether the active project is currently compiled (PROMPT.md: "it also should not be
        possible to stamp a non compiled gametype") -- called by MainWindow alongside the activity
        bar's own Apply-enabled state (see ``MainWindow._refresh_apply_enabled``), so this can never
        disagree with what the Apply button itself is showing. Combined with whether the project has
        history at all to decide :attr:`stamp_button`'s real enabled state."""
        self._compiled = compiled
        self._update_stamp_enabled(self._has_history)

    def _update_stamp_enabled(self, has_history: bool) -> None:
        self._has_history = has_history
        enabled = has_history and self._compiled
        self.stamp_button.setEnabled(enabled)
        self.stamp_button.setToolTip(
            "" if self._compiled else "Compile (Apply) this gametype before stamping a release."
        )

    def refresh(self) -> None:
        """Re-reads :attr:`current_folder`'s own branch list/current branch/uncommitted changes/
        graph from :mod:`in_reach.app.vcs` -- called on activation, and again by MainWindow after
        any action that changes history (commit, stamp, new branch, switch, restore) actually
        completes."""
        has_history = self.current_folder is not None and vcs.is_initialized(self.current_folder)
        self.branches_section.setVisible(has_history)
        self.branch_combo.setEnabled(has_history)
        self.new_branch_button.setEnabled(has_history)
        self.delete_branch_button.setEnabled(has_history)
        self.merge_branch_button.setEnabled(has_history)
        self.changes_section.setVisible(has_history)
        self.staged_list.setVisible(has_history)
        self.changes_list.setVisible(has_history)
        self.commit_message_edit.setEnabled(has_history)
        self.release_section.setVisible(has_history)
        self._update_stamp_enabled(has_history)
        self.compare_section.setVisible(has_history)
        self.compare_a_type_combo.setEnabled(has_history)
        self.compare_b_type_combo.setEnabled(has_history)
        self.compare_a_combo.setEnabled(has_history)
        self.compare_b_combo.setEnabled(has_history)
        self.compare_button.setEnabled(has_history)
        self.history_section.setVisible(has_history)
        self._graph_scroll.setVisible(has_history)
        self.restore_button.setVisible(has_history)
        self._empty_label.setVisible(not has_history)

        self._suppress_branch_signal = True
        self.branch_combo.clear()
        self._branches = []
        if has_history:
            self._branches = vcs.list_branches(self.current_folder)
            self.branch_combo.addItems(self._branches)
            current = vcs.current_branch(self.current_folder)
            if current is not None:
                self.branch_combo.setCurrentText(current)
        self._suppress_branch_signal = False

        uncommitted = vcs.uncommitted_changes(self.current_folder) if has_history else []
        staged = [c for c in uncommitted if c.staged]
        unstaged = [c for c in uncommitted if not c.staged]
        self.uncommitted_count = len(uncommitted)
        self.staged_count = len(staged)
        self.changes_section.set_title(f"Changes ({len(uncommitted)})")
        self.staged_label.setText(f"Staged Changes ({len(staged)})")
        self.changes_label.setText(f"Changes ({len(unstaged)})")
        self._fill_change_list(self.staged_list, staged)
        self._fill_change_list(self.changes_list, unstaged)
        self._update_commit_enabled()

        self._snapshots = vcs.graph_history(self.current_folder) if has_history else []
        self.graph.set_snapshots(self._snapshots)
        self.restore_button.setEnabled(False)
        self._selected_commit_sha = None
        self.commit_files_label.hide()
        self.commit_files_list.hide()
        self.commit_files_list.clear()
        self._files_pane.hide()  # collapses the splitter back to just the graph pane

        # Reset both sides back to "Branch" on every refresh -- setCurrentIndex() only actually
        # fires currentTextChanged (and so _populate_compare_combo(), via the constructor's own
        # connection) when the index genuinely changes, so this also explicitly (re-)populates both
        # combos directly rather than relying on that signal alone.
        self.compare_a_type_combo.setCurrentIndex(0)
        self.compare_b_type_combo.setCurrentIndex(0)
        self._populate_compare_combo(self.compare_a_combo, _COMPARE_TYPE_BRANCH)
        self._populate_compare_combo(self.compare_b_combo, _COMPARE_TYPE_BRANCH)
        if self.compare_a_combo.count() > 1:
            self.compare_b_combo.setCurrentIndex(1)

    def _fill_change_list(self, list_widget: QListWidget, changes: list) -> None:
        """Fills ``list_widget`` (one of :attr:`staged_list`/:attr:`changes_list`) with ``changes``
        -- each item carries its own project-relative path as :attr:`Qt.ItemDataRole.UserRole`, what
        :meth:`_on_change_clicked`/:meth:`_show_change_context_menu` read back."""
        list_widget.clear()
        for change in changes:
            prefix = _CHANGE_TYPE_PREFIX.get(change.change_type, "?")
            item_index = list_widget.count()
            list_widget.addItem(f"{prefix}  {change.path}")
            list_widget.item(item_index).setData(Qt.ItemDataRole.UserRole, change.path)

    def _populate_compare_combo(self, combo: QComboBox, type_name: str) -> None:
        """Fills ``combo`` (one of :attr:`compare_a_combo`/:attr:`compare_b_combo`) with just
        ``type_name``'s own refs -- every branch name, or every stamp's own message -- instead of
        both kinds merged into one long list (see this module's own ``_COMPARE_TYPE_*`` docstring).
        Called on every :meth:`refresh`, and again whenever either side's own type combo changes."""
        combo.clear()
        if type_name == _COMPARE_TYPE_STAMP:
            for snapshot in self._snapshots:
                if snapshot.is_stamp:
                    combo.addItem(f"{_STAMP_LABEL_PREFIX}{snapshot.stamp_message}", snapshot.sha)
        else:
            for branch in self._branches:
                combo.addItem(branch, branch)

    # -- user actions ---------------------------------------------------------------------------

    def _on_change_clicked(self, item) -> None:  # noqa: ANN001 -- QListWidgetItem
        rel_path = item.data(Qt.ItemDataRole.UserRole)
        if rel_path:
            self.diff_file_requested.emit(rel_path)

    def _build_change_context_menu(self, list_widget: QListWidget, item) -> QMenu | None:  # noqa: ANN001 -- QListWidgetItem
        """Builds (but never shows) the right-click menu for ``item`` in ``list_widget`` (one of
        :attr:`staged_list`/:attr:`changes_list`) -- PROMPT.md: "in the changes it should be
        possible to right click the file and then see: Open changes, open files, open file (HEAD),
        discard changes, stage changes (or unstage changes), reveal in file explorer". Split out
        from :meth:`_show_change_context_menu` (construction vs. ``exec()``-ing it) purely as a test
        seam, same reasoning as ``MainWindow``'s own ``_confirm_*`` methods. ``None`` if ``item`` has
        no path of its own to act on.

        Offers "Stage Changes" xor "Unstage Changes" depending on which list ``item`` is actually
        in -- never both, since an item is only ever in one of the two lists at a time."""
        rel_path = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not rel_path:
            return None
        is_staged = list_widget is self.staged_list

        menu = QMenu(self)
        menu.addAction("Open Changes", lambda: self.diff_file_requested.emit(rel_path))
        menu.addAction("Open File", lambda: self.open_file_requested.emit(rel_path))
        menu.addAction("Open File (HEAD)", lambda: self.open_file_head_requested.emit(rel_path))
        menu.addSeparator()
        menu.addAction("Discard Changes", lambda: self.discard_requested.emit(rel_path))
        if is_staged:
            menu.addAction("Unstage Changes", lambda: self.unstage_requested.emit([rel_path]))
        else:
            menu.addAction("Stage Changes", lambda: self.stage_requested.emit([rel_path]))
        menu.addSeparator()
        menu.addAction("Reveal in File Explorer", lambda: self.reveal_requested.emit(rel_path))
        return menu

    def _show_change_context_menu(self, list_widget: QListWidget, pos) -> None:  # noqa: ANN001 -- QPoint
        item = list_widget.itemAt(pos)
        menu = self._build_change_context_menu(list_widget, item)
        if menu is not None:
            menu.exec(list_widget.viewport().mapToGlobal(pos))

    def _on_stage_all_clicked(self) -> None:
        paths = [self.changes_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.changes_list.count())]
        if paths:
            self.stage_requested.emit(paths)

    def _on_unstage_all_clicked(self) -> None:
        paths = [self.staged_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.staged_list.count())]
        if paths:
            self.unstage_requested.emit(paths)

    def _update_commit_enabled(self) -> None:
        has_message = bool(self.commit_message_edit.text().strip())
        self.commit_button.setEnabled(self.staged_count > 0 and has_message)

    def _on_commit_clicked(self) -> None:
        message = self.commit_message_edit.text().strip()
        if message and self.staged_count > 0:
            self.commit_requested.emit(message)

    def clear_commit_message(self) -> None:
        """Called by MainWindow right after a successful commit -- the message box shouldn't carry
        the just-committed text forward into whatever gets typed next."""
        self.commit_message_edit.clear()

    def _on_stamp_clicked(self) -> None:
        if self.current_folder is None:
            return
        current_version = vcs.last_stamp_version(self.current_folder) or vcs.INITIAL_VERSION
        major, minor, patch = (int(part) for part in current_version.split("."))
        message = ""
        # PROMPT.md: "if a user aborts the stamp due to not re-stamping the same version, the
        # warning should close and they should be back at their release dialog/window" -- declining
        # "Stamp Anyway" no longer cancels the whole action outright; it loops back to the dialog
        # instead, reseeded with whatever version the user just tried (so they can see what they
        # picked) and the message they already typed (see StampReleaseDialog's own ``message``
        # argument), rather than losing their input and having to start over.
        while True:
            result = self._ask_stamp_release(major, minor, patch, message)
            if result is None:
                return
            message, version = result
            if vcs.version_already_stamped(self.current_folder, version) and not self._confirm_duplicate_version(
                version
            ):
                major, minor, patch = (int(part) for part in version.split("."))
                continue
            self.stamp_requested.emit(message, version)
            return

    def _ask_stamp_release(
        self, major: int, minor: int, patch: int, message: str = ""
    ) -> tuple[str, str] | None:
        """Shows the "Stamp Release" dialog (message + major/minor/patch spin boxes seeded from the
        project's current version) and returns ``(message, version)`` if confirmed with a non-empty
        message, ``None`` otherwise -- kept as its own method purely as a test seam, same reasoning
        as :meth:`_ask_text`. ``message``, when given, pre-fills the release-message field (see
        :meth:`_on_stamp_clicked`'s own "back at their release dialog" re-open)."""
        from in_reach.ide.stamp_release_dialog import StampReleaseDialog

        dialog = StampReleaseDialog(major, minor, patch, self, message=message)
        if dialog.exec() != StampReleaseDialog.DialogCode.Accepted:
            return None
        typed_message = dialog.message()
        if not typed_message:
            return None
        return typed_message, dialog.version()

    def _confirm_duplicate_version(self, version: str) -> bool:
        """Asks whether to stamp anyway when ``version`` has already been used by a past stamp
        (PROMPT.md: "if a user tries to submit the same version they should receive a warning
        (asking if they want to overwrite)") -- kept as its own method purely as a test seam, same
        reasoning as :meth:`_ask_text`.

        Returns:
            ``True`` for "Stamp Anyway", ``False`` for "Cancel".
        """
        from PyQt6.QtWidgets import QMessageBox

        choice = QMessageBox.warning(
            self,
            "in-reach",
            f'Version "{version}" has already been stamped. Stamp anyway?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return choice == QMessageBox.StandardButton.Yes

    def _on_new_branch_clicked(self) -> None:
        name = self._ask_text("New Branch", "Branch name:")
        if name:
            self.new_branch_requested.emit(name)

    def _source_ref_choices(self) -> dict[str, str]:
        """Every branch/stamp :meth:`_on_new_branch_from_clicked` can offer as a source, keyed by
        its own display text (a plain branch name, or ``"Stamp: <message>"``, same convention as
        :meth:`_populate_compare_combo`) to its real ref value (a branch name or a stamp's sha)."""
        choices: dict[str, str] = {branch: branch for branch in self._branches}
        for snapshot in self._snapshots:
            if snapshot.is_stamp:
                choices[f"{_STAMP_LABEL_PREFIX}{snapshot.stamp_message}"] = snapshot.sha
        return choices

    def _on_new_branch_from_clicked(self) -> None:
        from PyQt6.QtWidgets import QInputDialog

        choices = self._source_ref_choices()
        if not choices:
            return
        current = vcs.current_branch(self.current_folder) if self.current_folder is not None else None
        display, ok = QInputDialog.getItem(
            self, "New Branch From", "Source branch or stamp:", list(choices), 0, False
        )
        if not ok or not display:
            return
        name = self._ask_text("New Branch From", "Branch name:")
        if not name:
            return
        source = choices[display]
        if source == current:
            self.new_branch_requested.emit(name)  # plain "from current" -- no need for the source
        else:
            self.new_branch_from_requested.emit(name, source)

    def _on_delete_branch_clicked(self) -> None:
        name = self.branch_combo.currentText()
        if name:
            self.delete_branch_requested.emit(name)

    def _build_merge_branch_menu(self) -> QMenu | None:
        """Builds (but never shows) the "Merge Branch" popup menu -- one action per branch other
        than whichever is currently checked out, each merging that branch *into* the current one
        when picked. Split out purely as a test seam, same reasoning as
        :meth:`_build_change_context_menu`. ``None`` if there's no other branch to offer."""
        if self.current_folder is None:
            return None
        current = vcs.current_branch(self.current_folder)
        others = [name for name in self._branches if name != current]
        if not others:
            return None
        menu = QMenu(self)
        for name in others:
            menu.addAction(name, lambda n=name: self.merge_branch_requested.emit(n))
        return menu

    def _on_merge_branch_clicked(self) -> None:
        menu = self._build_merge_branch_menu()
        if menu is not None:
            menu.exec(self.merge_branch_button.mapToGlobal(self.merge_branch_button.rect().bottomLeft()))

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
        self._selected_commit_sha = sha or None
        if sha:
            self._files_pane.show()
            self.commit_files_label.show()
            self.commit_files_list.show()
            self.commit_files_label.setText("Files Changed")
            self.commit_files_list.clear()
            self.commit_selected.emit(sha)
        else:
            self._files_pane.hide()
            self.commit_files_label.hide()
            self.commit_files_list.hide()

    def set_commit_files(self, sha: str, files) -> None:  # noqa: ANN001 -- list[vcs.FileDiff]
        """Populates the "Files Changed" list for ``sha`` -- called by ``MainWindow`` once it's
        fetched :func:`~in_reach.app.vcs.commit_files_changed` in answer to :attr:`commit_selected`.
        A no-op if the graph's own selection has since moved on to a different commit (a slow fetch
        landing after the user already clicked elsewhere shouldn't overwrite what they're looking at
        now)."""
        if sha != self._selected_commit_sha:
            return
        self.commit_files_label.setText(f"Files Changed ({len(files)})")
        self.commit_files_list.clear()
        for change in files:
            prefix = _CHANGE_TYPE_PREFIX.get(change.change_type, "?")
            item_index = self.commit_files_list.count()
            self.commit_files_list.addItem(f"{prefix}  {change.path}")
            self.commit_files_list.item(item_index).setData(Qt.ItemDataRole.UserRole, change.path)

    def _on_commit_file_clicked(self, item) -> None:  # noqa: ANN001 -- QListWidgetItem
        rel_path = item.data(Qt.ItemDataRole.UserRole)
        if rel_path and self._selected_commit_sha:
            self.commit_diff_requested.emit(self._selected_commit_sha, rel_path)

    def _build_commit_file_context_menu(self, item) -> QMenu | None:  # noqa: ANN001 -- QListWidgetItem
        """Builds (but never shows) the right-click menu for ``item`` in :attr:`commit_files_list`
        -- split out from :meth:`_show_commit_file_context_menu` purely as a test seam, same
        reasoning as :meth:`_build_change_context_menu`."""
        rel_path = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not rel_path or not self._selected_commit_sha:
            return None
        sha = self._selected_commit_sha
        menu = QMenu(self)
        menu.addAction("View Diff", lambda: self.commit_diff_requested.emit(sha, rel_path))
        menu.addAction("Open File", lambda: self.commit_open_file_requested.emit(sha, rel_path))
        return menu

    def _show_commit_file_context_menu(self, pos) -> None:  # noqa: ANN001 -- QPoint
        item = self.commit_files_list.itemAt(pos)
        menu = self._build_commit_file_context_menu(item)
        if menu is not None:
            menu.exec(self.commit_files_list.viewport().mapToGlobal(pos))

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
