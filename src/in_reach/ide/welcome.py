"""The Welcome tab shown when the editor first opens -- modelled after VSCode's own Welcome page.

Below the title/subtitle (and the running version plus the folder in-reach was opened against) the
page divides into four quadrants: Start and Recent down the left, Verify System Settings and Help &
Walkthroughs down the right.

Everything on the page is a view of one file -- the project's ``.in-reach/.env``. The verify
quadrant's "N of 12 verified" count is a summary of that same file, not a checklist of its own --
see :class:`~in_reach.ide.verify_dialog.VerifyDialog` for the actual step-by-step run, and
:class:`~in_reach.ide.settings_info_dialog.SettingsInfoDialog` (its own "What is this?" button) for
why any of this is asked for in the first place. The "New Project from ..." actions enable because
the variant-folder steps behind them are verified; Recent is a key of its own. That's why
:meth:`WelcomeTab.refresh` is all it takes to bring the whole page back in sync after a verify run,
a "Clear Entries", or a new project -- see :mod:`in_reach.app.system_verify` for what fills those
keys in.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import in_reach
from in_reach.app import env_file, new_project, project, recent, system_verify
from in_reach.ide import icons
from in_reach.ide.new_project_dialog import NewProjectDialog
from in_reach.ide.settings_info_dialog import SettingsInfoDialog
from in_reach.ide.verify_dialog import VerifyDialog

_ICON_SIZE = 16

_CUSTOM_TAB_PLACEHOLDER = (
    "For a non-Steam install of Halo: MCC. Nothing to configure here yet -- verify against "
    "Steam (Halo MCC) for now."
)

# Placeholders only: there's no walkthrough content in this repo yet, so these advertise what's
# coming rather than pretending to open something.
_HELP_ENTRIES = (
    "Getting started with in-reach",
    "Writing your first Megalo script",
    "Compiling and hot-reloading a gametype",
    "Sharing a gametype with other players",
)


def _flat_button(label: str, icon_name: str | None = None) -> QPushButton:
    """A borderless, left-aligned action row -- the Welcome page's own "link" affordance."""
    button = QPushButton(f" {label}" if icon_name else label)
    if icon_name:
        button.setIcon(icons.icon(icon_name, size=_ICON_SIZE))
    button.setFlat(True)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setStyleSheet("text-align: left; padding: 2px 0px;")
    return button


