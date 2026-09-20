"""Tests for :mod:`in_reach.app.kanban_db` -- the SQLite-backed Kanban store."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from in_reach.app import kanban_db
from in_reach.app.kanban_db import KanbanStore


@pytest.fixture
def store(tmp_path: Path):
    s = KanbanStore(tmp_path / ".in-reach")
    yield s
    s.close()


def test_creates_the_database_file_inside_the_in_reach_folder(tmp_path: Path) -> None:
    s = KanbanStore(tmp_path / ".in-reach")
    try:
        assert (tmp_path / ".in-reach" / kanban_db.DB_FILENAME).is_file()
    finally:
        s.close()


def test_reopening_an_existing_database_keeps_its_data(tmp_path: Path) -> None:
    first = KanbanStore(tmp_path)
    project = first.ensure_project("abc", "Abc")
    first.create_board(project.id, "Sprint")
    first.close()

    second = KanbanStore(tmp_path)
    try:
        assert [b.name for b in second.list_boards(second.ensure_project("abc").id)] == ["Sprint"]
    finally:
        second.close()


def test_schema_version_is_recorded(tmp_path: Path) -> None:
    KanbanStore(tmp_path).close()
    conn = sqlite3.connect(tmp_path / kanban_db.DB_FILENAME)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == kanban_db.SCHEMA_VERSION
    finally:
        conn.close()


# -- projects ------------------------------------------------------------------------------------


def test_one_database_links_many_projects(store: KanbanStore) -> None:
    a = store.ensure_project("proj-a", "Alpha")
    b = store.ensure_project("proj-b", "Beta")
    store.create_board(a.id, "A board")
    store.create_board(b.id, "B board")

    assert [p.key for p in store.list_projects()] == ["proj-a", "proj-b"]
    assert [x.name for x in store.list_boards(a.id)] == ["A board"]
    assert [x.name for x in store.list_boards(b.id)] == ["B board"]


def test_ensure_project_is_idempotent_and_refreshes_the_title(store: KanbanStore) -> None:
    first = store.ensure_project("proj", "Old")
    second = store.ensure_project("proj", "New")

    assert first.id == second.id
    assert store.list_projects()[0].title == "New"


# -- boards --------------------------------------------------------------------------------------


def test_first_board_becomes_default_and_is_seeded_with_columns(store: KanbanStore) -> None:
    project = store.ensure_project("p")
    board = store.create_board(project.id, "Main")

    assert board.is_default
    assert [c.name for c in store.list_columns(board.id)] == list(kanban_db.DEFAULT_COLUMN_NAMES)


def test_later_boards_are_not_default_and_can_start_empty(store: KanbanStore) -> None:
    project = store.ensure_project("p")
    store.create_board(project.id, "Main")
    second = store.create_board(project.id, "Empty", seed_columns=False)

    assert not second.is_default
    assert store.list_columns(second.id) == []


def test_ensure_default_board_creates_once(store: KanbanStore) -> None:
    project = store.ensure_project("p")

    first = store.ensure_default_board(project.id)
    second = store.ensure_default_board(project.id)

    assert first.id == second.id
    assert first.name == kanban_db.DEFAULT_BOARD_NAME
    assert len(store.list_boards(project.id)) == 1


def test_set_default_board_moves_the_flag(store: KanbanStore) -> None:
    project = store.ensure_project("p")
    a = store.create_board(project.id, "A")
    b = store.create_board(project.id, "B")

    store.set_default_board(b.id)

    assert store.default_board(project.id).id == b.id
    assert not store.get_board(a.id).is_default


def test_deleting_the_default_board_promotes_the_next_one(store: KanbanStore) -> None:
    project = store.ensure_project("p")
    a = store.create_board(project.id, "A")
    b = store.create_board(project.id, "B")

    store.delete_board(a.id)

    assert store.get_board(a.id) is None
    assert store.default_board(project.id).id == b.id
    assert store.get_board(b.id).is_default


def test_deleting_a_board_cascades_to_its_columns_cards_and_labels(store: KanbanStore) -> None:
    project = store.ensure_project("p")
    board = store.create_board(project.id, "A")
    column = store.list_columns(board.id)[0]
    card = store.add_card(column.id, "task")
    label = store.create_label(board.id, "bug")
    store.set_card_labels(card.id, [label.id])

    store.delete_board(board.id)

    assert store.get_card(card.id) is None
    assert store.list_columns(board.id) == []
    assert store.list_labels(board.id) == []


def test_rename_board(store: KanbanStore) -> None:
    board = store.create_board(store.ensure_project("p").id, "Old")

    store.rename_board(board.id, "  New  ")

    assert store.get_board(board.id).name == "New"


def test_blank_names_are_rejected(store: KanbanStore) -> None:
    project = store.ensure_project("p")
    board = store.create_board(project.id, "Board")
    column = store.list_columns(board.id)[0]

    with pytest.raises(ValueError):
        store.create_board(project.id, "   ")
    with pytest.raises(ValueError):
        store.rename_board(board.id, "")
    with pytest.raises(ValueError):
        store.add_column(board.id, " ")
    with pytest.raises(ValueError):
        store.add_card(column.id, "")


# -- backgrounds ---------------------------------------------------------------------------------


def test_background_colour_round_trips_and_can_be_cleared(store: KanbanStore) -> None:
    board = store.create_board(store.ensure_project("p").id, "A")

    store.set_board_background(board.id, color="#123456")
    assert store.get_board(board.id).background_color == "#123456"

    store.set_board_background(board.id, color=None)
    assert store.get_board(board.id).background_color is None


def test_background_image_is_copied_into_the_in_reach_folder(store: KanbanStore, tmp_path: Path) -> None:
    board = store.create_board(store.ensure_project("p").id, "A")
    source = tmp_path / "pic.png"
    source.write_bytes(b"png-bytes")

    relative = store.set_board_background_image(board.id, source)

    stored = store.get_board(board.id)
    assert stored.background_image == relative
    copied = store.in_reach_dir / relative
    assert copied.read_bytes() == b"png-bytes"
    assert copied != source
    assert Path(relative).parts[:2] == ("kanban", "backgrounds")
    assert store.resolve_background_image(stored) == copied


def test_setting_an_image_clears_the_colour_and_vice_versa(store: KanbanStore, tmp_path: Path) -> None:
    board = store.create_board(store.ensure_project("p").id, "A", background_color="#abcdef")
    source = tmp_path / "pic.png"
    source.write_bytes(b"x")

    store.set_board_background_image(board.id, source)
    after_image = store.get_board(board.id)
    assert after_image.background_color is None
    assert after_image.background_image is not None

    store.set_board_background(board.id, color="#111111")
    after_color = store.get_board(board.id)
    assert after_color.background_image is None
    assert after_color.background_color == "#111111"
    assert not (store.in_reach_dir / after_image.background_image).exists()


def test_deleting_a_board_removes_its_background_image(store: KanbanStore, tmp_path: Path) -> None:
    board = store.create_board(store.ensure_project("p").id, "A")
    source = tmp_path / "pic.png"
    source.write_bytes(b"x")
    relative = store.set_board_background_image(board.id, source)

    store.delete_board(board.id)

    assert not (store.in_reach_dir / relative).exists()


def test_missing_background_source_raises(store: KanbanStore, tmp_path: Path) -> None:
    board = store.create_board(store.ensure_project("p").id, "A")

    with pytest.raises(FileNotFoundError):
        store.set_board_background_image(board.id, tmp_path / "nope.png")


def test_resolve_background_image_is_none_when_the_file_vanished(store: KanbanStore, tmp_path: Path) -> None:
    board = store.create_board(store.ensure_project("p").id, "A")
    source = tmp_path / "pic.png"
    source.write_bytes(b"x")
    relative = store.set_board_background_image(board.id, source)
    (store.in_reach_dir / relative).unlink()

    assert store.resolve_background_image(store.get_board(board.id)) is None


# -- columns -------------------------------------------------------------------------------------


def test_add_rename_and_delete_columns_keep_positions_contiguous(store: KanbanStore) -> None:
    board = store.create_board(store.ensure_project("p").id, "A", seed_columns=False)
    a = store.add_column(board.id, "A")
    b = store.add_column(board.id, "B")
    c = store.add_column(board.id, "C")

    store.rename_column(b.id, "Bee")
    store.delete_column(a.id)

    columns = store.list_columns(board.id)
    assert [(col.name, col.position) for col in columns] == [("Bee", 0), ("C", 1)]
    assert c.id in [col.id for col in columns]


def test_move_column(store: KanbanStore) -> None:
    board = store.create_board(store.ensure_project("p").id, "A", seed_columns=False)
    a = store.add_column(board.id, "A")
    store.add_column(board.id, "B")
    c = store.add_column(board.id, "C")

    store.move_column(c.id, 0)

    assert [col.name for col in store.list_columns(board.id)] == ["C", "A", "B"]
    store.move_column(a.id, 99)
    assert [col.name for col in store.list_columns(board.id)] == ["C", "B", "A"]


def test_deleting_a_column_deletes_its_cards(store: KanbanStore) -> None:
    board = store.create_board(store.ensure_project("p").id, "A")
    column = store.list_columns(board.id)[0]
    card = store.add_card(column.id, "task")

    store.delete_column(column.id)

    assert store.get_card(card.id) is None


# -- cards ---------------------------------------------------------------------------------------


def _first_two_columns(store: KanbanStore):
    board = store.create_board(store.ensure_project("p").id, "A")
    columns = store.list_columns(board.id)
    return board, columns[0], columns[1]


def test_add_card_appends_and_update_edits_it(store: KanbanStore) -> None:
    _board, todo, _doing = _first_two_columns(store)
    a = store.add_card(todo.id, "First", "desc")
    b = store.add_card(todo.id, "Second")

    store.update_card(b.id, title="Second!", description="more")

    assert [c.title for c in store.list_cards(todo.id)] == ["First", "Second!"]
    assert store.get_card(a.id).description == "desc"
    assert store.get_card(b.id).description == "more"


def test_mark_card_done_and_undone(store: KanbanStore) -> None:
    _board, todo, _doing = _first_two_columns(store)
    card = store.add_card(todo.id, "task")
    assert not card.done

    store.set_card_done(card.id, True)
    done = store.get_card(card.id)
    assert done.done and done.done_at is not None

    store.set_card_done(card.id, False)
    undone = store.get_card(card.id)
    assert not undone.done and undone.done_at is None


def test_delete_card_renumbers_the_rest(store: KanbanStore) -> None:
    _board, todo, _doing = _first_two_columns(store)
    a = store.add_card(todo.id, "A")
    store.add_card(todo.id, "B")
    store.add_card(todo.id, "C")

    store.delete_card(a.id)

    assert [(c.title, c.position) for c in store.list_cards(todo.id)] == [("B", 0), ("C", 1)]


def test_move_card_between_columns_and_within_one(store: KanbanStore) -> None:
    _board, todo, doing = _first_two_columns(store)
    a = store.add_card(todo.id, "A")
    b = store.add_card(todo.id, "B")
    store.add_card(doing.id, "X")

    store.move_card(a.id, doing.id, 0)
    assert [c.title for c in store.list_cards(todo.id)] == ["B"]
    assert [c.title for c in store.list_cards(doing.id)] == ["A", "X"]
    assert [c.position for c in store.list_cards(todo.id)] == [0]

    store.move_card(b.id, doing.id)
    assert [c.title for c in store.list_cards(doing.id)] == ["A", "X", "B"]

    store.move_card(b.id, doing.id, 0)
    assert [c.title for c in store.list_cards(doing.id)] == ["B", "A", "X"]


def test_set_column_cards_applies_a_dragged_order(store: KanbanStore) -> None:
    _board, todo, doing = _first_two_columns(store)
    a = store.add_card(todo.id, "A")
    b = store.add_card(todo.id, "B")
    x = store.add_card(doing.id, "X")

    store.set_column_cards(todo.id, [b.id])
    store.set_column_cards(doing.id, [x.id, a.id])

    assert [c.title for c in store.list_cards(todo.id)] == ["B"]
    assert [c.title for c in store.list_cards(doing.id)] == ["X", "A"]


# -- labels --------------------------------------------------------------------------------------


def test_labels_are_per_board_and_get_default_colours(store: KanbanStore) -> None:
    project = store.ensure_project("p")
    a = store.create_board(project.id, "A")
    b = store.create_board(project.id, "B")

    first = store.create_label(a.id, "bug")
    second = store.create_label(a.id, "feature")
    store.create_label(b.id, "other")

    assert first.color == kanban_db.LABEL_COLORS[0]
    assert second.color == kanban_db.LABEL_COLORS[1]
    assert [lbl.name for lbl in store.list_labels(a.id)] == ["bug", "feature"]
    assert [lbl.name for lbl in store.list_labels(b.id)] == ["other"]


def test_edit_label(store: KanbanStore) -> None:
    board = store.create_board(store.ensure_project("p").id, "A")
    label = store.create_label(board.id, "bug")

    store.update_label(label.id, name="defect", color="#ff0000")

    edited = store.list_labels(board.id)[0]
    assert (edited.name, edited.color) == ("defect", "#ff0000")


def test_assigning_and_replacing_card_labels(store: KanbanStore) -> None:
    board, todo, _doing = _first_two_columns(store)
    card = store.add_card(todo.id, "task")
    bug = store.create_label(board.id, "bug")
    feat = store.create_label(board.id, "feature")

    store.set_card_labels(card.id, [bug.id, feat.id])
    assert store.get_card(card.id).label_ids == (bug.id, feat.id)

    store.set_card_labels(card.id, [feat.id])
    assert store.get_card(card.id).label_ids == (feat.id,)


def test_deleting_a_label_removes_it_from_cards(store: KanbanStore) -> None:
    board, todo, _doing = _first_two_columns(store)
    card = store.add_card(todo.id, "task")
    bug = store.create_label(board.id, "bug")
    store.set_card_labels(card.id, [bug.id])

    store.delete_label(bug.id)

    assert store.get_card(card.id).label_ids == ()


# -- load_board ----------------------------------------------------------------------------------


def test_load_board_returns_columns_cards_and_labels_together(store: KanbanStore) -> None:
    board, todo, _doing = _first_two_columns(store)
    store.add_card(todo.id, "task")
    store.create_label(board.id, "bug")

    data = store.load_board(board.id)

    assert data.board.id == board.id
    assert [c.column.name for c in data.columns] == list(kanban_db.DEFAULT_COLUMN_NAMES)
    assert [card.title for card in data.columns[0].cards] == ["task"]
    assert [lbl.name for lbl in data.labels] == ["bug"]
    assert store.load_board(9999) is None


# -- agile groundwork ----------------------------------------------------------------------------


def test_column_rules_are_stored_but_not_enforced(store: KanbanStore) -> None:
    _board, _todo, doing = _first_two_columns(store)
    _ = doing

    rule = store.add_column_rule(doing.id, kanban_db.RULE_REQUIRES_COMPILE, {"target": "apply"})
    store.add_column_rule(doing.id, kanban_db.RULE_REQUIRES_TESTS)

    rules = store.list_column_rules(doing.id)
    assert [(r.rule_type, r.config) for r in rules] == [
        (kanban_db.RULE_REQUIRES_COMPILE, {"target": "apply"}),
        (kanban_db.RULE_REQUIRES_TESTS, {}),
    ]

    # Recording a rule never blocks a card from entering the column.
    card = store.add_card(store.list_columns(doing.board_id)[0].id, "task")
    store.move_card(card.id, doing.id)
    assert store.get_card(card.id).column_id == doing.id

    store.remove_column_rule(rule.id)
    assert len(store.list_column_rules(doing.id)) == 1


def test_blank_rule_type_is_rejected(store: KanbanStore) -> None:
    _board, todo, _doing = _first_two_columns(store)

    with pytest.raises(ValueError):
        store.add_column_rule(todo.id, "  ")


def test_card_links_can_point_at_features_docs_and_more(store: KanbanStore) -> None:
    _board, todo, _doing = _first_two_columns(store)
    card = store.add_card(todo.id, "task")

    feature = store.add_card_link(card.id, kanban_db.LINK_FEATURE, "megalo-linker", "Linker")
    store.add_card_link(card.id, kanban_db.LINK_DOCUMENTATION, "docs/notes.md")

    links = store.list_card_links(card.id)
    assert [(link.link_type, link.target, link.label) for link in links] == [
        (kanban_db.LINK_FEATURE, "megalo-linker", "Linker"),
        (kanban_db.LINK_DOCUMENTATION, "docs/notes.md", ""),
    ]
    store.remove_card_link(feature.id)
    assert len(store.list_card_links(card.id)) == 1
    with pytest.raises(ValueError):
        store.add_card_link(card.id, "feature", " ")


def test_rules_and_links_cascade_on_delete(store: KanbanStore) -> None:
    board, todo, _doing = _first_two_columns(store)
    card = store.add_card(todo.id, "task")
    store.add_card_link(card.id, kanban_db.LINK_FILE, "a.json")
    store.add_column_rule(todo.id, kanban_db.RULE_REQUIRES_TESTS)

    store.delete_board(board.id)

    assert store.list_card_links(card.id) == []
    assert store.list_column_rules(todo.id) == []


# -- change notification -------------------------------------------------------------------------


class _Counter:
    def __init__(self) -> None:
        self.count = 0

    def bump(self) -> None:
        self.count += 1


def test_listeners_fire_once_per_committed_change(store: KanbanStore) -> None:
    counter = _Counter()
    store.add_listener(counter.bump)
    board = store.create_board(store.ensure_project("p").id, "A")
    before = counter.count

    store.add_column(board.id, "Extra")

    assert counter.count == before + 1


def test_batch_coalesces_notifications_into_one(store: KanbanStore) -> None:
    board = store.create_board(store.ensure_project("p").id, "A")
    todo, doing, _done = store.list_columns(board.id)
    a = store.add_card(todo.id, "A")
    counter = _Counter()
    store.add_listener(counter.bump)

    with store.batch():
        store.set_column_cards(todo.id, [])
        store.set_column_cards(doing.id, [a.id])
        assert counter.count == 0

    assert counter.count == 1


def test_batch_with_no_changes_does_not_notify(store: KanbanStore) -> None:
    counter = _Counter()
    store.add_listener(counter.bump)

    with store.batch():
        pass

    assert counter.count == 0


def test_listeners_are_held_weakly_and_removable(store: KanbanStore) -> None:
    import gc

    board = store.create_board(store.ensure_project("p").id, "A")
    kept = _Counter()
    dropped = _Counter()
    removed = _Counter()
    store.add_listener(kept.bump)
    store.add_listener(dropped.bump)
    store.add_listener(removed.bump)
    store.remove_listener(removed.bump)
    del dropped
    gc.collect()

    store.rename_board(board.id, "B")

    assert kept.count == 1
    assert removed.count == 0
