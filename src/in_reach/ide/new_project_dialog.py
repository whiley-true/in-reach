"""The title/description/category prompt behind the Welcome tab's three "New ... Project" actions.

The same dialog serves all three: pass ``variants`` (a game-variants folder's contents, as returned
by :func:`in_reach.app.new_project.list_variants`) to add the "start from this variant" chooser, or
pass ``ask_game_type=True`` instead for a blank project -- a Multiplayer/Firefight picker replaces
the variant chooser, since a blank project still needs *something* to decompile/open in RVT with
(:func:`selected_variant` resolves one of in-reach's own bundled blank templates in that case, never
``None``). Firefight has no Category/Icon of its own, so picking it hides the Category row entirely
rather than offering a choice that wouldn't mean anything. Create stays disabled until the title is
one :func:`~in_reach.app.new_project.is_valid_title` will accept -- non-empty, within length,
nothing more (PROMPT.md: the title no longer has to be a legal Windows folder name, since the
project folder is a generated id now, not the title -- see that function's own docstring).
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from in_reach.app import blank_variant, new_project
from in_reach.app.categories import EngineCategory, display_name

_TITLE_HELP = f"1-{new_project.MAX_TITLE_LENGTH} characters."

# PROMPT.md: "please limit the size of the dropdown that opens for built-in variant and personal
# variant (as at present they can fill the entire screen)" -- a project folder with a few hundred
# .bin files would otherwise open a popup taller than the screen; this caps it to a scrollable list.
_VARIANT_DROPDOWN_MAX_VISIBLE_ITEMS = 12


class NewProjectDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        variants: list[tuple[str, Path]] | None = None,
        source_label: str = "Start from",
        ask_game_type: bool = False,
    ) -> None:
        """
        Args:
            parent: Owning widget.
            variants: ``(name, path)`` pairs to offer as the project's starting variant. ``None``
                (or empty) drops the chooser entirely -- a blank project.
            source_label: Field label for that chooser, e.g. ``"Built-in variant"``.
            ask_game_type: Whether to show the Multiplayer/Firefight picker -- only the "New Blank
                Project" flow needs this (PROMPT.md: "blank gametypes should also ask if
                multiplayer or firefight"); the other two flows already know their game type from
                the ``.bin`` they're starting from. Firefight has no Category/Icon of its own
                (PROMPT.md: "firefight doesnt get categorys and icons"), so picking it hides the
                Category row rather than offering a choice that wouldn't mean anything.
        """
        super().__init__(parent)
        self._variants = variants or []
        self._ask_game_type = ask_game_type

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
        self.description_edit.textChanged.connect(self._on_description_changed)
        self.description_edit.installEventFilter(self)
        form.addRow("Description", self.description_edit)

        if self._ask_game_type:
            self.multiplayer_radio = QRadioButton("Multiplayer")
            self.firefight_radio = QRadioButton("Firefight")
            self.multiplayer_radio.setChecked(True)
            game_type_row = QHBoxLayout()
            game_type_row.addWidget(self.multiplayer_radio)
            game_type_row.addWidget(self.firefight_radio)
            game_type_row.addStretch()
            self.firefight_radio.toggled.connect(self._on_game_type_changed)
            form.addRow("Game Type", game_type_row)

        self.category_combo = QComboBox()
        for category in EngineCategory:
            self.category_combo.addItem(display_name(category), category)
        form.addRow("Category", self.category_combo)

        self.variant_combo = QComboBox()
        self.variant_combo.setMaxVisibleItems(_VARIANT_DROPDOWN_MAX_VISIBLE_ITEMS)
        for name, path in self._variants:
            self.variant_combo.addItem(name, str(path))
        if self._variants:
            # Editable + a filtering completer turns this into a type-to-search combo (PROMPT.md)
            # -- NoInsert keeps typing from adding whatever's typed as a new, bogus entry.
            self.variant_combo.setEditable(True)
            self.variant_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            completer = QCompleter([name for name, _path in self._variants], self.variant_combo)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
            self.variant_combo.setCompleter(completer)
            form.addRow(source_label, self.variant_combo)
        else:
            self.variant_combo.hide()

        self._form = form
        layout.addLayout(form)

        self.title_help_label = QLabel(_TITLE_HELP)
        self.title_help_label.setWordWrap(True)
        layout.addWidget(self.title_help_label)

        self.description_help_label = QLabel()
        self.description_help_label.setWordWrap(True)
        self.description_help_label.setEnabled(False)
        layout.addWidget(self.description_help_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Create")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._on_title_changed(self.title_edit.text())
        self._on_description_changed(self.description_edit.text())
        if self._ask_game_type:
            self._on_game_type_changed(self.firefight_radio.isChecked())

    def _on_game_type_changed(self, firefight_checked: bool) -> None:
        """Firefight has no Category/Icon of its own (see this class's own docstring), so picking
        it hides the Category row rather than leaving a choice that wouldn't mean anything."""
        self._form.setRowVisible(self.category_combo, not firefight_checked)

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

    def _on_description_changed(self, text: str) -> None:
        self.description_help_label.setText(f"{len(text)}/{new_project.MAX_DESCRIPTION_LENGTH} characters")

    def eventFilter(self, obj: object, event) -> bool:  # noqa: ANN001 -- QEvent
        # Muted (the same disabled-text convention as title_help_label) until the description
        # field is actually focused -- PROMPT.md: "should show 0-137 characters ... when
        # description is highlighted" -- rather than competing for attention the whole time the
        # way the title's own always-relevant validity rule does.
        if obj is self.description_edit:
            if event.type() == QEvent.Type.FocusIn:
                self.description_help_label.setEnabled(True)
            elif event.type() == QEvent.Type.FocusOut:
                self.description_help_label.setEnabled(False)
        return super().eventFilter(obj, event)

    def title(self) -> str:
        return self.title_edit.text().strip()

    def description(self) -> str:
        return self.description_edit.text().strip()

    def is_firefight(self) -> bool:
        """Whether the Firefight radio is picked -- always ``False`` when this dialog wasn't built
        with ``ask_game_type=True`` (the built-in/personal-variant flows already know their game
        type from the ``.bin`` they're starting from)."""
        return self._ask_game_type and self.firefight_radio.isChecked()

    def category(self) -> EngineCategory:
        # Firefight has no Category of its own -- see this class's own docstring -- so its
        # (hidden) combobox value is never meaningful; report "none" rather than whatever it was
        # last left showing.
        if self.is_firefight():
            return EngineCategory.none
        return self.category_combo.currentData()

    def selected_variant(self) -> Path | None:
        """The chosen starting variant.

        A blank project (``ask_game_type=True``) still needs *something* to decompile/open in RVT
        with, so this resolves to in-reach's own bundled blank multiplayer/Firefight template
        (PROMPT.md: RVT wasn't running for blank gametypes, and clicking it didn't load them, both
        because a blank project previously had no ``.bin`` at all) -- never ``None`` in that case.
        For the built-in/personal-variant flows, ``None`` means a blank project (no chooser shown).
        """
        if self._ask_game_type:
            return blank_variant.resolve_blank_variant(firefight=self.is_firefight())
        if not self._variants:
            return None
        data = self.variant_combo.currentData()
        return Path(data) if data else None
