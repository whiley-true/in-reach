"""Tests for :mod:`in_reach.ide.kanban_board` -- the Kanban board editor tab (PROMPT.md: "the board
should function like a simple Trello: add column, rename, delete; add card, title, description,
label (edit, delete, make labels); mark as done")."""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QPixmap

from in_reach.app.kanban_db import KanbanStore
from in_reach.ide.kanban_board import KanbanBoardView, _CardDelegate
from in_reach.ide.kanban_dialogs import CardDialog, LabelsDialog


@pytest.fixture
def store(tmp_path: Path):
    s = KanbanStore(tmp_path / ".in-reach")
    yield s
    s.close()


@pytest.fixture
def board(store: KanbanStore):
    project = store.ensure_project("proj", "Proj")
    return store.create_board(project.id, "Sprint 1")


@pytest.fixture
def view(qtbot, store: KanbanStore, board) -> KanbanBoardView:
    widget = KanbanBoardView(store, board.id)
    qtbot.addWidget(widget)
    widget.resize(1000, 560)
    widget.show()
    return widget


def _cols(store: KanbanStore, board):
    return store.list_columns(board.id)


def _titles(column) -> list[str]:
    return [column.card_list.item(i).text() for i in range(column.card_list.count())]


# -- rendering ------------------------------------------------------------------------------------


def test_shows_the_board_name_and_its_columns_in_order(view: KanbanBoardView) -> None:
    assert view.title_label.text() == "Sprint 1"
    assert [c.title_label.text() for c in view.columns] == ["To Do", "In Progress", "Done"]


def test_columns_show_their_cards_and_a_count(view: KanbanBoardView, store: KanbanStore, board) -> None:
    todo = _cols(store, board)[0]
    store.add_card(todo.id, "First")
    store.add_card(todo.id, "Second")

    assert _titles(view.columns[0]) == ["First", "Second"]
    assert view.columns[0].count_label.text() == "2"
    assert view.columns[1].count_label.text() == "0"


def test_a_card_description_is_its_tooltip(view: KanbanBoardView, store: KanbanStore, board) -> None:
    store.add_card(_cols(store, board)[0].id, "Task", "the details")

    assert view.columns[0].card_list.item(0).toolTip() == "the details"


def test_an_empty_board_shows_a_hint_and_still_allows_adding_a_column(qtbot, store: KanbanStore) -> None:
    project = store.ensure_project("p2", "P2")
    empty = store.create_board(project.id, "Empty", seed_columns=False)
    empty_view = KanbanBoardView(store, empty.id)
    qtbot.addWidget(empty_view)
    empty_view.show()

    assert empty_view.columns == []
    assert empty_view.add_column_button.isEnabled() is True


def test_view_redraws_when_the_store_changes_underneath_it(view: KanbanBoardView, store: KanbanStore, board) -> None:
    store.add_card(_cols(store, board)[1].id, "added elsewhere")

    assert _titles(view.columns[1]) == ["added elsewhere"]


def test_two_views_of_one_board_stay_in_step(qtbot, store: KanbanStore, board, view: KanbanBoardView) -> None:
    other = KanbanBoardView(store, board.id)
    qtbot.addWidget(other)
    other.show()

    view.add_card(_cols(store, board)[0].id, "from the first view")

    assert _titles(other.columns[0]) == ["from the first view"]


def test_a_deleted_board_shows_a_notice_and_disables_the_toolbar(view: KanbanBoardView, store: KanbanStore, board) -> None:
    store.delete_board(board.id)

    assert view._missing_label.isVisibleTo(view) is True
    assert view.add_column_button.isEnabled() is False
    assert view.labels_button.isEnabled() is False


def test_the_horizontal_scroll_position_survives_a_redraw(qtbot, store: KanbanStore, board) -> None:
    for i in range(6):
        store.add_column(board.id, f"Extra {i}")
    narrow = KanbanBoardView(store, board.id)
    qtbot.addWidget(narrow)
    narrow.resize(500, 400)
    narrow.show()
    bar = narrow._scroll.horizontalScrollBar()
    bar.setValue(150)

    store.add_card(_cols(store, board)[0].id, "triggers a redraw")

    assert narrow._scroll.horizontalScrollBar().value() == 150


