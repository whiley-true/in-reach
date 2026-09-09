"""The primary sidebar's Dashboard view (PROMPT.md: "file explorer is renamed to dashboard"): a
tab per currently open gametype project (PROMPT.md: "multiple projects can be loaded ... have tabs
for the different projects that then changes the project explorer below"), showing three boxes for
it -- "Script"/"Settings" pointed at that project's own ``script/``/``settings/`` subfolders, and
"Stats" summarizing its build's own space usage and string count (see
:func:`~in_reach.app.rvt.settings_io.load_build_stats`/:func:`~in_reach.app.rvt.strings_io.
count_script_strings`). There used to be a sixth, generic "browse the whole project folder" tree
too; PROMPT.md asked for it to go now that Script/Settings cover the two subfolders actually worth
browsing by hand. The personal game/map variant folder trees that used to live here too (PROMPT.md:
"remove the Personal Map and Game Variants sections for now, they will later go in their own
sidepanel") are gone for now -- :mod:`in_reach.app.system_verify` still resolves those folders for
the Welcome tab's own Verify System Settings flow, this panel just doesn't display them anymore.

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
    QProgressBar,
    QSizePolicy,
    QTabBar,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from in_reach.app import new_project
from in_reach.app.rvt import settings_io, strings_io
from in_reach.ide.file_icons import ExplorerIconProvider

_NO_PROJECT_TEXT = "No project opened yet -- create or load one from the Welcome tab."
_NO_STATS_TEXT = "No build stats yet -- Apply (or launch RVT) once this gametype compiles."


def _new_tree() -> tuple[QTreeView, QFileSystemModel]:
    model = QFileSystemModel()
    model.setIconProvider(ExplorerIconProvider())
    tree = QTreeView()
    tree.setModel(model)
    tree.setHeaderHidden(True)
    for column in (1, 2, 3):  # Size, Type, Date Modified -- a flat file list doesn't need these
        tree.hideColumn(column)
    tree.setUniformRowHeights(True)
    # PROMPT.md: "please remove the bubble outline around ... settings, and output.txt" --
    # QTreeView (like every QAbstractScrollArea) defaults to a sunken StyledPanel frame around
    # itself, which read as a bordered "bubble" boxing in the Settings/Script trees' own handful of
    # rows. Same fix already applied to the Welcome tab's own QScrollArea, see welcome.py.
    tree.setFrameShape(QFrame.Shape.NoFrame)
    return tree, model


def _cap_tree_rows(tree: QTreeView, rows: int) -> None:
    """Caps ``tree``'s own height to fit exactly ``rows`` rows, no more -- for the Settings/Script
    quick-access trees, whose subfolder always holds a fixed, known number of entries (3
    ``settings/*.json`` files, 1 ``script/output.txt``), so there's no reason either should reserve
    a QTreeView's own generic, content-independent size hint worth of extra blank space below its
    last real row (PROMPT.md: "there is still too much empty space under settings. it only needs
    to be 3 files vertical").

    Recomputed from the tree's *current* font on every call rather than cached once, so a zoom
    change (:meth:`ExplorerPanel.refresh_font_scale`) resizes this along with everything else
    instead of leaving it clipped to whatever row height was live when the app started.
    """
    row_height = tree.fontMetrics().height() + 8  # +8: Qt's own default per-item vertical padding
    tree.setMaximumHeight(row_height * rows)
    tree.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)


def _point_tree_at(tree: QTreeView, model: QFileSystemModel, folder: Path | None) -> None:
    """Roots ``tree`` at ``folder``, or back to the empty placeholder for ``None``.

    ``folder`` must actually exist as a directory -- an empty string root path (what
    ``QFileSystemModel`` falls back to for ``None``/a missing folder) shows "This PC"'s own top
    level (every drive letter) rather than nothing, which read as "the script drop down is showing
    local disk, new volume[,] etc" (PROMPT.md) for a project predating some later folder rename that
    left an expected subfolder missing. Callers pointing at a project's own subfolder should create
    it first (a plain ``mkdir(parents=True, exist_ok=True)``) rather than pass one that might not
    exist, so this is only ever really hit for the genuine "no project open" case.
    """
    if folder is None or not folder.is_dir():
        model.setRootPath("")
        tree.setRootIndex(model.index(""))
        return
    model.setRootPath(str(folder))
    tree.setRootIndex(model.index(str(folder)))


#: PROMPT.md: "instead of using bubbles around sections, maybe just have the section header and a
#: line break/divider with a collapsing arrow ... to try and stop the ui being too cluttered" --
#: strips the checkable QToolButton's own default raised/"pill" background (shown whenever a
#: section is expanded, since it's ``checked`` then -- see _CollapsibleSection.__init__) so the
#: header reads as plain text-plus-arrow, not a button.
_SECTION_HEADER_STYLE = "QToolButton { border: none; background-color: transparent; }"

#: PROMPT.md: "please remove the bubble outline around triggers conditions actions, forge lables
#: and strings" -- Fusion's own default QProgressBar is a rounded, bordered pill; this flattens it
#: to a plain rectangle so it stops reading as a bordered "bubble" over the Stats box's own text.
_FLAT_PROGRESS_BAR_STYLE = (
    "QProgressBar { border: none; border-radius: 0px; background-color: palette(alternate-base);"
    " text-align: center; }"
    "QProgressBar::chunk { background-color: palette(highlight); }"
)


class _CollapsibleSection(QWidget):
    """A header (an arrow + title, click to toggle) above a divider line and a body widget that
    hides/shows with it -- VS Code's own sidebar section headers, applied to every box in this
    panel so each reads as its own labeled region without needing a bordered/bubble frame around
    it (PROMPT.md, see :data:`_SECTION_HEADER_STYLE`)."""

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
        self._toggle.setStyleSheet(_SECTION_HEADER_STYLE)
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._toggle.toggled.connect(self._on_toggled)
        layout.addWidget(self._toggle)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Plain)
        layout.addWidget(divider)

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
    #: Emitted with a file's path when it's clicked in the Script or Settings box -- never for a
    #: directory (clicking one just expands/collapses it, QTreeView's own default behavior).
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

    #: Section headers (Stats/Settings/Script) read 10% smaller than the rest of this panel's own
    #: (already +10%'d) text, so they read as "10% smaller than its neighbors" rather than landing
    #: back near the app's own plain size.
    HEADER_TEXT_SCALE = 0.9

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        #: The gametype project folder the main tree currently points at, or ``None`` -- read by
        #: MainWindow.launch_rvt() to know which project's .bin to open RVT against.
        self.current_folder: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        #: One tab per currently open project (PROMPT.md), labeled with its own title -- read back
        #: from its own settings.json (see :func:`~in_reach.app.new_project.read_project_title`),
        #: same as the Welcome tab's Recent list -- via :meth:`open_project`/:meth:`close_project`,
        #: not touched directly. Hidden whenever no project is open.
        self.project_tabs = QTabBar()
        self.project_tabs.setTabsClosable(True)
        self.project_tabs.setExpanding(False)
        self.project_tabs.setUsesScrollButtons(True)
        self.project_tabs.hide()
        self.project_tabs.currentChanged.connect(self._on_tab_changed)
        self.project_tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        layout.addWidget(self.project_tabs)

        self._no_project_label = QLabel(_NO_PROJECT_TEXT)
        self._no_project_label.setWordWrap(True)
        self._no_project_label.setEnabled(False)
        layout.addWidget(self._no_project_label)

        # A hidden widget in a QVBoxLayout doesn't claim its own stretch share, so with the
        # Script/Settings/Stats boxes below all hidden (no project open), this stands in for that
        # -- keeping the "no project" label pinned to the top instead of the layout centering it in
        # whatever space is left -- and collapses back to nothing the moment a project opens (see
        # _activate()).
        self._no_project_spacer = QWidget()
        layout.addWidget(self._no_project_spacer, 1)

        # PROMPT.md: "please also add a stats view into the dashboard" -- the active project's own
        # build/stats.autogenerated.json (space usage + script content counts), regenerated by
        # every decompile/resync/Apply for a multiplayer gametype (see
        # in_reach.app.rvt.decompile's own module docstring) -- there's nothing to show for a
        # blank/Firefight project that's never compiled, hence the placeholder. Placed first
        # (PROMPT.md: "put the stats at the top, then settings underneath ... then Script") --
        # stats/settings/script all take stretch=0 so they sit close together rather than each
        # claiming a share of any extra vertical space; the trailing addStretch() below is what
        # absorbs that space instead, keeping the three boxes anchored to the top of the panel.
        #
        # PROMPT.md: "please combine the percentage used bar to be: 10,874 / 20520 B used (53%)
        # (and with the progress bar background)" -- the byte-usage figure is the progress bar's
        # own displayed text (QProgressBar.setFormat(), in refresh_stats()) rather than a separate
        # label line, so it reads directly over the bar's own fill instead of next to it.
        self.stats_progress = QProgressBar()
        self.stats_progress.setRange(0, 100)
        self.stats_progress.setTextVisible(True)
        # PROMPT.md: "please remove the bubble outline around triggers conditions actions, forge
        # lables and strings" -- Fusion's own default QProgressBar chrome is a rounded, bordered
        # pill sitting directly above those two lines; flattening it to a plain rectangle removes
        # the one bordered/"bubble" element left in the Stats box.
        self.stats_progress.setStyleSheet(_FLAT_PROGRESS_BAR_STYLE)
        # PROMPT.md: "fix the panel icon width so that trigger conditions and actions should
        # always display on the same line" -- its own label, word-wrap off, rather than folded
        # into stats_label's general (deliberately wrapping) prose/counts text: a wrapping QLabel
        # word-wraps *within* each of its own "\n"-joined lines too if the panel's too narrow for
        # one of them, which is exactly what was splitting this one over two lines. Kept from ever
        # actually needing to overflow by _SIDEBAR_MIN_WIDTH (see main_window.py), sized against
        # this line's own worst-case (triple-digit counts) width.
        self.stats_counts_label = QLabel()
        self.stats_counts_label.setWordWrap(False)
        self.stats_label = QLabel(_NO_STATS_TEXT)
        self.stats_label.setWordWrap(True)
        stats_body = QFrame()
        stats_layout = QVBoxLayout(stats_body)
        stats_layout.setContentsMargins(0, 4, 0, 0)
        stats_layout.setSpacing(4)
        stats_layout.addWidget(self.stats_progress)
        stats_layout.addWidget(self.stats_counts_label)
        stats_layout.addWidget(self.stats_label)
        self.stats_section = _CollapsibleSection("Stats", stats_body, collapsed=False)
        self.stats_section.hide()
        layout.addWidget(self.stats_section)

        # Dedicated quick-access boxes for the active project's own script/settings subfolders,
        # open by default since they're central to the active project. Hidden entirely with no
        # project open (see _activate()).
        self.settings_tree, self._settings_model = _new_tree()
        self.settings_section = _CollapsibleSection("Settings", self.settings_tree, collapsed=False)
        self.settings_section.hide()
        layout.addWidget(self.settings_section)

        self.script_tree, self._script_model = _new_tree()
        self.script_section = _CollapsibleSection("Script", self.script_tree, collapsed=False)
        self.script_section.hide()
        layout.addWidget(self.script_section)

        layout.addStretch(1)

        for tree, model in (
            (self.script_tree, self._script_model),
            (self.settings_tree, self._settings_model),
        ):
            tree.clicked.connect(lambda index, m=model: self._on_tree_clicked(m, index))

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
        self.script_section.set_header_font(header_font)
        self.settings_section.set_header_font(header_font)
        self.stats_section.set_header_font(header_font)

        _cap_tree_rows(self.settings_tree, 3)  # settings/settings.json, script_settings.json, strings.json
        _cap_tree_rows(self.script_tree, 1)  # script/output.txt

    def _on_tree_clicked(self, model: QFileSystemModel, index: QModelIndex) -> None:
        if not index.isValid() or model.isDir(index):
            return
        self.file_activated.emit(Path(model.filePath(index)))

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
        """Re-reads ``folder``'s own title (its ``settings.json`` -- see
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
        """Points the main tree (and the Script/Settings/Stats boxes) at ``folder`` (the newly
        active gametype project's own folder), or back to the "no project" placeholder for
        ``None``."""
        self.current_folder = folder
        has_project = folder is not None and folder.is_dir()
        self.project_tabs.setVisible(self.project_tabs.count() > 0)
        self._no_project_label.setVisible(not has_project)
        self._no_project_spacer.setVisible(not has_project)
        self.script_section.setVisible(has_project)
        self.settings_section.setVisible(has_project)
        _point_tree_at(self.script_tree, self._script_model, self._ensure_subdir(folder, new_project.SCRIPT_DIRNAME))
        _point_tree_at(
            self.settings_tree, self._settings_model, self._ensure_subdir(folder, new_project.SETTINGS_DIRNAME)
        )
        self.stats_section.setVisible(has_project)
        self.refresh_stats()
        self.active_project_changed.emit(folder)

    @staticmethod
    def _ensure_subdir(folder: Path | None, name: str) -> Path | None:
        """``folder / name``, first creating it if it doesn't exist yet -- a project predating some
        later folder rename (or one hand-deleted) can otherwise be missing an expected subfolder,
        which used to make :func:`_point_tree_at` fall back to showing every drive letter on the
        machine instead (PROMPT.md: "the script drop down is showing local disk, new volum[e] etc").
        ``None`` (no project open) passes straight through."""
        if folder is None:
            return None
        subdir = folder / name
        subdir.mkdir(parents=True, exist_ok=True)
        return subdir

    # -- the Stats box --------------------------------------------------------------------------

    def refresh_stats(self) -> None:
        """Re-reads :attr:`current_folder`'s own ``build/stats.autogenerated.json`` (space usage +
        script content counts) and ``settings/strings.json`` (PROMPT.md: "please also make stats
        include[] strings.json") and updates the Stats box to match (PROMPT.md: "please also add a
        stats view into the dashboard") -- called on every project switch, and again by
        ``MainWindow`` after a resync/Apply might have regenerated either.

        ``strings.json`` is shown independently of the build stats -- it's written for every
        project, multiplayer or not (see :mod:`in_reach.app.rvt.decompile`'s own module docstring),
        where the build stats file only ever exists for a multiplayer gametype that's actually
        compiled at least once. The placeholder text only shows if *neither* is available.
        """
        stats = None
        strings_count = None
        if self.current_folder is not None:
            from in_reach.app.rvt.decompile import GENERATED_STATS_FILENAME, STRINGS_FILENAME

            stats_path = self.current_folder / new_project.BUILD_DIRNAME / GENERATED_STATS_FILENAME
            stats = settings_io.load_build_stats(stats_path)
            strings_path = self.current_folder / new_project.SETTINGS_DIRNAME / STRINGS_FILENAME
            strings_count = strings_io.count_script_strings(strings_path)

        self.stats_progress.setVisible(stats is not None)
        self.stats_counts_label.setVisible(stats is not None)
        lines: list[str] = []
        if stats is not None:
            self.stats_progress.setValue(round(stats.space.percent))
            # PROMPT.md: "please combine the percentage used bar to be: 10,874 / 20520 Bytes used
            # (53%) (and with the progress bar background)" -- shown as the bar's own text over its
            # fill, rather than a separate label line.
            self.stats_progress.setFormat(
                f"{stats.space.bytes_used:,} / {stats.space.bytes_max:,} Bytes used ({stats.space.percent:.0f}%)"
            )
            counts = stats.counts
            self.stats_counts_label.setText(
                f"Triggers: {counts.triggers}   Conditions: {counts.conditions}   Actions: {counts.actions}"
            )
            # PROMPT.md: "Forge labels and Strings should be on the same line"
            forge_line = f"Forge Labels: {counts.forge_labels}"
            lines.append(f"{forge_line}   Strings: {strings_count}" if strings_count is not None else forge_line)
        elif strings_count is not None:
            lines.append(f"Strings: {strings_count}")
        self.stats_label.setText("\n".join(lines) if lines else _NO_STATS_TEXT)
