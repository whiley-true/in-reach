"""Dialogs behind the Kanban board (PROMPT.md: "add card, title, description, label (edit, delete,
make labels) -- mark as done"): :class:`CardDialog` (edit one card), :class:`LabelsDialog` (make/edit/
delete a board's labels) and :class:`LabelEditDialog` (one label's name + colour).

Every dialog applies its own changes straight to the :class:`~in_reach.app.kanban_db.KanbanStore`
when accepted -- the board view redraws itself off the store's own change notifications, so a
dialog never needs to hand anything back. Anything that would pop a further modal (a confirmation,
a colour picker) goes through a small, separately-named method so tests can substitute it, same
convention as ``ask_confirm_replace`` in :mod:`in_reach.ide.search_panel`.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from in_reach.app.kanban_db import LABEL_COLORS, KanbanStore, Label

_SWATCH_SIZE = 16


def swatch_icon(color: str, size: int = _SWATCH_SIZE) -> QIcon:
    """A small rounded colour chip, for a label's row in a list."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


def pick_color(parent: QWidget | None, initial: str | None) -> str | None:
    """A standard colour picker, seeded with ``initial`` -- the chosen ``#rrggbb``, or ``None`` if
    cancelled. Module-level so tests (and the sidebar panel) share one seam for it."""
    color = QColorDialog.getColor(QColor(initial) if initial else QColor(LABEL_COLORS[0]), parent, "Choose a colour")
    return color.name() if color.isValid() else None