# -- background (PROMPT.md: "set background colour or custom image") --------------------------------


def test_background_colour_is_painted(view: KanbanBoardView, store: KanbanStore, board) -> None:
    store.set_board_background(board.id, color="#123456")

    assert view._canvas.color == QColor("#123456")
    assert view._canvas.has_image is False
    assert view._canvas.grab().toImage().pixelColor(2, 2) == QColor("#123456")


def test_background_image_is_painted_covering_the_board(view: KanbanBoardView, store: KanbanStore, board, tmp_path: Path) -> None:
    source = tmp_path / "bg.png"
    pixmap = QPixmap(60, 40)
    pixmap.fill(QColor("#00ff00"))
    assert pixmap.save(str(source))

    store.set_board_background_image(board.id, source)

    assert view._canvas.has_image is True
    assert view._canvas.grab().toImage().pixelColor(2, 2) == QColor("#00ff00")


def test_a_missing_background_image_file_falls_back_to_plain(view: KanbanBoardView, store: KanbanStore, board, tmp_path: Path) -> None:
    source = tmp_path / "bg.png"
    QPixmap(10, 10).save(str(source))
    relative = store.set_board_background_image(board.id, source)
    (store.in_reach_dir / relative).unlink()

    view.reload()

    assert view._canvas.has_image is False


def test_no_background_uses_the_theme_base_colour(view: KanbanBoardView) -> None:
    assert view._canvas.color is None


# -- columns --------------------------------------------------------------------------------------


def test_add_column_asks_for_a_name_then_adds_it(view: KanbanBoardView, store: KanbanStore, board, monkeypatch) -> None:
    monkeypatch.setattr(view, "_ask_text", lambda *a, **k: "Review")

    view.add_column_button.click()

    assert [c.name for c in _cols(store, board)][-1] == "Review"
    assert [c.title_label.text() for c in view.columns][-1] == "Review"


def test_add_column_cancelled_adds_nothing(view: KanbanBoardView, store: KanbanStore, board, monkeypatch) -> None:
    monkeypatch.setattr(view, "_ask_text", lambda *a, **k: None)

    view.add_column()

    assert len(_cols(store, board)) == 3


def test_rename_column(view: KanbanBoardView, store: KanbanStore, board, monkeypatch) -> None:
    seen = {}
    monkeypatch.setattr(view, "_ask_text", lambda title, label, default="": seen.setdefault("default", default) and "Backlog")

    view.columns[0].rename_action.trigger()

    assert seen["default"] == "To Do"
    assert _cols(store, board)[0].name == "Backlog"


def test_delete_column_confirms_and_mentions_the_card_count(view: KanbanBoardView, store: KanbanStore, board, monkeypatch) -> None:
    todo = _cols(store, board)[0]
    store.add_card(todo.id, "a")
    store.add_card(todo.id, "b")
    prompts = []
    monkeypatch.setattr(view, "_confirm", lambda text: prompts.append(text) or True)

    view.columns[0].delete_action.trigger()

    assert "2 cards" in prompts[0]
    assert [c.name for c in _cols(store, board)] == ["In Progress", "Done"]


def test_delete_column_declined_keeps_it(view: KanbanBoardView, store: KanbanStore, board, monkeypatch) -> None:
    monkeypatch.setattr(view, "_confirm", lambda text: False)

    view.columns[0].delete_action.trigger()

    assert len(_cols(store, board)) == 3


def test_move_column_actions_respect_the_ends_and_reorder(view: KanbanBoardView, store: KanbanStore, board) -> None:
    assert view.columns[0].move_left_action.isEnabled() is False
    assert view.columns[0].move_right_action.isEnabled() is True
    assert view.columns[2].move_right_action.isEnabled() is False

    view.columns[0].move_right_action.trigger()

    assert [c.name for c in _cols(store, board)] == ["In Progress", "To Do", "Done"]


# -- cards: add -----------------------------------------------------------------------------------