class WelcomeTab(QWidget):
    #: Emitted with a gametype project folder whenever one is created or opened from this page.
    project_opened = pyqtSignal(Path)

    def __init__(self, parent: QWidget | None = None, *, root_dir: Path | None = None) -> None:
        """
        Args:
            parent: Owning widget.
            root_dir: The folder in-reach was opened against -- shown in the header, and the parent
                of both the ``.in-reach`` project folder this page reads and any new gametype
                project it creates. Defaults to the current working directory.
        """
        super().__init__(parent)
        self.root_dir = root_dir or Path.cwd()
        self.project_dir = project.get_project_dir(self.root_dir)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(24)
        layout.addLayout(self._build_header())

        grid = QGridLayout()
        grid.setHorizontalSpacing(48)
        grid.setVerticalSpacing(28)
        grid.addWidget(self._build_start_quadrant(), 0, 0)
        grid.addWidget(self._build_verify_quadrant(), 0, 1)
        grid.addWidget(self._build_recent_quadrant(), 1, 0)
        grid.addWidget(self._build_help_quadrant(), 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        layout.addLayout(grid, 1)

        self.refresh()

    # -- construction ---------------------------------------------------------------------------

    def _build_header(self) -> QVBoxLayout:
        header = QVBoxLayout()
        header.setSpacing(4)

        title = QLabel("In-Reach")
        title_font = title.font()
        title_font.setPointSize(title_font.pointSize() + 12)
        title_font.setBold(True)
        title.setFont(title_font)
        header.addWidget(title)

        subtitle = QLabel("Halo Reach Script Manager")
        subtitle_font = subtitle.font()
        subtitle_font.setPointSize(subtitle_font.pointSize() + 2)
        subtitle.setFont(subtitle_font)
        header.addWidget(subtitle)

        self.version_label = QLabel(f"v{in_reach.__version__}")
        self.path_label = QLabel(str(self.root_dir))
        self.path_label.setToolTip(str(self.root_dir))
        for label in (self.version_label, self.path_label):
            # Renders in the theme's own disabled-text color (see Theme.build_palette), which is
            # exactly the "secondary line" shade wanted here -- and follows a live theme switch,
            # which a hardcoded hex in a stylesheet wouldn't.
            label.setEnabled(False)
            header.addWidget(label)
        return header

    def _build_quadrant(self, heading: str) -> tuple[QWidget, QVBoxLayout]:
        frame = QFrame()
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        label = QLabel(heading)
        heading_font = label.font()
        heading_font.setBold(True)
        label.setFont(heading_font)
        outer.addWidget(label)

        body = QVBoxLayout()
        body.setSpacing(2)
        outer.addLayout(body)
        outer.addStretch(1)
        return frame, body

    def _build_start_quadrant(self) -> QWidget:
        frame, body = self._build_quadrant("Start")

        self.new_blank_button = _flat_button("New Blank Project", "new_file")
        self.new_builtin_button = _flat_button("New Project from In-Built Gametype Variant", "new_file")
        self.new_personal_button = _flat_button("New Project from Personal Gametype Variant", "new_file")
        self.load_project_button = _flat_button("Load Project", "explorer")
        self.import_pickle_button = _flat_button("Import Project from Pickle File", "explorer")

        self.new_blank_button.clicked.connect(self.new_blank_project)
        self.new_builtin_button.clicked.connect(self.new_built_in_project)
        self.new_personal_button.clicked.connect(self.new_personal_project)
        self.load_project_button.clicked.connect(self.load_project)
        # Stubbed for now, per PROMPT.md -- disabled rather than wired to a no-op, so the page
        # never implies it did something.
        self.import_pickle_button.setEnabled(False)
        self.import_pickle_button.setToolTip("Not implemented yet.")

        for button in (
            self.new_blank_button,
            self.new_builtin_button,
            self.new_personal_button,
            self.load_project_button,
            self.import_pickle_button,
        ):
            body.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
        return frame

    def _build_recent_quadrant(self) -> QWidget:
        frame, body = self._build_quadrant("Recent")
        self._recent_layout = body
        self._recent_empty_label = QLabel("No recent projects yet.")
        self._recent_empty_label.setEnabled(False)
        body.addWidget(self._recent_empty_label)
        return frame

    def _build_verify_quadrant(self) -> QWidget:
        frame, body = self._build_quadrant("Verify System Settings")

        tabs = QTabWidget()
        tabs.addTab(self._build_steam_verify_page(), "Steam (Halo MCC)")
        tabs.addTab(self._build_custom_verify_page(), "Custom")
        self.verify_tabs = tabs
        body.addWidget(tabs)
        return frame

    def _build_steam_verify_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(12, 12, 12, 12)
        page_layout.setSpacing(8)

        # A summary rather than the twelve-item checklist itself -- see VerifyDialog for the actual
        # step-by-step results, and SettingsInfoDialog (below) for what each step is even for.
        self.verified_count_label = QLabel()
        page_layout.addWidget(self.verified_count_label)
        page_layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.verify_now_button = QPushButton("Verify Now")
        self.verify_now_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.verify_now_button.clicked.connect(self.verify_now)
        self.clear_entries_button = QPushButton("Clear Entries")
        self.clear_entries_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_entries_button.clicked.connect(self.clear_entries)
        self.what_is_this_button = QPushButton("What is this?")
        self.what_is_this_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.what_is_this_button.clicked.connect(self.show_settings_info)
        buttons.addWidget(self.verify_now_button)
        buttons.addWidget(self.clear_entries_button)
        buttons.addWidget(self.what_is_this_button)
        buttons.addStretch(1)
        page_layout.addLayout(buttons)
        return page

    def _build_custom_verify_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(12, 12, 12, 12)
        placeholder = QLabel(_CUSTOM_TAB_PLACEHOLDER)
        placeholder.setWordWrap(True)
        placeholder.setEnabled(False)
        page_layout.addWidget(placeholder)
        page_layout.addStretch(1)
        return page

    def _build_help_quadrant(self) -> QWidget:
        frame, body = self._build_quadrant("Help & Walkthroughs")
        for entry in _HELP_ENTRIES:
            button = _flat_button(entry)
            button.setEnabled(False)
            button.setToolTip("Not written yet.")
            body.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
        return frame

    # -- state ----------------------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-reads the ``.env`` and brings the verify count, the Start actions and Recent back in sync."""
        verified = system_verify.verified_keys(self.project_dir)
        verified_count = sum(1 for is_set in verified.values() if is_set)
        self.verified_count_label.setText(f"{verified_count} of {len(verified)} settings verified.")

        self.new_builtin_button.setEnabled(
            verified.get(system_verify.STANDARD_VARIANTS_KEY, False)
            and verified.get(system_verify.HOPPER_VARIANTS_KEY, False)
        )
        self.new_builtin_button.setToolTip(
            ""
            if self.new_builtin_button.isEnabled()
            else "Verify the standard and hopper game variant folders first."
        )
        self.new_personal_button.setEnabled(verified.get(system_verify.PERSONAL_VARIANTS_KEY, False))
        self.new_personal_button.setToolTip(
            "" if self.new_personal_button.isEnabled() else "Verify the personal game variants folder first."
        )

        self._rebuild_recent()

    def _rebuild_recent(self) -> None:
        while self._recent_layout.count() > 1:  # index 0 is the "nothing yet" label
            item = self._recent_layout.takeAt(1)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        entries = recent.list_recent(self.project_dir)
        self._recent_empty_label.setVisible(not entries)
        for path in entries:
            button = _flat_button(path.name, "explorer")
            button.setToolTip(str(path))
            button.clicked.connect(lambda _checked=False, p=path: self._open_project(p))
            self._recent_layout.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)

    # -- verify actions --------------------------------------------------------------------------

    def verify_now(self) -> None:
        """Opens the step-by-step verification popout, re-ticking the checklist once it's done."""
        dialog = VerifyDialog(self.project_dir, self)
        dialog.run_finished.connect(self.refresh)
        dialog.start()
        dialog.exec()
        self.refresh()

    def clear_entries(self) -> None:
        """Blanks every verified value, resetting the count back to zero."""
        system_verify.clear_entries(self.project_dir)
        self.refresh()

    def show_settings_info(self) -> None:
        """Opens the "What is this?" explainer for why these settings are asked for at all."""
        SettingsInfoDialog(self).exec()

    # -- start actions ---------------------------------------------------------------------------

    def new_blank_project(self) -> None:
        self._create_project_from(NewProjectDialog(self))

    def new_built_in_project(self) -> None:
        values = system_verify.verified_keys(self.project_dir)
        if not (
            values.get(system_verify.STANDARD_VARIANTS_KEY) and values.get(system_verify.HOPPER_VARIANTS_KEY)
        ):
            return
        env_values = self._env_values()
        variants = [
            (f"Standard: {name}", path)
            for name, path in new_project.list_variants(Path(env_values[system_verify.STANDARD_VARIANTS_KEY]))
        ] + [
            (f"Hopper: {name}", path)
            for name, path in new_project.list_variants(Path(env_values[system_verify.HOPPER_VARIANTS_KEY]))
        ]
        if not variants:
            QMessageBox.information(self, "in-reach", "No game variants found in those folders.")
            return
        self._create_project_from(NewProjectDialog(self, variants=variants, source_label="Built-in variant"))

    def new_personal_project(self) -> None:
        folder = self._env_values().get(system_verify.PERSONAL_VARIANTS_KEY, "")
        if not folder:
            return
        variants = new_project.list_variants(Path(folder))
        if not variants:
            QMessageBox.information(self, "in-reach", f"No game variants found in {folder}.")
            return
        self._create_project_from(NewProjectDialog(self, variants=variants, source_label="Personal variant"))

    def load_project(self) -> None:
        """Opens a folder picker and adopts whatever's chosen as the current project."""
        chosen = self.ask_project_folder()
        if chosen:
            self._open_project(Path(chosen))

    def _create_project_from(self, dialog: NewProjectDialog) -> None:
        """Runs ``dialog`` and, if it's accepted, scaffolds the project it describes."""
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            folder = new_project.create_gametype_project(
                self.project_dir, dialog.title(), dialog.description(), dialog.selected_variant()
            )
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "in-reach", f"Couldn't create the project:\n{exc}")
            return
        self._open_project(folder)

    def _open_project(self, folder: Path) -> None:
        recent.add_recent(self.project_dir, folder)
        self.refresh()
        self.project_opened.emit(folder)

    def _env_values(self) -> dict[str, str]:
        return env_file.get_env_values(system_verify.env_path_for(self.project_dir))

    def ask_project_folder(self) -> str:
        """Kept as its own method purely as a test seam (see ``tabs.py``'s ``_ask_save_path``)."""
        return QFileDialog.getExistingDirectory(self, "Load Project", str(self.root_dir))
