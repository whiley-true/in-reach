"""Tests for :mod:`in_reach.ide.kanban_dialogs` -- the card editor and the label dialogs (PROMPT.md:
"add card, title, description, label (edit, delete, make labels) -- mark as done")."""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtWidgets import QDialog

from in_reach.app.kanban_db import LABEL_COLORS, KanbanStore
from in_reach.ide import kanban_dialogs
from in_reach.ide.kanban_dialogs import CardDialog, LabelEditDialog, LabelsDialog


@pytest.fixture
def store(tmp_path: Path):
    s = KanbanStore(tmp_path / ".in-reach")
    yield s
    s.close()


@pytest.fixture
def board(store: KanbanStore):
    return store.create_board(store.ensure_project("p", "P").id, "Board")


@pytest.fixture
def card(store: KanbanStore, board):
    todo = store.list_columns(board.id)[0]
    return store.add_card(todo.id, "Original", "old description")


# -- LabelEditDialog ------------------------------------------------------------------------------


def test_label_edit_dialog_reports_name_and_colour(qtbot) -> None:
    dialog = LabelEditDialog(name="  bug ", color="#f87168")
    qtbot.addWidget(dialog)

    assert dialog.name() == "bug"
    assert dialog.color() == "#f87168"


def test_label_edit_dialog_preset_swatch_sets_the_colour_and_is_marked(qtbot) -> None:
    dialog = LabelEditDialog()
    qtbot.addWidget(dialog)

    dialog.swatch_buttons[LABEL_COLORS[3]].click()

    assert dialog.color() == LABEL_COLORS[3]
    assert dialog.swatch_buttons[LABEL_COLORS[3]].isChecked() is True
    assert dialog.swatch_buttons[LABEL_COLORS[0]].isChecked() is False


def test_label_edit_dialog_custom_colour_uses_the_picker(qtbot, monkeypatch) -> None:
    dialog = LabelEditDialog()
    qtbot.addWidget(dialog)
    monkeypatch.setattr(kanban_dialogs, "pick_color", lambda parent, initial: "#010203")

    dialog.custom_button.click()

    assert dialog.color() == "#010203"
    assert all(not b.isChecked() for b in dialog.swatch_buttons.values())


def test_label_edit_dialog_custom_colour_cancelled_keeps_the_old_one(qtbot, monkeypatch) -> None:
    dialog = LabelEditDialog(color=LABEL_COLORS[1])
    qtbot.addWidget(dialog)
    monkeypatch.setattr(kanban_dialogs, "pick_color", lambda parent, initial: None)

    dialog.custom_button.click()

    assert dialog.color() == LABEL_COLORS[1]


def test_label_edit_dialog_preview_follows_the_name(qtbot) -> None:
    dialog = LabelEditDialog()
    qtbot.addWidget(dialog)

    dialog.name_edit.setText("urgent")

    assert dialog.preview.text() == "urgent"


# -- LabelsDialog ---------------------------------------------------------------------------------


@pytest.fixture
def labels_dialog(qtbot, store: KanbanStore, board) -> LabelsDialog:
    dialog = LabelsDialog(store, board.id)
    qtbot.addWidget(dialog)
    return dialog


def test_labels_dialog_lists_the_boards_labels(store: KanbanStore, board, labels_dialog: LabelsDialog) -> None:
    store.create_label(board.id, "bug")
    store.create_label(board.id, "feature")

    labels_dialog.refresh()

    assert [labels_dialog.list.item(i).text() for i in range(labels_dialog.list.count())] == ["bug", "feature"]


def test_labels_dialog_buttons_need_a_selection(labels_dialog: LabelsDialog, store: KanbanStore, board) -> None:
    assert labels_dialog.edit_button.isEnabled() is False
    assert labels_dialog.delete_button.isEnabled() is False

    store.create_label(board.id, "bug")
    labels_dialog.refresh()
    labels_dialog.list.setCurrentRow(0)

    assert labels_dialog.edit_button.isEnabled() is True
    assert labels_dialog.delete_button.isEnabled() is True


def test_make_a_label(labels_dialog: LabelsDialog, store: KanbanStore, board, monkeypatch) -> None:
    monkeypatch.setattr(labels_dialog, "_ask_label", lambda name, color, title: ("urgent", "#ff0000"))

    labels_dialog.new_button.click()

    assert [(lbl.name, lbl.color) for lbl in store.list_labels(board.id)] == [("urgent", "#ff0000")]
    assert labels_dialog.list.count() == 1


