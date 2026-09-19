"""``MainPanelArea``/``TabPane`` additions for the Search panel's "Search only in Open Editors" and
for Kanban board tabs."""

from __future__ import annotations

from pathlib import Path

import pytest

from in_reach.app.kanban_db import KanbanStore
from in_reach.ide.kanban_board import KanbanBoardView
from in_reach.ide.main_window import MainWindow


@pytest.fixture
def window(qtbot, tmp_path: Path):
    project_dir = tmp_path / ".in-reach"
    project_dir.mkdir()
    (project_dir / ".env").write_text("", encoding="utf-8")
    win = MainWindow(root_dir=tmp_path)
    qtbot.addWidget(win)
    win.show()
    return win


@pytest.fixture
def store(tmp_path: Path):
    s = KanbanStore(tmp_path / "kanban-store")
    yield s
    s.close()


@pytest.fixture
def board(store: KanbanStore):
    return store.create_board(store.ensure_project("p", "P").id, "Sprint")


# -- open_file_paths --------------------------------------------------------------------------------


def test_open_file_paths_lists_every_open_file_tab(window: MainWindow, tmp_path: Path) -> None:
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("a", encoding="utf-8")
    b.write_text("b", encoding="utf-8")
    pane = window.main_panel.active_pane
    pane.open_file(a)
    window.main_panel.new_tab_in(pane)  # a second tab, so the first isn't replaced by the next open
    pane.open_file(b)

    assert window.main_panel.open_file_paths() == {a, b}


def test_open_file_paths_ignores_tabs_with_no_file(window: MainWindow) -> None:
    window.main_panel.new_tab_in(window.main_panel.active_pane)  # an Untitled tab

    assert window.main_panel.open_file_paths() == set()


def test_open_file_paths_includes_popout_windows(window: MainWindow, tmp_path: Path) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text("x", encoding="utf-8")
    pane = window.main_panel.active_pane
    pane.open_file(notes)
    popout = window.main_panel.move_tab_to_new_window(pane, pane.currentIndex())

    assert notes in window.main_panel.open_file_paths()

    popout.force_close()


def test_open_file_paths_drops_a_file_once_its_tab_is_closed(window: MainWindow, tmp_path: Path) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text("x", encoding="utf-8")
    pane = window.main_panel.active_pane
    pane.open_file(notes)
    assert notes in window.main_panel.open_file_paths()

    pane.close_current()

    assert notes not in window.main_panel.open_file_paths()


# -- Kanban board tabs ----------------------------------------------------------------------------


def test_open_kanban_board_adds_a_tab_titled_after_the_board(window: MainWindow, store: KanbanStore, board) -> None:
    pane = window.main_panel.active_pane

    pane.open_kanban_board(store, board.id)

    assert isinstance(pane.currentWidget(), KanbanBoardView)
    assert pane.tabText(pane.currentIndex()) == "Sprint"
    assert not pane.tabIcon(pane.currentIndex()).isNull()


def test_open_kanban_board_switches_to_an_already_open_board_instead_of_duplicating(window: MainWindow, store: KanbanStore, board) -> None:
    pane = window.main_panel.active_pane
    pane.open_kanban_board(store, board.id)
    board_index = pane.currentIndex()
    window.main_panel.new_tab_in(pane)
    assert pane.currentIndex() != board_index

    pane.open_kanban_board(store, board.id)

    assert pane.currentIndex() == board_index
    assert len(window.main_panel.kanban_views()) == 1


def test_open_kanban_board_for_a_missing_board_opens_nothing(window: MainWindow, store: KanbanStore) -> None:
    pane = window.main_panel.active_pane
    before = pane.count()

    pane.open_kanban_board(store, 99999)

    assert pane.count() == before


def test_a_board_tab_never_collides_with_file_tab_dedup(window: MainWindow, store: KanbanStore, board, tmp_path: Path) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text("x", encoding="utf-8")
    pane = window.main_panel.active_pane
    pane.open_kanban_board(store, board.id)
    window.main_panel.new_tab_in(pane)

    pane.open_file(notes)

    assert window.main_panel.open_file_paths() == {notes}
    assert len(window.main_panel.kanban_views()) == 1


def test_a_board_tab_can_be_closed_without_a_save_prompt(window: MainWindow, store: KanbanStore, board) -> None:
    pane = window.main_panel.active_pane
    pane.open_kanban_board(store, board.id)

    assert pane.close_current() is True

    assert window.main_panel.kanban_views() == []


def test_refresh_kanban_tabs_retitles_and_closes(window: MainWindow, store: KanbanStore, board) -> None:
    other = store.create_board(board.project_id, "Other")
    pane = window.main_panel.active_pane
    pane.open_kanban_board(store, board.id)
    pane.open_kanban_board(store, other.id)

    store.rename_board(board.id, "Renamed")
    window.main_panel.refresh_kanban_tabs()
    titles = [pane.tabText(i) for i in range(pane.count())]
    assert "Renamed" in titles and "Sprint" not in titles

    store.delete_board(other.id)
    window.main_panel.refresh_kanban_tabs()
    assert [v.board_id for v in window.main_panel.kanban_views()] == [board.id]


def test_a_board_tab_moves_to_a_popout_window_and_still_refreshes(window: MainWindow, store: KanbanStore, board) -> None:
    pane = window.main_panel.active_pane
    pane.open_kanban_board(store, board.id)
    popout = window.main_panel.move_tab_to_new_window(pane, pane.currentIndex())

    store.rename_board(board.id, "In A Window")
    window.main_panel.refresh_kanban_tabs()

    assert popout.pane.tabText(0) == "In A Window"
    popout.force_close()


def test_splitting_duplicates_a_board_tab_rather_than_showing_a_welcome_tab(window: MainWindow, store: KanbanStore, board) -> None:
    pane = window.main_panel.active_pane
    pane.open_kanban_board(store, board.id)

    window.main_panel.split_from(pane)

    views = window.main_panel.kanban_views()
    assert len(views) == 2 and views[0] is not views[1]
    assert {v.board_id for v in views} == {board.id}


def test_a_closed_board_tab_stops_listening_to_the_store(window: MainWindow, store: KanbanStore, board) -> None:
    from PyQt6 import sip
    from PyQt6.QtCore import QCoreApplication, QEvent

    pane = window.main_panel.active_pane
    pane.open_kanban_board(store, board.id)
    view = window.main_panel.kanban_views()[0]
    pane.close_current()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert sip.isdeleted(view)

    store.add_column(board.id, "added after the tab closed")  # must not raise

    assert not any(getattr(ref(), "__self__", None) is view for ref in store._listeners)
