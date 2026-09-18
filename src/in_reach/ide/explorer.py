"""The primary sidebar's Dashboard view (PROMPT.md: "file explorer is renamed to dashboard"): one
project open at a time per window (PROMPT.md: "we now want it to be 1 per window" -- this panel
used to hold a tab strip for several open projects at once; opening a second one while one's
already open is now MainWindow's own "Open in this window / Open in new window" popup instead, see
:meth:`~in_reach.ide.main_window.MainWindow._open_project_with_popup`), three boxes for the active
project, top to bottom (PROMPT.md: "please move stats to the top of the panel") -- "Stats"
summarizing its build's own space usage and per-subsystem (Triggers/Conditions/Actions/Forge
Labels/Strings) counts against this project's own confirmed engine caps (see
:func:`~in_reach.app.rvt.settings_io.load_build_stats`/:func:`~in_reach.app.rvt.strings_io.
count_script_strings`/:data:`_MAX_TRIGGERS` et al.), "Quick Launch" (the Export File/Launch RVT/
View Compiled button row, plus "Built-in"/"Hot Reload" buttons that open the matching
:mod:`in_reach.app.system_verify`-resolved folder in the OS file explorer), and "Settings" pointed
at its own ``settings/`` subfolder. There used to be a fourth, generic "browse the whole project
folder" tree too; PROMPT.md asked for it to go now that Script/Settings cover the two subfolders
actually worth browsing by hand -- and later, a "Script" quick-access box exactly like Settings'
own, pointed at ``script/`` (whose only ever entry was ``output.txt``); PROMPT.md ("please also
remove output from script") asked for that to go too, now that the button row's own "View
Output.txt" is the supported way to look at it (see :meth:`ExplorerPanel.view_output_requested`).
The personal game/map variant folder trees that used to live here too (PROMPT.md: "remove the
Personal Map and Game Variants sections for now, they will later go in their own sidepanel") came
back in a different form as Quick Launch's own "Built-in" buttons above -- :mod:`in_reach.app.
system_verify` is still the one place their folders are actually resolved, same as the Welcome
tab's own Verify System Settings flow.

The Settings tree is a plain ``QFileSystemModel``/``QTreeView`` pair (so it reflects live disk
changes for free) with a custom icon provider (:mod:`in_reach.ide.file_icons`) swapped in for the
platform's own generic file icons.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QFileSystemModel, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from in_reach.app import new_project, system_verify
from in_reach.app.rvt import settings_io, strings_io
from in_reach.ide.collapsible_section import CollapsibleSection as _CollapsibleSection
from in_reach.ide.collapsible_section import SECTION_HEADER_STYLE
from in_reach.ide.file_icons import ExplorerIconProvider

_NO_PROJECT_TEXT = "No project opened yet -- create or load one from the Welcome tab."
_NO_STATS_TEXT = "No build stats yet -- Apply (or launch RVT) once this gametype compiles."

#: PROMPT.md: "in the dashboard please also make it so that it also shows the max amount of
#: tiggers, conditions, actions, forge labels and strings (if known)" -- these five are "known":
#: confirmed (not guessed) hard engine caps read directly out of the vendored ReachVariantTool C++
#: source (``game_variants/components/megalo/limits.h``) during this project's own prior research
#: (see ``TO_IMPLEMENT_(LATEST).md``'s "Engine-resource / counter caps" table) -- ``max_triggers``/
#: ``max_conditions``/``max_actions``/``max_script_labels`` ("script label" being the engine's own
#: internal name for a Forge label)/``max_variant_strings`` (the compiled string *table*'s own
#: capacity -- what :func:`~in_reach.app.rvt.strings_io.count_script_strings` counts entries
#: against, as opposed to ``max_string_ids``, a separate bytecode-level reference-index cap).
_MAX_TRIGGERS = 320
_MAX_CONDITIONS = 512
#: Briefly bumped to 1064 with an "unconfirmed" note (PROMPT.md: "increase max actions to 1064 ...
#: but we know its more than 1024") -- reverted the moment a real compile actually confirmed the
#: opposite: "The compiled script contains 1052 actions, but only a maximum of 1024 are allowed."
#: (the engine's own error text). 1024 was correct all along; back to a plain confirmed cap like
#: the other four, no asterisk/tooltip needed.
_MAX_ACTIONS = 1024
_MAX_FORGE_LABELS = 16
_MAX_STRINGS = 112
#: PROMPT.md: "also in dashboard please add progress bars for the remaining script counts (options,
#: traits, stats, widgets)" -- same confirmed-cap sourcing as the five above (vendored
#: ReachVariantTool ``game_variants/components/megalo/limits.h``,
#: ``Megalo::Limits::max_script_options``/``max_script_traits``/``max_script_stats``/
#: ``max_script_widgets``), not guessed -- ``max_script_traits``/``max_script_widgets`` in
#: particular are *not* the same numbers a plausible-looking guess would land on (16 and 4, not 8
#: and 11/12 -- the latter pair would come from conflating this cap with
#: ``ScriptedHUDWidget.position``'s own unrelated 0-11 placement-slot range).
_MAX_SCRIPT_OPTIONS = 16
_MAX_SCRIPT_TRAITS = 16
_MAX_SCRIPT_STATS = 4
_MAX_SCRIPT_WIDGETS = 4


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
#: section is expanded, since it's ``checked`` then -- see ``CollapsibleSection.__init__``) so the
#: header reads as plain text-plus-arrow, not a button.
#: PROMPT.md: "please update dashbaord so headings are bold and subheadings are italic" -- applies
#: to every _CollapsibleSection header (Stats/Quick Launch/Settings), on top of the plain-text/no-
#: background treatment above. See :mod:`in_reach.ide.collapsible_section` for the widget itself
#: (factored out once the Git panel needed the same treatment) -- this alias is kept so every
#: existing ``_SECTION_HEADER_STYLE`` reference in this file stays valid.
_SECTION_HEADER_STYLE = SECTION_HEADER_STYLE

#: PROMPT.md: "please remove the bubble outline around triggers conditions actions, forge lables
#: and strings" -- Fusion's own default QProgressBar is a rounded, bordered pill; this flattens it
#: to a plain rectangle so it stops reading as a bordered "bubble" over the Stats box's own text.
_FLAT_PROGRESS_BAR_STYLE = (
    "QProgressBar { border: none; border-radius: 0px; background-color: palette(alternate-base);"
    " text-align: center; }"
    "QProgressBar::chunk { background-color: palette(highlight); }"
)

#: PROMPT.md: "please remove the bubble connecting the project dashboard buttons so they do not
#: appear connected, and give them a background colour to make it clear they are buttons" -- the
#: Export RVT File/View Output.txt row (see ExplorerPanel.__init__). Each button gets its own
#: independent, clearly bounded box (never a shared border with its neighbor) with a real
#: background fill, rather than the flat/borderless look a plain QToolButton reads as against this
#: panel's own palette(base) background.
_DASHBOARD_BUTTON_STYLE = (
    "QToolButton { background-color: palette(button); border: 1px solid palette(mid);"
    " border-radius: 4px; padding: 4px 10px; }"
    # Was `palette(light)` -- none of the dark/Whiley themes' own JSON ever sets that QPalette role
    # (theme.py's build_palette() only assigns the roles it's explicitly given, so "light" is left
    # at Qt's own unrelated default, which reads as plain white) -- a hover turned the whole button
    # white, and with it white/near-white button text, unreadable. Highlighting with the theme's
    # own accent color instead is themed by construction, and matches how every other hover/select
    # state in this app already reads (menus, tabs, the activity bar's checked border).
    "QToolButton:hover { background-color: palette(highlight); color: palette(highlighted-text); }"
    "QToolButton:pressed { background-color: palette(mid); }"
)


#: PROMPT.md: "please then make a section 'Quick Launch' ... underneath that top row of buttons,
#: we want a subheader saying 'Built-in' ... then a subheader saying hot reload" -- a plain label,
#: one step down from a full _CollapsibleSection header (these aren't collapsible themselves, just
#: grouping labels within the Quick Launch section's own body). Later, PROMPT.md: "please update
#: dashbaord so headings are bold and subheadings are italic" -- italic distinguishes it from a
#: full section header's own bold treatment (see _SECTION_HEADER_STYLE) without it reading as just
#: as prominent.
_SUBHEADER_STYLE = "QLabel { font-style: italic; }"


def _subheader(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(_SUBHEADER_STYLE)
    return label


def _folder_button(text: str) -> QToolButton:
    """A button styled exactly like :attr:`ExplorerPanel.export_button` -- one of the "Built-in"/
    "Hot Reload" quick-launch buttons that opens a system_verify-resolved folder in the OS file
    explorer (MainWindow owns actually opening it, see :attr:`ExplorerPanel.
    open_builtin_folder_requested`), same division of labor as export_button/rvt_button/
    view_output_button above."""
    button = QToolButton()
    button.setText(text)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setAutoRaise(False)
    button.setStyleSheet(_DASHBOARD_BUTTON_STYLE)
    button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return button


class _StatBox(QFrame):
    """One of the Dashboard's five "sub" stats (Triggers/Conditions/Actions/Forge Labels/Strings)
    -- PROMPT.md: "please make each the 'sub' stats have a percentage bar and a border, aligning
    the 5 totals across two columns". A bordered frame (unlike :data:`_FLAT_PROGRESS_BAR_STYLE`'s
    own deliberately borderless progress bar -- PROMPT.md's own "please remove the bubble outline
    around triggers conditions actions" earlier asked for the *opposite* border-less treatment on a
    single combined line; splitting the same five counts out into their own individually-bordered
    boxes is a distinct, later ask, not a reversal of that one) wrapping just a progress bar, whose
    own text carries the label/count/percent, the same "text lives on the bar" convention
    :attr:`ExplorerPanel.stats_progress` already uses for the overall byte-usage figure.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("QFrame { border: 1px solid palette(mid); border-radius: 4px; }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(True)
        self.progress.setStyleSheet(_FLAT_PROGRESS_BAR_STYLE)
        layout.addWidget(self.progress)

    def set_value(self, label: str, count: int, maximum: int) -> None:
        percent = min(100, round(100 * count / maximum)) if maximum else 0
        self.progress.setValue(percent)
        self.progress.setFormat(f"{label}: {count}/{maximum} ({percent}%)")


class ExplorerPanel(QWidget):
    #: Emitted with a file's path when it's clicked in the Script or Settings box -- never for a
    #: directory (clicking one just expands/collapses it, QTreeView's own default behavior).
    file_activated = pyqtSignal(Path)

    #: Emitted with the newly active project's folder (or ``None`` once it closes) -- whenever a
    #: project opens or the current one closes.
    active_project_changed = pyqtSignal(object)

    #: Emitted with a project's folder right after it actually closes (PROMPT.md: "if project is
    #: closed in ide, if Reach Variant tool is open for that project it should be closed") -- what
    #: MainWindow needs to know which (if any) RVT process to terminate.
    project_closed = pyqtSignal(Path)

    #: PROMPT.md: "Underneath project tabs please add the following buttons: Export RVT File (on
    #: the left) and on the right: View Output.txt" -- MainWindow owns what each button actually
    #: does (compiling + a save-as dialog; regenerating and opening the locked output view).
    export_requested = pyqtSignal()
    view_output_requested = pyqtSignal()

    #: PROMPT.md: "we are removing locations, and rvt ... please add a button in between Export
    #: File and View Compiled ... for Launch RVT" -- replaces the activity bar's own former RVT
    #: launcher icon (see activity_bar.py's own history); MainWindow owns actually launching it
    #: (:meth:`~in_reach.ide.main_window.MainWindow.launch_rvt`), same division of labor as
    #: export_requested/view_output_requested above.
    launch_rvt_requested = pyqtSignal()

    #: PROMPT.md: "underneath that top row of buttons, we want a subheader saying 'Built-in' and
    #: buttons for[...] then a subheader saying hot reload[...] Open HotReload Folder" -- emitted
    #: with the :mod:`in_reach.app.system_verify` env key each button's own folder resolves under
    #: (e.g. :data:`~in_reach.app.system_verify.STANDARD_VARIANTS_KEY`); MainWindow owns actually
    #: resolving and opening it (it's the one that already knows this window's own ``root_dir``,
    #: see :meth:`~in_reach.ide.main_window.MainWindow._open_builtin_folder`), same division of
    #: labor as export_requested/launch_rvt_requested above.
    open_builtin_folder_requested = pyqtSignal(str)

    #: PROMPT.md: "please tweak the default explorer text scale to be +10%" -- relative to the
    #: app's own current zoom-scaled font (see :meth:`refresh_font_scale`), not a fixed point size.
    TEXT_SCALE = 1.1

    #: Section headers (Stats/Settings/Script) read 10% smaller than the rest of this panel's own
    #: (already +10%'d) text, so they read as "10% smaller than its neighbors" rather than landing
    #: back near the app's own plain size.
    HEADER_TEXT_SCALE = 0.9

    #: PROMPT.md: "in the dashboard panel please make the font for the settings jsons 10% bigger,
    #: they look too small in the sidebar" -- on top of :data:`TEXT_SCALE`, applied only to
    #: :attr:`settings_tree`'s own three rows (settings.json/script_settings.json/strings.json),
    #: not the rest of this panel.
    SETTINGS_TREE_TEXT_SCALE = 1.1

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        #: The gametype project folder the main tree currently points at, or ``None`` -- read by
        #: MainWindow.launch_rvt() to know which project's .bin to open RVT against.
        self.current_folder: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._no_project_label = QLabel(_NO_PROJECT_TEXT)
        self._no_project_label.setWordWrap(True)
        self._no_project_label.setEnabled(False)
        layout.addWidget(self._no_project_label)

        # A hidden widget in a QVBoxLayout doesn't claim its own stretch share, so with the
        # Stats/Quick Launch/Settings boxes below all hidden (no project open), this stands in for
        # that -- keeping the "no project" label pinned to the top instead of the layout centering
        # it in whatever space is left -- and collapses back to nothing the moment a project opens
        # (see _activate()).
        self._no_project_spacer = QWidget()
        layout.addWidget(self._no_project_spacer, 1)

        # PROMPT.md: "please also add a stats view into the dashboard" -- the active project's own
        # build/stats.autogenerated.json (space usage + script content counts), regenerated by
        # every decompile/resync/Apply for a multiplayer gametype (see
        # in_reach.app.rvt.decompile's own module docstring) -- there's nothing to show for a
        # blank/Firefight project that's never compiled, hence the placeholder. Placed first
        # (PROMPT.md: "put the stats at the top, then settings underneath ... then Script"; later,
        # "please move stats to the top of the panel" reconfirmed the same ordering once Quick
        # Launch was added below it) -- stats/quick-launch/settings all take stretch=0 so they sit
        # close together rather than each claiming a share of any extra vertical space; the trailing
        # addStretch() below is what absorbs that space instead, keeping the three boxes anchored to
        # the top of the panel.
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
        # PROMPT.md: "please make each the 'sub' stats have a percentage bar and a border, aligning
        # the 5 totals across two columns" -- each of Triggers/Conditions/Actions/Forge Labels/
        # Strings gets its own bordered _StatBox (a percentage bar whose own text carries the
        # label/count/max), laid out 2-per-row rather than the single word-wrap-off summary line
        # this used to be (see _StatBox's own docstring for why that's not a reversal of the
        # "remove the bubble outline" ask just above).
        self.trigger_stat = _StatBox()
        self.condition_stat = _StatBox()
        self.action_stat = _StatBox()
        self.forge_label_stat = _StatBox()
        self.string_stat = _StatBox()
        # PROMPT.md: "also in dashboard please add progress bars for the remaining script counts
        # (options, traits, stats, widgets)" -- same _StatBox treatment as the five above, just the
        # four ScriptContentCounts fields that didn't get one yet.
        self.script_option_stat = _StatBox()
        self.script_trait_stat = _StatBox()
        self.script_stat_stat = _StatBox()
        self.script_widget_stat = _StatBox()
        stats_grid = QGridLayout()
        stats_grid.setContentsMargins(0, 0, 0, 0)
        stats_grid.setSpacing(6)
        stats_grid.addWidget(self.trigger_stat, 0, 0)
        stats_grid.addWidget(self.condition_stat, 0, 1)
        stats_grid.addWidget(self.action_stat, 1, 0)
        stats_grid.addWidget(self.forge_label_stat, 1, 1)
        stats_grid.addWidget(self.string_stat, 2, 0)
        stats_grid.addWidget(self.script_option_stat, 2, 1)
        stats_grid.addWidget(self.script_trait_stat, 3, 0)
        stats_grid.addWidget(self.script_stat_stat, 3, 1)
        stats_grid.addWidget(self.script_widget_stat, 4, 0)
        self.stats_grid_widget = QWidget()
        self.stats_grid_widget.setLayout(stats_grid)
        self.stats_label = QLabel(_NO_STATS_TEXT)
        self.stats_label.setWordWrap(True)
        stats_body = QFrame()
        stats_layout = QVBoxLayout(stats_body)
        stats_layout.setContentsMargins(0, 4, 0, 0)
        stats_layout.setSpacing(4)
        stats_layout.addWidget(self.stats_progress)
        stats_layout.addWidget(self.stats_grid_widget)
        stats_layout.addWidget(self.stats_label)
        self.stats_section = _CollapsibleSection("Stats", stats_body, collapsed=False)
        self.stats_section.hide()
        layout.addWidget(self.stats_section)

        # PROMPT.md: "please then make a section 'Quick Launch' and add our buttons underneath" --
        # the same Export File/Launch RVT/View Compiled row this panel already had, now grouped
        # under its own collapsible section alongside the two new "Built-in"/"Hot Reload" button
        # grids below, rather than sitting bare at the top of the panel.
        quick_launch_body = QWidget()
        quick_launch_layout = QVBoxLayout(quick_launch_body)
        quick_launch_layout.setContentsMargins(0, 4, 0, 0)
        quick_launch_layout.setSpacing(8)

        # PROMPT.md: "Underneath project tabs please add the following buttons: Export RVT File
        # (on the left) and on the right: View Output.txt"; later, "please see side_bar_sizing.png
        # and make sure compiled is aligning next to the other buttons" -- Export File/Launch RVT on
        # the left, View Compiled pushed to the right by the stretch between them, exactly the
        # reference image's own row.
        button_row = QWidget()
        button_row_layout = QHBoxLayout(button_row)
        button_row_layout.setContentsMargins(0, 0, 0, 0)
        self.export_button = QToolButton()
        # PROMPT.md: "rename export RVT file to be 'Export File'".
        self.export_button.setText("Export File")
        self.export_button.setToolTip("Compile and save this gametype as a .bin or .mglo file")
        self.export_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_button.setAutoRaise(False)
        self.export_button.setStyleSheet(_DASHBOARD_BUTTON_STYLE)
        self.export_button.clicked.connect(self.export_requested.emit)
        button_row_layout.addWidget(self.export_button)
        # PROMPT.md: "please add a button in between Export File and View Compiled ... for Launch
        # RVT" -- disabled with no project open, same as the activity bar's own former RVT icon
        # (see MainWindow.launch_rvt's own docstring for why).
        self.rvt_button = QToolButton()
        self.rvt_button.setText("Launch RVT")
        self.rvt_button.setToolTip("Launch ReachVariantTool")
        self.rvt_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rvt_button.setAutoRaise(False)
        self.rvt_button.setStyleSheet(_DASHBOARD_BUTTON_STYLE)
        self.rvt_button.setEnabled(False)
        self.rvt_button.clicked.connect(self.launch_rvt_requested.emit)
        button_row_layout.addWidget(self.rvt_button)
        button_row_layout.addStretch(1)
        self.view_output_button = QToolButton()
        # PROMPT.md: "View Compiled (renamed from View Compiled.txt)".
        self.view_output_button.setText("View Compiled")
        self.view_output_button.setToolTip("Open a read-only view of this project's compiled Megalo script")
        self.view_output_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.view_output_button.setAutoRaise(False)
        self.view_output_button.setStyleSheet(_DASHBOARD_BUTTON_STYLE)
        self.view_output_button.clicked.connect(self.view_output_requested.emit)
        button_row_layout.addWidget(self.view_output_button)
        self.button_row = button_row
        quick_launch_layout.addWidget(self.button_row)

        # PROMPT.md: "underneath that top row of buttons, we want a subheader saying 'Built-in' and
        # buttons for: col a: Open Game Variants/Open Hopper Variants/Open User Games, col b: Open
        # Map Variants/Open Hopper Maps/Open User Maps" -- each resolves the matching
        # system_verify-checked folder against this window's own project-root .env (MainWindow owns
        # the actual lookup+open, see open_builtin_folder_requested's own docstring).
        quick_launch_layout.addWidget(_subheader("Built-in"))
        self.game_variants_button = _folder_button("Open Game Variants")
        self.map_variants_button = _folder_button("Open Map Variants")
        self.hopper_variants_button = _folder_button("Open Hopper Variants")
        self.hopper_maps_button = _folder_button("Open Hopper Maps")
        self.user_games_button = _folder_button("Open User Games")
        self.user_maps_button = _folder_button("Open User Maps")
        for button, key in (
            (self.game_variants_button, system_verify.STANDARD_VARIANTS_KEY),
            (self.map_variants_button, system_verify.STANDARD_MAP_VARIANTS_KEY),
            (self.hopper_variants_button, system_verify.HOPPER_VARIANTS_KEY),
            (self.hopper_maps_button, system_verify.HOPPER_MAP_VARIANTS_KEY),
            (self.user_games_button, system_verify.PERSONAL_VARIANTS_KEY),
            (self.user_maps_button, system_verify.PERSONAL_MAPS_KEY),
        ):
            button.clicked.connect(lambda _checked=False, k=key: self.open_builtin_folder_requested.emit(k))
        builtin_grid = QGridLayout()
        builtin_grid.setContentsMargins(0, 0, 0, 0)
        builtin_grid.setSpacing(6)
        builtin_grid.addWidget(self.game_variants_button, 0, 0)
        builtin_grid.addWidget(self.map_variants_button, 0, 1)
        builtin_grid.addWidget(self.hopper_variants_button, 1, 0)
        builtin_grid.addWidget(self.hopper_maps_button, 1, 1)
        builtin_grid.addWidget(self.user_games_button, 2, 0)
        builtin_grid.addWidget(self.user_maps_button, 2, 1)
        builtin_grid_widget = QWidget()
        builtin_grid_widget.setLayout(builtin_grid)
        quick_launch_layout.addWidget(builtin_grid_widget)

        # PROMPT.md: "then a subheader saying hot reload: col a: Open HotReload Folder".
        quick_launch_layout.addWidget(_subheader("Hot Reload"))
        self.hotreload_button = _folder_button("Open HotReload Folder")
        self.hotreload_button.clicked.connect(
            lambda: self.open_builtin_folder_requested.emit(system_verify.HOTRELOAD_KEY)
        )
        quick_launch_layout.addWidget(self.hotreload_button)

        self.quick_launch_section = _CollapsibleSection("Quick Launch", quick_launch_body, collapsed=False)
        self.quick_launch_section.hide()
        layout.addWidget(self.quick_launch_section)

        # Dedicated quick-access box for the active project's own settings/ subfolder, open by
        # default since it's central to the active project. Hidden entirely with no project open
        # (see _activate()).
        self.settings_tree, self._settings_model = _new_tree()
        self.settings_section = _CollapsibleSection("Settings", self.settings_tree, collapsed=False)
        self.settings_section.hide()
        layout.addWidget(self.settings_section)

        layout.addStretch(1)

        self.settings_tree.clicked.connect(
            lambda index: self._on_tree_clicked(self._settings_model, index)
        )

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
        self.settings_section.set_header_font(header_font)
        self.stats_section.set_header_font(header_font)
        self.quick_launch_section.set_header_font(header_font)

        settings_tree_font = QFont(font)
        settings_tree_font.setPointSizeF(font.pointSizeF() * self.SETTINGS_TREE_TEXT_SCALE)
        self.settings_tree.setFont(settings_tree_font)

        _cap_tree_rows(self.settings_tree, 3)  # settings/settings.json, script_settings.json, strings.json

    def _on_tree_clicked(self, model: QFileSystemModel, index: QModelIndex) -> None:
        if not index.isValid() or model.isDir(index):
            return
        self.file_activated.emit(Path(model.filePath(index)))

    # -- the main project tree -------------------------------------------------------------------

    def open_project(self, folder: Path) -> None:
        """Points this panel at ``folder`` as the one open project (PROMPT.md: "1 per window") --
        replacing whatever was open before, if anything. A no-op for a folder that doesn't actually
        exist, so a bad path can't clobber whatever's already open. Also a no-op (skips the
        redundant re-``_activate``) if ``folder`` is already the active project.

        Emits :attr:`project_closed` for the *previous* project first when it's being replaced --
        with only one project open at a time, replacing it is closing it, and MainWindow relies on
        that signal to terminate its own RVT process (PROMPT.md: "if project is closed in ide, if
        Reach Variant tool is open for that project it should be closed").
        """
        if not folder.is_dir() or folder == self.current_folder:
            return
        if self.current_folder is not None:
            self.project_closed.emit(self.current_folder)
        self._activate(folder)

    def close_project(self, folder: Path) -> None:
        """Closes ``folder`` if it's the currently active project -- a no-op otherwise (there's
        nothing else open to close, PROMPT.md: "1 per window")."""
        if folder != self.current_folder:
            return
        self.project_closed.emit(folder)
        self._activate(None)

    def close_active_project(self) -> None:
        """Closes whichever project is currently open -- "Close Project" (File menu). A no-op with
        no project open."""
        if self.current_folder is not None:
            self.close_project(self.current_folder)

    def _activate(self, folder: Path | None) -> None:
        """Points the main tree (and the Script/Settings/Stats boxes) at ``folder`` (the newly
        active gametype project's own folder), or back to the "no project" placeholder for
        ``None``."""
        self.current_folder = folder
        has_project = folder is not None and folder.is_dir()
        self._no_project_label.setVisible(not has_project)
        self._no_project_spacer.setVisible(not has_project)
        self.quick_launch_section.setVisible(has_project)
        self.settings_section.setVisible(has_project)
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

        has_counts = stats is not None
        self.stats_progress.setVisible(has_counts)
        self.stats_grid_widget.setVisible(has_counts or strings_count is not None)
        self.trigger_stat.setVisible(has_counts)
        self.condition_stat.setVisible(has_counts)
        self.action_stat.setVisible(has_counts)
        self.forge_label_stat.setVisible(has_counts)
        self.string_stat.setVisible(strings_count is not None)
        self.script_option_stat.setVisible(has_counts)
        self.script_trait_stat.setVisible(has_counts)
        self.script_stat_stat.setVisible(has_counts)
        self.script_widget_stat.setVisible(has_counts)
        if has_counts:
            self.stats_progress.setValue(round(stats.space.percent))
            # PROMPT.md: "please combine the percentage used bar to be: 10,874 / 20520 Bytes used
            # (53%) (and with the progress bar background)" -- shown as the bar's own text over its
            # fill, rather than a separate label line.
            self.stats_progress.setFormat(
                f"{stats.space.bytes_used:,} / {stats.space.bytes_max:,} Bytes used ({stats.space.percent:.0f}%)"
            )
            counts = stats.counts
            # PROMPT.md: "please also make it so that it also shows the max amount of tiggers,
            # conditions, actions, forge labels and strings (if known)" -- see _MAX_TRIGGERS et al.
            self.trigger_stat.set_value("Triggers", counts.triggers, _MAX_TRIGGERS)
            self.condition_stat.set_value("Conditions", counts.conditions, _MAX_CONDITIONS)
            self.action_stat.set_value("Actions", counts.actions, _MAX_ACTIONS)
            self.forge_label_stat.set_value("Forge Labels", counts.forge_labels, _MAX_FORGE_LABELS)
            # PROMPT.md: "also in dashboard please add progress bars for the remaining script
            # counts (options, traits, stats, widgets)" -- see _MAX_SCRIPT_OPTIONS et al.
            self.script_option_stat.set_value("Options", counts.script_options, _MAX_SCRIPT_OPTIONS)
            self.script_trait_stat.set_value("Traits", counts.script_traits, _MAX_SCRIPT_TRAITS)
            self.script_stat_stat.set_value("Stats", counts.script_stats, _MAX_SCRIPT_STATS)
            self.script_widget_stat.set_value("Widgets", counts.script_widgets, _MAX_SCRIPT_WIDGETS)
        if strings_count is not None:
            self.string_stat.set_value("Strings", strings_count, _MAX_STRINGS)
        self.stats_label.setVisible(not has_counts and strings_count is None)
        self.stats_label.setText(_NO_STATS_TEXT)