def test_make_a_label_cancelled(labels_dialog: LabelsDialog, store: KanbanStore, board, monkeypatch) -> None:
    monkeypatch.setattr(labels_dialog, "_ask_label", lambda name, color, title: None)

    labels_dialog.new_label()

    assert store.list_labels(board.id) == []


def test_new_label_dialog_is_offered_the_next_preset_colour(labels_dialog: LabelsDialog, store: KanbanStore, board, monkeypatch) -> None:
    store.create_label(board.id, "one")
    offered = []
    monkeypatch.setattr(labels_dialog, "_ask_label", lambda name, color, title: offered.append(color))

    labels_dialog.new_label()

    assert offered == [LABEL_COLORS[1]]


def test_edit_a_label(labels_dialog: LabelsDialog, store: KanbanStore, board, monkeypatch) -> None:
    store.create_label(board.id, "bug", "#111111")
    labels_dialog.refresh()
    labels_dialog.list.setCurrentRow(0)
    seen = []
    monkeypatch.setattr(
        labels_dialog, "_ask_label", lambda name, color, title: seen.append((name, color)) or ("defect", "#222222")
    )

    labels_dialog.edit_button.click()

    assert seen == [("bug", "#111111")]
    assert [(lbl.name, lbl.color) for lbl in store.list_labels(board.id)] == [("defect", "#222222")]
    assert labels_dialog.list.item(0).text() == "defect"


def test_delete_a_label_confirms(labels_dialog: LabelsDialog, store: KanbanStore, board, monkeypatch) -> None:
    store.create_label(board.id, "bug")
    labels_dialog.refresh()
    labels_dialog.list.setCurrentRow(0)
    monkeypatch.setattr(labels_dialog, "_confirm_delete", lambda label: False)
    labels_dialog.delete_button.click()
    assert len(store.list_labels(board.id)) == 1

    monkeypatch.setattr(labels_dialog, "_confirm_delete", lambda label: True)
    labels_dialog.delete_button.click()

    assert store.list_labels(board.id) == []
    assert labels_dialog.list.count() == 0


def test_a_colour_only_label_gets_a_placeholder_name_in_the_list(labels_dialog: LabelsDialog, store: KanbanStore, board) -> None:
    store.create_label(board.id, "")

    labels_dialog.refresh()

    assert labels_dialog.list.item(0).text() == "(no name)"


# -- CardDialog -----------------------------------------------------------------------------------


@pytest.fixture
def card_dialog(qtbot, store: KanbanStore, card) -> CardDialog:
    dialog = CardDialog(store, card.id)
    qtbot.addWidget(dialog)
    return dialog


def test_card_dialog_loads_the_cards_fields(card_dialog: CardDialog) -> None:
    assert card_dialog.title_edit.text() == "Original"
    assert card_dialog.description_edit.toPlainText() == "old description"
    assert card_dialog.done_check.isChecked() is False


def test_card_dialog_for_a_missing_card_raises(qtbot, store: KanbanStore) -> None:
    with pytest.raises(KeyError):
        CardDialog(store, 99999)


def test_saving_edits_the_title_and_description(card_dialog: CardDialog, store: KanbanStore, card) -> None:
    card_dialog.title_edit.setText("  Renamed ")
    card_dialog.description_edit.setPlainText("new words")

    card_dialog.accept()

    saved = store.get_card(card.id)
    assert (saved.title, saved.description) == ("Renamed", "new words")


def test_a_blank_title_keeps_the_dialog_open_and_saves_nothing(card_dialog: CardDialog, store: KanbanStore, card) -> None:
    card_dialog.title_edit.setText("   ")
    card_dialog.description_edit.setPlainText("changed too")

    card_dialog.accept()

    assert card_dialog.result() != QDialog.DialogCode.Accepted
    assert store.get_card(card.id).title == "Original"
    assert store.get_card(card.id).description == "old description"


def test_marking_done_from_the_dialog(card_dialog: CardDialog, store: KanbanStore, card) -> None:
    card_dialog.done_check.setChecked(True)

    card_dialog.accept()

    assert store.get_card(card.id).done is True


def test_saving_an_already_done_card_untouched_keeps_its_done_time(qtbot, store: KanbanStore, card) -> None:
    store.set_card_done(card.id, True)
    done_at = store.get_card(card.id).done_at
    dialog = CardDialog(store, card.id)
    qtbot.addWidget(dialog)

    dialog.accept()

    assert store.get_card(card.id).done_at == done_at