def test_add_card_editor_adds_a_card_and_stays_open_for_the_next(view: KanbanBoardView, store: KanbanStore, board) -> None:
    todo = _cols(store, board)[0]
    view.columns[0].open_add_card_editor()
    view.columns[0].add_card_edit.setText("Write tests")

    view.columns[0].add_card_edit.returnPressed.emit()

    assert [c.title for c in store.list_cards(todo.id)] == ["Write tests"]
    column = view.column_widget(todo.id)
    assert column.add_card_edit.isVisibleTo(view) is True
    assert column.add_card_edit.text() == ""


def test_add_card_ignores_a_blank_title(view: KanbanBoardView, store: KanbanStore, board) -> None:
    view.columns[0].open_add_card_editor()
    view.columns[0].add_card_edit.setText("   ")

    view.columns[0].add_card_edit.returnPressed.emit()

    assert store.list_cards(_cols(store, board)[0].id) == []


def test_escape_closes_the_add_card_editor(qtbot, view: KanbanBoardView) -> None:
    column = view.columns[0]
    column.open_add_card_editor()
    assert column.add_card_edit.isVisibleTo(view) is True

    qtbot.keyClick(column.add_card_edit, Qt.Key.Key_Escape)

    assert column.add_card_edit.isVisibleTo(view) is False
    assert column.add_card_button.isVisibleTo(view) is True


def test_the_add_card_button_opens_the_editor(view: KanbanBoardView) -> None:
    column = view.columns[1]

    column.add_card_button.click()

    assert column.add_card_edit.isVisibleTo(view) is True
    assert column.add_card_button.isVisibleTo(view) is False


# -- cards: done / edit / delete / move -----------------------------------------------------------


def test_clicking_the_tick_box_marks_a_card_done(qtbot, view: KanbanBoardView, store: KanbanStore, board) -> None:
    card = store.add_card(_cols(store, board)[0].id, "Task")
    card_list = view.columns[0].card_list
    item = card_list.item(0)
    labels, title = card_list._item_parts(item)
    check = card_list.card_delegate.check_rect(card_list.visualItemRect(item), card_list.font(), labels, title)

    qtbot.mouseClick(card_list.viewport(), Qt.MouseButton.LeftButton, pos=check.center())

    assert store.get_card(card.id).done is True
    assert view.columns[0].card_list.item(0).data(Qt.ItemDataRole.UserRole + 1) is True


def test_toggle_done_flips_back(view: KanbanBoardView, store: KanbanStore, board) -> None:
    card = store.add_card(_cols(store, board)[0].id, "Task")

    view.toggle_done(card.id)
    view.toggle_done(card.id)

    assert store.get_card(card.id).done is False


def test_double_clicking_a_card_opens_its_edit_dialog(view: KanbanBoardView, store: KanbanStore, board, monkeypatch) -> None:
    card = store.add_card(_cols(store, board)[0].id, "Task")
    opened = []
    monkeypatch.setattr(view, "_run_dialog", opened.append)

    view.columns[0].card_list.edit_requested.emit(card.id)

    assert len(opened) == 1 and isinstance(opened[0], CardDialog)


def test_edit_card_that_no_longer_exists_is_a_noop(view: KanbanBoardView, monkeypatch) -> None:
    opened = []
    monkeypatch.setattr(view, "_run_dialog", opened.append)

    view.edit_card(99999)

    assert opened == []


def test_card_menu_offers_edit_done_move_and_delete(view: KanbanBoardView, store: KanbanStore, board) -> None:
    card = store.add_card(_cols(store, board)[0].id, "Task")

    menu = view.build_card_menu(card.id)

    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert labels == ["Edit...", "Mark as Done", "Move to", "Delete..."]
    move_menu = next(a for a in menu.actions() if a.text() == "Move to").menu()
    enabled = {a.text(): a.isEnabled() for a in move_menu.actions()}
    assert enabled == {"To Do": False, "In Progress": True, "Done": True}  # not its own column