class LabelEditDialog(QDialog):
    """One label's name and colour -- a row of the preset :data:`~in_reach.app.kanban_db.
    LABEL_COLORS` swatches plus "Custom..." for anything else."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        name: str = "",
        color: str = LABEL_COLORS[0],
        title: str = "Label",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._color = color

        layout = QVBoxLayout(self)
        self.name_edit = QLineEdit(name)
        self.name_edit.setPlaceholderText("Label name")
        layout.addWidget(self.name_edit)

        swatches = QHBoxLayout()
        self.swatch_buttons: dict[str, QToolButton] = {}
        for preset in LABEL_COLORS:
            button = QToolButton()
            button.setCheckable(True)
            button.setFixedSize(26, 26)
            button.setStyleSheet(
                f"QToolButton {{ background-color: {preset}; border: 2px solid transparent; border-radius: 4px; }}"
                "QToolButton:checked { border-color: palette(text); }"
            )
            button.setToolTip(preset)
            button.clicked.connect(lambda _checked=False, c=preset: self.set_color(c))
            swatches.addWidget(button)
            self.swatch_buttons[preset] = button
        self.custom_button = QPushButton("Custom...")
        self.custom_button.clicked.connect(self._pick_custom)
        swatches.addWidget(self.custom_button)
        swatches.addStretch(1)
        layout.addLayout(swatches)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(24)
        layout.addWidget(self.preview)
        self.name_edit.textChanged.connect(self._refresh_preview)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.set_color(color)

    def name(self) -> str:
        return self.name_edit.text().strip()

    def color(self) -> str:
        return self._color

    def set_color(self, color: str) -> None:
        self._color = QColor(color).name()
        for preset, button in self.swatch_buttons.items():
            button.setChecked(preset.lower() == self._color.lower())
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        text = self.name() or "(no name)"
        self.preview.setText(text)
        self.preview.setStyleSheet(
            f"QLabel {{ background-color: {self._color}; color: black; border-radius: 4px; padding: 2px 8px; }}"
        )

    def _pick_custom(self) -> None:
        chosen = pick_color(self, self._color)
        if chosen:
            self.set_color(chosen)


class LabelsDialog(QDialog):
    """Make, edit and delete a board's labels (PROMPT.md: "label (edit, delete, make labels)")."""

    def __init__(self, store: KanbanStore, board_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Labels")
        self._store = store
        self._board_id = board_id
        self.resize(360, 320)

        layout = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _item: self.edit_selected())
        layout.addWidget(self.list, 1)

        row = QHBoxLayout()
        self.new_button = QPushButton("New Label...")
        self.new_button.clicked.connect(self.new_label)
        self.edit_button = QPushButton("Edit...")
        self.edit_button.clicked.connect(self.edit_selected)
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete_selected)
        for button in (self.new_button, self.edit_button, self.delete_button):
            row.addWidget(button)
        layout.addLayout(row)

        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        close.accepted.connect(self.accept)
        layout.addWidget(close)

        self.list.itemSelectionChanged.connect(self._sync_enabled)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        for label in self._store.list_labels(self._board_id):
            item = QListWidgetItem(swatch_icon(label.color), label.name or "(no name)")
            item.setData(Qt.ItemDataRole.UserRole, label.id)
            self.list.addItem(item)
        self._sync_enabled()

    def _sync_enabled(self) -> None:
        has_selection = self._selected_label() is not None
        self.edit_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)

    def _selected_label(self) -> Label | None:
        item = self.list.currentItem()
        if item is None:
            return None
        label_id = item.data(Qt.ItemDataRole.UserRole)
        return next((lbl for lbl in self._store.list_labels(self._board_id) if lbl.id == label_id), None)

    def _ask_label(self, name: str, color: str, title: str) -> tuple[str, str] | None:
        """Test seam -- the (name, colour) the user entered, or ``None`` if cancelled."""
        dialog = LabelEditDialog(self, name=name, color=color, title=title)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.name(), dialog.color()

    def _confirm_delete(self, label: Label) -> bool:
        """Test seam."""
        result = QMessageBox.question(
            self,
            "in-reach",
            f"Delete the label {label.name or '(no name)'!r}? It will be removed from every card.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return result == QMessageBox.StandardButton.Yes

    def new_label(self) -> None:
        next_color = LABEL_COLORS[len(self._store.list_labels(self._board_id)) % len(LABEL_COLORS)]
        answer = self._ask_label("", next_color, "New Label")
        if answer is None:
            return
        self._store.create_label(self._board_id, answer[0], answer[1])
        self.refresh()

    def edit_selected(self) -> None:
        label = self._selected_label()
        if label is None:
            return
        answer = self._ask_label(label.name, label.color, "Edit Label")
        if answer is None:
            return
        self._store.update_label(label.id, name=answer[0], color=answer[1])
        self.refresh()

    def delete_selected(self) -> None:
        label = self._selected_label()
        if label is None or not self._confirm_delete(label):
            return
        self._store.delete_label(label.id)
        self.refresh()


class CardDialog(QDialog):
    """Edit one card: title, description, labels (check any number, or "Manage Labels..." to make/
    edit/delete them), done, or delete the card outright. Changes are applied to the store on OK."""

    def __init__(self, store: KanbanStore, card_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        card = store.get_card(card_id)
        if card is None:
            raise KeyError(card_id)
        self._store = store
        self._card = card
        self._board_id = self._board_id_of(card.column_id)
        #: ``True`` once the user deleted the card through this dialog (which then closes).
        self.deleted = False
        self.setWindowTitle("Edit Card")
        self.resize(460, 480)

        layout = QVBoxLayout(self)
        self.title_edit = QLineEdit(card.title)
        self.title_edit.setPlaceholderText("Card title")
        layout.addWidget(self.title_edit)

        layout.addWidget(QLabel("Description"))
        self.description_edit = QPlainTextEdit(card.description)
        self.description_edit.setPlaceholderText("Add a more detailed description...")
        layout.addWidget(self.description_edit, 1)

        layout.addWidget(QLabel("Labels"))
        self._labels_box = QVBoxLayout()
        self._labels_box.setSpacing(2)
        layout.addLayout(self._labels_box)
        self.label_checks: dict[int, QCheckBox] = {}
        self._checked_label_ids = set(card.label_ids)
        self.manage_labels_button = QPushButton("Manage Labels...")
        self.manage_labels_button.clicked.connect(self.open_labels_dialog)
        layout.addWidget(self.manage_labels_button, 0, Qt.AlignmentFlag.AlignLeft)
        self._rebuild_label_checks()

        self.done_check = QCheckBox("Mark as done")
        self.done_check.setChecked(card.done)
        layout.addWidget(self.done_check)

        buttons = QHBoxLayout()
        self.delete_button = QPushButton("Delete Card")
        self.delete_button.clicked.connect(self.delete_card)
        buttons.addWidget(self.delete_button)
        buttons.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        buttons.addWidget(box)
        layout.addLayout(buttons)

    def _board_id_of(self, column_id: int) -> int:
        board_id = self._store.board_id_of_column(column_id)
        if board_id is None:
            raise KeyError(column_id)
        return board_id

    # -- labels -----------------------------------------------------------------------------------

    def _rebuild_label_checks(self) -> None:
        # Remember what's ticked right now (not just what was saved) so reopening Manage Labels
        # doesn't undo a tick the user made a moment ago.
        if self.label_checks:
            self._checked_label_ids = {lid for lid, box in self.label_checks.items() if box.isChecked()}
        while self._labels_box.count():
            item = self._labels_box.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.label_checks = {}
        labels = self._store.list_labels(self._board_id)
        for label in labels:
            box = QCheckBox(label.name or "(no name)")
            box.setIcon(swatch_icon(label.color))
            box.setChecked(label.id in self._checked_label_ids)
            self._labels_box.addWidget(box)
            self.label_checks[label.id] = box
        if not labels:
            hint = QLabel("No labels yet -- use Manage Labels to make one.")
            hint.setEnabled(False)
            self._labels_box.addWidget(hint)

    def open_labels_dialog(self) -> None:
        """"Manage Labels..." -- then refreshes this dialog's own checkboxes to match."""
        self._run_labels_dialog(LabelsDialog(self._store, self._board_id, self))
        self._rebuild_label_checks()

    def _run_labels_dialog(self, dialog: LabelsDialog) -> None:
        """Test seam."""
        dialog.exec()

    # -- actions ----------------------------------------------------------------------------------

    def _confirm_delete(self) -> bool:
        """Test seam."""
        result = QMessageBox.question(
            self,
            "in-reach",
            f"Delete the card {self._card.title!r}? This can't be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return result == QMessageBox.StandardButton.Yes

    def delete_card(self) -> None:
        if not self._confirm_delete():
            return
        self._store.delete_card(self._card.id)
        self.deleted = True
        super().accept()

    def accept(self) -> None:
        title = self.title_edit.text().strip()
        if not title:
            self.title_edit.setFocus()
            self.title_edit.setPlaceholderText("A card needs a title")
            return
        with self._store.batch():
            self._store.update_card(self._card.id, title=title, description=self.description_edit.toPlainText())
            self._store.set_card_labels(
                self._card.id, [lid for lid, box in self.label_checks.items() if box.isChecked()]
            )
            if self.done_check.isChecked() != self._card.done:
                self._store.set_card_done(self._card.id, self.done_check.isChecked())
        super().accept()
