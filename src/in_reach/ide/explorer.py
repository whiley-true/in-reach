"""The primary sidebar's Explorer view: the currently open gametype project's own folder tree, and
-- collapsed by default, since they're secondary to it -- two more folder trees for the personal
game/map variant folders :mod:`in_reach.app.system_verify` resolves.

Each tree is a plain ``QFileSystemModel``/``QTreeView`` pair (so it reflects live disk changes for
free) with a custom icon provider (:mod:`in_reach.ide.file_icons`) swapped in for the platform's
own generic file icons.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QFileSystemModel
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QSizePolicy,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from in_reach.app import env_file, system_verify
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

    @property
    def expanded(self) -> bool:
        return self._toggle.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self._toggle.setChecked(expanded)


class ExplorerPanel(QWidget):
    #: Emitted with a file's path when it's clicked in any of the three trees -- never for a
    #: directory (clicking one just expands/collapses it, QTreeView's own default behavior).
    file_activated = pyqtSignal(Path)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._env_project_dir: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._no_project_label = QLabel(_NO_PROJECT_TEXT)
        self._no_project_label.setWordWrap(True)
        self._no_project_label.setEnabled(False)
        layout.addWidget(self._no_project_label)

        self.project_tree, self._project_model = _new_tree()
        self.project_tree.hide()
        layout.addWidget(self.project_tree, 1)

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

        for tree, model in (
            (self.project_tree, self._project_model),
            (self.personal_variants_tree, self._personal_variants_model),
            (self.personal_maps_tree, self._personal_maps_model),
        ):
            tree.clicked.connect(lambda index, m=model: self._on_tree_clicked(m, index))

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

    def set_project_folder(self, folder: Path | None) -> None:
        """Points the main tree at ``folder`` (the current gametype project's own folder), or back
        to the "no project" placeholder for ``None``."""
        has_project = folder is not None and folder.is_dir()
        self._no_project_label.setVisible(not has_project)
        self.project_tree.setVisible(has_project)
        _point_tree_at(self.project_tree, self._project_model, folder)

    # -- the two personal-folder sections ----------------------------------------------------------

    def set_env_project_dir(self, project_dir: Path | None) -> None:
        """Points the two personal-folder sections at whatever
        :data:`~in_reach.app.system_verify.PERSONAL_VARIANTS_KEY`/
        :data:`~in_reach.app.system_verify.PERSONAL_MAPS_KEY` currently resolve to in
        ``project_dir``'s own ``.env`` -- the project's ``.in-reach`` folder, not the gametype
        project folder :meth:`set_project_folder` points the main tree at.

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