def test_card_menu_offers_mark_not_done_for_a_done_card(view: KanbanBoardView, store: KanbanStore, board) -> None:
    card = store.add_card(_cols(store, board)[0].id, "Task")
    store.set_card_done(card.id, True)

    menu = view.build_card_menu(card.id)

    assert "Mark as Not Done" in [a.text() for a in menu.actions()]


def test_card_menu_move_to_moves_the_card(view: KanbanBoardView, store: KanbanStore, board) -> None:
    cols = _cols(store, board)
    card = store.add_card(cols[0].id, "Task")
    menu = view.build_card_menu(card.id)
    move_menu = next(a for a in menu.actions() if a.text() == "Move to").menu()

    next(a for a in move_menu.actions() if a.text() == "Done").trigger()

    assert store.get_card(card.id).column_id == cols[2].id
    assert _titles(view.columns[2]) == ["Task"]


def test_delete_card_confirms(view: KanbanBoardView, store: KanbanStore, board, monkeypatch) -> None:
    card = store.add_card(_cols(store, board)[0].id, "Task")
    monkeypatch.setattr(view, "_confirm", lambda text: False)
    view.delete_card(card.id)
    assert store.get_card(card.id) is not None

    monkeypatch.setattr(view, "_confirm", lambda text: True)
    view.delete_card(card.id)
    assert store.get_card(card.id) is None
    assert _titles(view.columns[0]) == []


def test_right_clicking_a_card_pops_up_its_menu(view: KanbanBoardView, store: KanbanStore, board, monkeypatch) -> None:
    from PyQt6.QtWidgets import QMenu

    card = store.add_card(_cols(store, board)[0].id, "Task")
    popped = []
    monkeypatch.setattr(QMenu, "exec", lambda self, *args, **kwargs: popped.append([a.text() for a in self.actions()]))
    card_list = view.columns[0].card_list

    card_list._on_context_menu(card_list.visualItemRect(card_list.item(0)).center())

    assert card.id  # the menu was built for that card
    assert popped == [["Edit...", "Mark as Done", "Move to", "", "Delete..."]]


def test_right_clicking_empty_space_pops_up_nothing(view: KanbanBoardView, monkeypatch) -> None:
    from PyQt6.QtWidgets import QMenu

    popped = []
    monkeypatch.setattr(QMenu, "exec", lambda self, *args, **kwargs: popped.append(1))

    view.columns[0].card_list._on_context_menu(QPoint(5, 5))

    assert popped == []


# -- drag and drop --------------------------------------------------------------------------------


def test_dropping_a_card_into_another_column_is_persisted(view: KanbanBoardView, store: KanbanStore, board) -> None:
    cols = _cols(store, board)
    a = store.add_card(cols[0].id, "A")
    store.add_card(cols[0].id, "B")
    store.add_card(cols[1].id, "X")
    source, target = view.columns[0].card_list, view.columns[1].card_list

    moved = source.takeItem(0)  # what Qt's own drag-and-drop move does to the lists
    target.insertItem(0, moved)
    view.persist_order()

    assert [c.title for c in store.list_cards(cols[0].id)] == ["B"]
    assert [c.title for c in store.list_cards(cols[1].id)] == ["A", "X"]
    assert store.get_card(a.id).column_id == cols[1].id


def test_reordering_within_a_column_is_persisted(view: KanbanBoardView, store: KanbanStore, board) -> None:
    todo = _cols(store, board)[0]
    store.add_card(todo.id, "A")
    store.add_card(todo.id, "B")
    store.add_card(todo.id, "C")
    card_list = view.columns[0].card_list

    card_list.insertItem(0, card_list.takeItem(2))  # C to the top
    view.persist_order()

    assert [c.title for c in store.list_cards(todo.id)] == ["C", "A", "B"]


def test_a_drop_persists_from_the_next_event_loop_turn(qtbot, view: KanbanBoardView, store: KanbanStore, board) -> None:
    cols = _cols(store, board)
    store.add_card(cols[0].id, "A")
    source, target = view.columns[0].card_list, view.columns[2].card_list
    target.addItem(source.takeItem(0))

    source.order_changed.emit()
    assert store.list_cards(cols[0].id) != []  # not yet -- deferred out of the drop handler itself

    qtbot.waitUntil(lambda: store.list_cards(cols[0].id) == [])
    assert [c.title for c in store.list_cards(cols[2].id)] == ["A"]


