"""The primary sidebar's Explorer view: a tab per currently open gametype project (PROMPT.md:
"multiple projects can be loaded ... have tabs for the different projects that then changes the
project explorer below"), each showing that project's own folder tree, plus -- collapsed by
default, since they're secondary to it -- two more folder trees for the personal game/map variant
folders :mod:`in_reach.app.system_verify` resolves (shared across every open project, since they
don't depend on which one is active).

Each tree is a plain ``QFileSystemModel``/``QTreeView`` pair (so it reflects live disk changes for
free) with a custom icon provider (:mod:`in_reach.ide.file_icons`) swapped in for the platform's
own generic file icons.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QFileSystemModel, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QSizePolicy,
    QTabBar,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from in_reach.app import env_file, new_project, system_verify
from in_reach.ide.file_icons import ExplorerIconProvider

_NO_PROJECT_TEXT = "No project opened yet -- create or load one from the Welcome tab."
_NOT_RESOLVED_TEXT = "Not verified yet -- see Verify System Settings on the Welcome tab."


def _new_tree() -> tuple[QTreeView, QFileSystemModel]:
    model = QFileSystemModel()
    model.setIconProvider(ExplorerIconProvider())
    tree = QTreeView()
    tree.setModel(model)
    tree.setHeaderHidden(True)
    for column in (1, 2, 3):  # Size, Type, Date Modified -- a flat file list doesn't need these
        tree.hideColumn(column)
    tree.setUniformRowHeights(True)
    return tree, model


def _point_tree_at(tree: QTreeView, model: QFileSystemModel, folder: Path | None) -> None:
    if folder is None or not folder.is_dir():
        model.setRootPath("")
        tree.setRootIndex(model.index(""))
        return
    model.setRootPath(str(folder))
    tree.setRootIndex(model.index(str(folder)))


class _CollapsibleSection(QWidget):
    """A header (an arrow + title, click to toggle) above a body widget that hides/shows with it
    -- VS Code's own sidebar section headers, applied here to the two personal-folder trees so
    they read as secondary to the main project tree above them rather than competing for space."""

    def __init__(self, title: str, body: QWidget, *, collapsed: bool = True) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._toggle = QToolButton()
        self._toggle.setText(title)
        self._toggle.setCheckable(True)
        self._toggle.setChecked(not collapsed)
        self._toggle.setArrowType(Qt.ArrowType.DownArrow if not collapsed else Qt.ArrowType.RightArrow)
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle.setAutoRaise(True)
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._toggle.toggled.connect(self._on_toggled)
        layout.addWidget(self._toggle)

        self.body = body
        self.body.setVisible(not collapsed)
        layout.addWidget(self.body, 1)

    def _on_toggled(self, checked: bool) -> None:
        self._toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self.body.setVisible(checked)

    def set_header_font(self, font: QFont) -> None:
        """Overrides the header's own font -- e.g. to size it independently of :attr:`body`'s
        inherited one (see :meth:`ExplorerPanel.refresh_font_scale`)."""
        self._toggle.setFont(font)

    @property
    def expanded(self) -> bool:
        return self._toggle.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self._toggle.setChecked(expanded)


class ExplorerPanel(QWidget):
    #: Emitted with a file's path when it's clicked in the main project tree -- never for a
    #: directory (clicking one just expands/collapses it, QTreeView's own default behavior), and
    #: not from either personal-folder tree (see their own click wiring, below, for why).
    file_activated = pyqtSignal(Path)

    #: Emitted with the newly active project's folder (or ``None`` once the last tab closes) --
    #: whenever the tab switches, a new one opens, or the current one closes.
    active_project_changed = pyqtSignal(object)

    #: Emitted with every currently open project's folder, in tab order, whenever that set changes
    #: (a tab opens, closes, or the whole list is cleared) -- distinct from
    #: :attr:`active_project_changed` since a tab closing in the background changes this without
    #: changing which one is active.
    open_projects_changed = pyqtSignal(list)

    #: PROMPT.md: "please tweak the default explorer text scale to be +10%" -- relative to the
    #: app's own current zoom-scaled font (see :meth:`refresh_font_scale`), not a fixed point size.
    TEXT_SCALE = 1.1

    #: "make Personal Game Variant and Personal Map Variant text 10% smaller" -- relative to the
    #: rest of this panel's own (already +10%'d) text, not the app font directly, so it reads as
    #: "10% smaller than its neighbors" rather than landing back near the app's own plain size.
    HEADER_TEXT_SCALE = 0.9

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._env_project_dir: Path | None = None
        #: The gametype project folder the main tree currently points at, or ``None`` -- read by
        #: MainWindow.launch_rvt() to know which project's .bin to open RVT against.
        self.current_folder: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        #: One tab per currently open project (PROMPT.md), labeled with its own title -- read back
        #: from its README (see :func:`~in_reach.app.new_project.read_project_title`), same as the
        #: Welcome tab's Recent list -- via :meth:`open_project`/:meth:`close_project`, not touched
        #: directly. Hidden whenever no project is open, same as the tree itself.
        self.project_tabs = QTabBar()
        self.project_tabs.setTabsClosable(True)
        self.project_tabs.setExpanding(False)
        self.project_tabs.setUsesScrollButtons(True)
        self.project_tabs.hide()
        self.project_tabs.currentChanged.connect(self._on_tab_changed)
        self.project_tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        layout.addWidget(self.project_tabs)

        #: The active project's own *folder* name (the generated id, e.g. "abcd1234") -- distinct
        #: from its tab's own title text -- shown as a subheading underneath the tabs (PROMPT.md:
        #: "include the name of the folder as subheading on the explorer page (underneath project
        #: tabs)"). Hidden along with everything else project-related when nothing is open.
        self.folder_subheading = QLabel()
        self.folder_subheading.setEnabled(False)
        self.folder_subheading.hide()
        layout.addWidget(self.folder_subheading)

        self._no_project_label = QLabel(_NO_PROJECT_TEXT)
        self._no_project_label.setWordWrap(True)
        self._no_project_label.setEnabled(False)
        layout.addWidget(self._no_project_label)

        self.project_tree, self._project_model = _new_tree()
        self.project_tree.hide()
        layout.addWidget(self.project_tree, 1)

        # PROMPT.md: "when no project is open, the Personal Game Variants and Personal Map
        # Variants should appear at the bottom of the file explorer panel" -- project_tree's own
        # stretch=1 above only pushes them down while it's actually visible (a hidden widget in a
        # QVBoxLayout doesn't claim its stretch share), so this stands in for it whenever there's no
        # project open, and collapses back to nothing the moment one is (see _activate()).
        self._no_project_spacer = QWidget()
        layout.addWidget(self._no_project_spacer, 1)

        self.personal_variants_tree, self._personal_variants_model = _new_tree()
        self.personal_variants_placeholder = self._placeholder_label()
        self.personal_variants_section = _CollapsibleSection(
            "Personal Game Variants", self._folder_body(self.personal_variants_tree, self.personal_variants_placeholder)
        )
        layout.addWidget(self.personal_variants_section)

        self.personal_maps_tree, self._personal_maps_model = _new_tree()
        self.personal_maps_placeholder = self._placeholder_label()
        self.personal_maps_section = _CollapsibleSection(
            "Personal Map Variants", self._folder_body(self.personal_maps_tree, self.personal_maps_placeholder)
        )
        layout.addWidget(self.personal_maps_section)

        # Only the main project tree opens files on click -- the two personal-folder trees hold
        # raw .bin/.mvar game/map variants, which the plain text editor can't do anything useful
        # with yet (PROMPT.md: opening one currently "raises an error as trying to open them as if
        # they were text"). Once those file types are actually processed, this can open up too.
        self.project_tree.clicked.connect(lambda index: self._on_tree_clicked(self._project_model, index))

        self.refresh_font_scale()

    def refresh_font_scale(self) -> None:
        """(Re-)applies :data:`TEXT_SCALE` on top of the app's current font.

        Setting a font directly on this widget makes every child that doesn't set its own
        (every label/tree/section header here) inherit it too -- Qt's ordinary font cascade --
        but that inheritance is a one-time snapshot, not a live binding: it stops tracking
        ``QApplication.font()`` the moment this is set. Call this again after a zoom change (see
        ``MainWindow._adjust_zoom()``) or it'll be stuck at whatever scale was live when it was
        last called.
        """
        app = QApplication.instance()
        if app is None:
            return
        font = QFont(app.font())
        font.setPointSizeF(font.pointSizeF() * self.TEXT_SCALE)
        self.setFont(font)

        header_font = QFont(font)
        header_font.setPointSizeF(font.pointSizeF() * self.HEADER_TEXT_SCALE)
        self.personal_variants_section.set_header_font(header_font)
        self.personal_maps_section.set_header_font(header_font)

    def _on_tree_clicked(self, model: QFileSystemModel, index: QModelIndex) -> None:
        if not index.isValid() or model.isDir(index):
            return
        self.file_activated.emit(Path(model.filePath(index)))

    def _placeholder_label(self) -> QLabel:
        label = QLabel(_NOT_RESOLVED_TEXT)
        label.setWordWrap(True)
        label.setEnabled(False)
        return label

    def _folder_body(self, tree: QTreeView, placeholder: QLabel) -> QWidget:
        body = QFrame()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 4, 0, 0)
        body_layout.addWidget(tree)
        body_layout.addWidget(placeholder)
        return body

    # -- the main project tree -------------------------------------------------------------------

    @property
    def open_projects(self) -> list[Path]:
        """Every currently open project, in tab order -- the tab bar itself is the source of
        truth, so this can never drift out of sync with what's actually shown."""
        return [Path(self.project_tabs.tabData(index)) for index in range(self.project_tabs.count())]

    def open_project(self, folder: Path) -> None:
        """Opens ``folder`` as a tab, switching to it -- or, if it's already open, just switches to
        its existing tab rather than adding a duplicate. A no-op (nothing added, nothing switched)
        for a folder that doesn't actually exist, so a bad path can't clobber whatever's already
        open with a dead tab.

        Signals are blocked around the actual tab-bar calls and :meth:`_activate` is called
        directly instead -- ``addTab()`` fires ``currentChanged`` for a brand new *first* tab
        synchronously, before ``setTabData()`` below it has a chance to run, which would otherwise
        have :meth:`_on_tab_changed` read back ``None`` instead of the folder just added.
        """
        if not folder.is_dir():
            return
        self.project_tabs.blockSignals(True)
        try:
            for index in range(self.project_tabs.count()):
                if Path(self.project_tabs.tabData(index)) == folder:
                    self.project_tabs.setCurrentIndex(index)
                    self._activate(folder)
                    return
            index = self.project_tabs.addTab(new_project.read_project_title(folder))
            self.project_tabs.setTabData(index, str(folder))
            self.project_tabs.setCurrentIndex(index)
        finally:
            self.project_tabs.blockSignals(False)
        self._activate(folder)
        self.open_projects_changed.emit(self.open_projects)

    def refresh_project_title(self, folder: Path) -> None:
        """Re-reads ``folder``'s own title (its README's heading -- see
        :func:`~in_reach.app.new_project.read_project_title`) and relabels its tab to match --
        called after a rename (PROMPT.md: "when a project name is changed [via rvt or via apply
        settings.json change] - the project title should change in the tabs and in the
        breadcrumb"). A no-op if ``folder`` isn't currently open as a tab."""
        for index in range(self.project_tabs.count()):
            if Path(self.project_tabs.tabData(index)) == folder:
                self.project_tabs.setTabText(index, new_project.read_project_title(folder))
                return

    def close_project(self, folder: Path) -> None:
        """Closes ``folder``'s own tab, if it's open -- Qt's own ``QTabBar`` picks a neighboring
        tab to switch to (or, if this was the last one, falls back to the "no project"
        placeholder; see :meth:`_on_tab_changed`)."""
        for index in range(self.project_tabs.count()):
            if Path(self.project_tabs.tabData(index)) == folder:
                self.project_tabs.removeTab(index)
                self.open_projects_changed.emit(self.open_projects)
                return

    def close_active_project(self) -> None:
        """Closes whichever tab is currently active -- "Close Project" (File menu). A no-op with
        no project open."""
        if self.current_folder is not None:
            self.close_project(self.current_folder)

    def close_all_projects(self) -> None:
        """Closes every open tab at once, back to the "no project" placeholder."""
        for folder in list(self.open_projects):
            self.close_project(folder)

    def _on_tab_close_requested(self, index: int) -> None:
        self.close_project(Path(self.project_tabs.tabData(index)))

    def _on_tab_changed(self, index: int) -> None:
        self._activate(Path(self.project_tabs.tabData(index)) if index >= 0 else None)

    def _activate(self, folder: Path | None) -> None:
        """Points the main tree at ``folder`` (the newly active gametype project's own folder), or
        back to the "no project" placeholder for ``None``."""
        self.current_folder = folder
        has_project = folder is not None and folder.is_dir()
        self.project_tabs.setVisible(self.project_tabs.count() > 0)
        self.folder_subheading.setText(folder.name if has_project else "")
        self.folder_subheading.setVisible(has_project)
        self._no_project_label.setVisible(not has_project)
        self.project_tree.setVisible(has_project)
        self._no_project_spacer.setVisible(not has_project)
        _point_tree_at(self.project_tree, self._project_model, folder)
        self.active_project_changed.emit(folder)

    # -- the two personal-folder sections ----------------------------------------------------------

    def set_env_project_dir(self, project_dir: Path | None) -> None:
        """Points the two personal-folder sections at whatever
        :data:`~in_reach.app.system_verify.PERSONAL_VARIANTS_KEY`/
        :data:`~in_reach.app.system_verify.PERSONAL_MAPS_KEY` currently resolve to in
        ``project_dir``'s own ``.env`` -- the project's ``.in-reach`` folder, not any gametype
        project folder :meth:`open_project` opens as a tab.

        Args:
            project_dir: The project's ``.in-reach`` folder, or ``None`` to clear both sections.
        """
        self._env_project_dir = project_dir
        self.refresh_personal_folders()

    def refresh_personal_folders(self) -> None:
        """Re-resolves both personal-folder sections against the ``.env`` -- called after a verify
        run or "Clear Entries" might have changed either one."""
        values = self._env_values()

        self._apply_personal_folder(
            self.personal_variants_tree,
            self._personal_variants_model,
            self.personal_variants_placeholder,
            values.get(system_verify.PERSONAL_VARIANTS_KEY),
        )
        self._apply_personal_folder(
            self.personal_maps_tree,
            self._personal_maps_model,
            self.personal_maps_placeholder,
            values.get(system_verify.PERSONAL_MAPS_KEY),
        )

    def _env_values(self) -> dict[str, str]:
        if self._env_project_dir is None:
            return {}
        return env_file.get_env_values(system_verify.env_path_for(self._env_project_dir))

    def _apply_personal_folder(
        self, tree: QTreeView, model: QFileSystemModel, placeholder: QLabel, raw: str | None
    ) -> None:
        folder = Path(raw) if raw else None
        resolved = folder is not None and folder.is_dir()
        tree.setVisible(resolved)
        placeholder.setVisible(not resolved)
        _point_tree_at(tree, model, folder if resolved else None)