def test_labels_are_listed_and_the_ones_on_the_card_are_ticked(qtbot, store: KanbanStore, board, card) -> None:
    bug = store.create_label(board.id, "bug")
    store.create_label(board.id, "feature")
    store.set_card_labels(card.id, [bug.id])

    dialog = CardDialog(store, card.id)
    qtbot.addWidget(dialog)

    assert {lid: box.isChecked() for lid, box in dialog.label_checks.items()} == {bug.id: True, bug.id + 1: False}


def test_ticking_labels_saves_them_on_the_card(card_dialog: CardDialog, store: KanbanStore, board, card) -> None:
    bug = store.create_label(board.id, "bug")
    feature = store.create_label(board.id, "feature")
    card_dialog._rebuild_label_checks()

    card_dialog.label_checks[bug.id].setChecked(True)
    card_dialog.label_checks[feature.id].setChecked(True)
    card_dialog.accept()

    assert store.get_card(card.id).label_ids == (bug.id, feature.id)


def test_unticking_removes_a_label_from_the_card(qtbot, store: KanbanStore, board, card) -> None:
    bug = store.create_label(board.id, "bug")
    store.set_card_labels(card.id, [bug.id])
    dialog = CardDialog(store, card.id)
    qtbot.addWidget(dialog)

    dialog.label_checks[bug.id].setChecked(False)
    dialog.accept()

    assert store.get_card(card.id).label_ids == ()


def test_a_board_with_no_labels_says_how_to_make_one(card_dialog: CardDialog) -> None:
    assert card_dialog.label_checks == {}


def test_manage_labels_refreshes_the_checkboxes_and_keeps_ticks(card_dialog: CardDialog, store: KanbanStore, board, monkeypatch) -> None:
    first = store.create_label(board.id, "bug")
    card_dialog._rebuild_label_checks()
    card_dialog.label_checks[first.id].setChecked(True)

    def make_another(dialog) -> None:
        store.create_label(board.id, "feature")

    monkeypatch.setattr(card_dialog, "_run_labels_dialog", make_another)
    card_dialog.manage_labels_button.click()

    assert len(card_dialog.label_checks) == 2
    assert card_dialog.label_checks[first.id].isChecked() is True  # the tick made a moment ago survived


def test_manage_labels_opens_a_labels_dialog_for_this_board(card_dialog: CardDialog, monkeypatch, board) -> None:
    seen = []
    monkeypatch.setattr(card_dialog, "_run_labels_dialog", seen.append)

    card_dialog.open_labels_dialog()

    assert isinstance(seen[0], LabelsDialog)
    assert seen[0]._board_id == board.id


def test_a_deleted_label_disappears_from_the_dialog_after_managing(card_dialog: CardDialog, store: KanbanStore, board, monkeypatch) -> None:
    bug = store.create_label(board.id, "bug")
    card_dialog._rebuild_label_checks()
    monkeypatch.setattr(card_dialog, "_run_labels_dialog", lambda dialog: store.delete_label(bug.id))

    card_dialog.open_labels_dialog()

    assert card_dialog.label_checks == {}


def test_delete_card_confirms_then_deletes_and_closes(card_dialog: CardDialog, store: KanbanStore, card, monkeypatch) -> None:
    monkeypatch.setattr(card_dialog, "_confirm_delete", lambda: False)
    card_dialog.delete_button.click()
    assert store.get_card(card.id) is not None
    assert card_dialog.deleted is False

    monkeypatch.setattr(card_dialog, "_confirm_delete", lambda: True)
    card_dialog.delete_button.click()

    assert store.get_card(card.id) is None
    assert card_dialog.deleted is True
    assert card_dialog.result() == QDialog.DialogCode.Accepted


def test_cancelling_the_dialog_saves_nothing(card_dialog: CardDialog, store: KanbanStore, card) -> None:
    card_dialog.title_edit.setText("changed")
    card_dialog.done_check.setChecked(True)

    card_dialog.reject()

    saved = store.get_card(card.id)
    assert saved.title == "Original" and saved.done is False


def test_pick_color_returns_the_hex_or_none(monkeypatch) -> None:
    from PyQt6.QtGui import QColor
    from PyQt6.QtWidgets import QColorDialog

    monkeypatch.setattr(QColorDialog, "getColor", staticmethod(lambda *a, **k: QColor("#abcdef")))
    assert kanban_dialogs.pick_color(None, "#000000") == "#abcdef"

    monkeypatch.setattr(QColorDialog, "getColor", staticmethod(lambda *a, **k: QColor()))
    assert kanban_dialogs.pick_color(None, None) is None
