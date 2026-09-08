"""The title/description/category prompt behind the Welcome tab's three "New ... Project" actions.

The same dialog serves all three: pass ``variants`` (a game-variants folder's contents, as returned
by :func:`in_reach.app.new_project.list_variants`) to add the "start from this variant" chooser, or
leave it out for a blank project. Create stays disabled until the title is one
:func:`~in_reach.app.new_project.is_valid_title` will accept -- non-empty, within length, nothing
more (PROMPT.md: the title no longer has to be a legal Windows folder name, since the project
folder is a generated id now, not the title -- see that function's own docstring).
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from in_reach.app import new_project
from in_reach.app.categories import EngineCategory, display_name

_TITLE_HELP = f"1-{new_project.MAX_TITLE_LENGTH} characters."


class NewProjectDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        variants: list[tuple[str, Path]] | None = None,
        source_label: str = "Start from",
    ) -> None:
        """
        Args:
            parent: Owning widget.
            variants: ``(name, path)`` pairs to offer as the project's starting variant. ``None``
                (or empty) drops the chooser entirely -- a blank project.
            source_label: Field label for that chooser, e.g. ``"Built-in variant"``.
        """
        super().__init__(parent)
        self._variants = variants or []

        self.setWindowTitle("New Project")
        self.setModal(True)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(8)

        self.title_edit = QLineEdit()
        self.title_edit.setMaxLength(new_project.MAX_TITLE_LENGTH)
        self.title_edit.setPlaceholderText("My Gametype")
        self.title_edit.textChanged.connect(self._on_title_changed)
        form.addRow("Title", self.title_edit)

        self.description_edit = QLineEdit()
        self.description_edit.setMaxLength(new_project.MAX_DESCRIPTION_LENGTH)
        self.description_edit.setPlaceholderText("Optional")
        form.addRow("Description", self.description_edit)

        self.category_combo = QComboBox()
        for category in EngineCategory:
            self.category_combo.addItem(display_name(category), category)
        form.addRow("Category", self.category_combo)

        self.variant_combo = QComboBox()
        for name, path in self._variants:
            self.variant_combo.addItem(name, str(path))
        if self._variants:
            form.addRow(source_label, self.variant_combo)
        else:
            self.variant_combo.hide()

        layout.addLayout(form)

        self.title_help_label = QLabel(_TITLE_HELP)
        self.title_help_label.setWordWrap(True)
        layout.addWidget(self.title_help_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Create")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._on_title_changed(self.title_edit.text())

    def _on_title_changed(self, text: str) -> None:
        valid = new_project.is_valid_title(text.strip())
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valid)
        # Stays visible the whole time -- it's persistent guidance ("here's the rule"), not a
        # one-off error that should vanish the instant the field happens to pass; the field starts
        # out invalid (empty) precisely so this is what a user sees first, not something that
        # flickers in and out as they type. Only its emphasis changes: full contrast while the
        # current text wouldn't be accepted, muted to the theme's own disabled-text shade (see
        # welcome.py's version/path labels for the same pattern) once it would.
        self.title_help_label.setEnabled(not valid)

    def title(self) -> str:
        return self.title_edit.text().strip()

    def description(self) -> str:
        return self.description_edit.text().strip()

    def category(self) -> EngineCategory:
        return self.category_combo.currentData()

    def selected_variant(self) -> Path | None:
        """The chosen starting variant, or ``None`` for a blank project."""
        if not self._variants:
            return None
        data = self.variant_combo.currentData()
        return Path(data) if data else None