def test_several_drops_before_the_timer_fires_persist_only_once(qtbot, view: KanbanBoardView) -> None:
    calls = []
    original = view.persist_order
    view.persist_order = lambda: calls.append(1) or original()  # type: ignore[method-assign]

    view._schedule_persist_order()
    view._schedule_persist_order()
    qtbot.waitUntil(lambda: bool(calls))
    qtbot.wait(20)

    assert calls == [1]


def test_card_lists_accept_drops_and_move(view: KanbanBoardView) -> None:
    from PyQt6.QtWidgets import QAbstractItemView

    card_list = view.columns[0].card_list
    assert card_list.acceptDrops() is True
    assert card_list.dragEnabled() is True
    assert card_list.dragDropMode() == QAbstractItemView.DragDropMode.DragDrop
    assert card_list.defaultDropAction() == Qt.DropAction.MoveAction


# -- labels ---------------------------------------------------------------------------------------


def test_labels_button_opens_the_labels_dialog(view: KanbanBoardView, monkeypatch) -> None:
    opened = []
    monkeypatch.setattr(view, "_run_dialog", opened.append)

    view.labels_button.click()

    assert len(opened) == 1 and isinstance(opened[0], LabelsDialog)


def test_label_chips_are_carried_on_the_card_item(view: KanbanBoardView, store: KanbanStore, board) -> None:
    card = store.add_card(_cols(store, board)[0].id, "Task")
    bug = store.create_label(board.id, "bug", "#f87168")

    store.set_card_labels(card.id, [bug.id])

    item = view.columns[0].card_list.item(0)
    assert item.data(Qt.ItemDataRole.UserRole + 2) == ["#f87168|bug"]


# -- the card delegate ----------------------------------------------------------------------------


def test_a_longer_title_makes_a_taller_card(view: KanbanBoardView, store: KanbanStore, board) -> None:
    cols = _cols(store, board)
    store.add_card(cols[0].id, "short")
    store.add_card(cols[0].id, "a much much longer card title " * 6)
    card_list = view.columns[0].card_list

    short_h = card_list.visualItemRect(card_list.item(0)).height()
    long_h = card_list.visualItemRect(card_list.item(1)).height()

    assert long_h > short_h


def test_a_labelled_card_is_taller_than_an_unlabelled_one(view: KanbanBoardView, store: KanbanStore, board) -> None:
    cols = _cols(store, board)
    plain = store.add_card(cols[0].id, "same title")
    tagged = store.add_card(cols[0].id, "same title")
    store.set_card_labels(tagged.id, [store.create_label(board.id, "bug").id])
    card_list = view.columns[0].card_list

    plain_h = card_list.visualItemRect(card_list.item(0)).height()
    tagged_h = card_list.visualItemRect(card_list.item(1)).height()

    assert plain.id != tagged.id and tagged_h > plain_h


def test_delegate_layout_puts_the_tick_box_inside_the_card() -> None:
    delegate = _CardDelegate()
    from PyQt6.QtCore import QRect
    from PyQt6.QtGui import QFont

    item_rect = QRect(0, 0, 240, 50)
    check = delegate.check_rect(item_rect, QFont(), [], "Task")

    assert item_rect.contains(check)


def test_done_and_not_done_cards_paint_differently(view: KanbanBoardView, store: KanbanStore, board) -> None:
    cols = _cols(store, board)
    store.add_card(cols[0].id, "Task")
    done = store.add_card(cols[0].id, "Task")
    store.set_card_done(done.id, True)
    card_list = view.columns[0].card_list

    image = card_list.viewport().grab().toImage()
    first = card_list.visualItemRect(card_list.item(0))
    second = card_list.visualItemRect(card_list.item(1))
    crop_a = image.copy(first.left(), first.top(), first.width(), first.height() - 1)
    crop_b = image.copy(second.left(), second.top(), first.width(), first.height() - 1)

    assert crop_a != crop_b
