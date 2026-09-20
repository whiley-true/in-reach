"""MainWindow-level Kanban behaviour (PROMPT.md: "the icon should open the side panel ... when clicked
it should load the default board in the editor view")."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from in_reach.app.kanban_db import DB_FILENAME, KanbanStore
from in_reach.ide.kanban_board import KanbanBoardView
from in_reach.ide.main_window import MainWindow


@pytest.fixture
def project_window(qtbot, tmp_path: Path):
    project_dir = tmp_path / ".in-reach"
    project_dir.mkdir()
    (project_dir / ".env").write_text("", encoding="utf-8")
    win = MainWindow(root_dir=tmp_path)
    qtbot.addWidget(win)
    win.show()
    return win


def _project(tmp_path: Path, name: str = "abcd1234", title: str = "First") -> Path:
    folder = tmp_path / name
    (folder / "settings").mkdir(parents=True)
    (folder / "settings" / "settings.json").write_text(json.dumps({"meta": {"title": title}}), encoding="utf-8")
    return folder


def _boards_open(window: MainWindow) -> list[KanbanBoardView]:
    return window.main_panel.kanban_views()


def _db(tmp_path: Path) -> Path:
    return tmp_path / ".in-reach" / DB_FILENAME


# -- opening the default board ------------------------------------------------------------------


def test_clicking_the_kanban_icon_shows_the_panel_and_opens_the_default_board(project_window: MainWindow, tmp_path: Path) -> None:
    project_window._on_project_opened(_project(tmp_path))

    project_window.activity_bar.kanban_button.click()

    assert project_window._sidebar_stack.currentWidget() is project_window.kanban_panel
    views = _boards_open(project_window)
    assert [v.title_label.text() for v in views] == ["Main Board"]
    assert project_window.main_panel.active_pane.currentWidget() is views[0]
    assert [c.title_label.text() for c in views[0].columns] == ["To Do", "In Progress", "Done"]


def test_the_board_tab_is_titled_after_the_board(project_window: MainWindow, tmp_path: Path) -> None:
    project_window._on_project_opened(_project(tmp_path))

    project_window.activity_bar.kanban_button.click()

    pane = project_window.main_panel.active_pane
    assert pane.tabText(pane.currentIndex()) == "Main Board"


def test_clicking_again_after_visiting_another_view_does_not_duplicate_the_tab(project_window: MainWindow, tmp_path: Path) -> None:
    project_window._on_project_opened(_project(tmp_path))
    project_window.activity_bar.kanban_button.click()
    project_window.activity_bar.git_button.click()

    project_window.activity_bar.kanban_button.click()

    assert len(_boards_open(project_window)) == 1


def test_the_default_board_is_the_one_marked_default(project_window: MainWindow, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    project_window._on_project_opened(folder)
    project_window.activity_bar.kanban_button.click()
    store = project_window._kanban_store()
    project_id = store.ensure_project(folder.name).id
    other = store.create_board(project_id, "Backlog")
    store.set_default_board(other.id)
    project_window.main_panel.active_pane.close_current()
    project_window.activity_bar.git_button.click()

    project_window.activity_bar.kanban_button.click()

    assert [v.title_label.text() for v in _boards_open(project_window)] == ["Backlog"]


def test_with_no_project_open_no_board_is_opened_and_no_database_is_created(project_window: MainWindow, tmp_path: Path) -> None:
    project_window.activity_bar.kanban_button.click()

    assert _boards_open(project_window) == []
    assert project_window._sidebar_stack.currentWidget() is project_window._no_project_page
    assert project_window._kanban_store_obj is None
    assert not _db(tmp_path).exists()


def test_the_database_is_only_created_once_the_kanban_view_is_used(project_window: MainWindow, tmp_path: Path) -> None:
    project_window._on_project_opened(_project(tmp_path))
    assert not _db(tmp_path).exists()

    project_window.activity_bar.kanban_button.click()

    assert _db(tmp_path).is_file()


def test_the_database_lives_in_the_shared_in_reach_folder_and_serves_every_project(project_window: MainWindow, tmp_path: Path) -> None:
    first, second = _project(tmp_path, "aaaa1111", "First"), _project(tmp_path, "bbbb2222", "Second")
    project_window.ask_open_in_new_window = lambda folder: "this_window"  # type: ignore[method-assign]
    project_window._on_project_opened(first)
    project_window.activity_bar.kanban_button.click()
    project_window.activity_bar.git_button.click()
    project_window._on_project_opened(second)
    project_window.activity_bar.kanban_button.click()

    store = project_window._kanban_store()

    assert store.db_path == _db(tmp_path)
    assert sorted(p.key for p in store.list_projects()) == ["aaaa1111", "bbbb2222"]
    assert {p.title for p in store.list_projects()} == {"First", "Second"}
    for project_row in store.list_projects():
        assert [b.name for b in store.list_boards(project_row.id)] == ["Main Board"]


def test_the_panel_lists_the_active_projects_boards(project_window: MainWindow, tmp_path: Path) -> None:
    project_window._on_project_opened(_project(tmp_path))

    project_window.activity_bar.kanban_button.click()

    panel = project_window.kanban_panel
    assert [panel.boards_list.item(i).text() for i in range(panel.boards_list.count())] == ["Main Board  (default)"]


# -- panel -> tabs --------------------------------------------------------------------------------


def test_opening_a_board_from_the_panel_opens_its_tab(project_window: MainWindow, tmp_path: Path) -> None:
    project_window._on_project_opened(_project(tmp_path))
    project_window.activity_bar.kanban_button.click()
    store = project_window._kanban_store()
    extra = store.create_board(project_window.kanban_panel.project.id, "Sprint 2")

    project_window.kanban_panel.open_board_requested.emit(extra.id)

    assert sorted(v.title_label.text() for v in _boards_open(project_window)) == ["Main Board", "Sprint 2"]


def test_new_board_from_the_panel_opens_it(project_window: MainWindow, tmp_path: Path, monkeypatch) -> None:
    project_window._on_project_opened(_project(tmp_path))
    project_window.activity_bar.kanban_button.click()
    monkeypatch.setattr(project_window.kanban_panel, "_ask_text", lambda *a, **k: "Brand New")

    project_window.kanban_panel.new_button.click()

    assert "Brand New" in [v.title_label.text() for v in _boards_open(project_window)]


def test_renaming_a_board_retitles_its_tab(project_window: MainWindow, tmp_path: Path, monkeypatch) -> None:
    project_window._on_project_opened(_project(tmp_path))
    project_window.activity_bar.kanban_button.click()
    monkeypatch.setattr(project_window.kanban_panel, "_ask_text", lambda *a, **k: "Renamed Board")
    project_window.kanban_panel.boards_list.setCurrentRow(0)

    project_window.kanban_panel.rename_button.click()

    pane = project_window.main_panel.active_pane
    assert pane.tabText(pane.currentIndex()) == "Renamed Board"
    assert _boards_open(project_window)[0].title_label.text() == "Renamed Board"


def test_deleting_a_board_closes_its_tab(project_window: MainWindow, tmp_path: Path, monkeypatch) -> None:
    project_window._on_project_opened(_project(tmp_path))
    project_window.activity_bar.kanban_button.click()
    monkeypatch.setattr(project_window.kanban_panel, "_confirm_delete", lambda board: True)
    project_window.kanban_panel.boards_list.setCurrentRow(0)

    project_window.kanban_panel.delete_button.click()

    assert _boards_open(project_window) == []


def test_changing_the_background_from_the_panel_repaints_the_open_board(project_window: MainWindow, tmp_path: Path, monkeypatch) -> None:
    project_window._on_project_opened(_project(tmp_path))
    project_window.activity_bar.kanban_button.click()
    monkeypatch.setattr(project_window.kanban_panel, "_ask_color", lambda initial: "#224466")
    project_window.kanban_panel.boards_list.setCurrentRow(0)

    project_window.kanban_panel.color_button.click()

    assert _boards_open(project_window)[0]._canvas.color.name() == "#224466"


def test_a_background_image_is_copied_under_the_in_reach_folder(project_window: MainWindow, tmp_path: Path, monkeypatch) -> None:
    from PyQt6.QtGui import QColor, QPixmap

    project_window._on_project_opened(_project(tmp_path))
    project_window.activity_bar.kanban_button.click()
    picture = tmp_path / "pic.png"
    pixmap = QPixmap(8, 8)
    pixmap.fill(QColor("#00aa00"))
    pixmap.save(str(picture))
    monkeypatch.setattr(project_window.kanban_panel, "_ask_image", lambda: picture)
    project_window.kanban_panel.boards_list.setCurrentRow(0)

    project_window.kanban_panel.image_button.click()

    copies = list((tmp_path / ".in-reach" / "kanban" / "backgrounds").iterdir())
    assert len(copies) == 1
    assert _boards_open(project_window)[0]._canvas.has_image is True


# -- splitting ------------------------------------------------------------------------------------


def test_splitting_a_board_tab_opens_a_second_live_view_of_the_same_board(project_window: MainWindow, tmp_path: Path) -> None:
    project_window._on_project_opened(_project(tmp_path))
    project_window.activity_bar.kanban_button.click()

    project_window.split_active_tab_right()

    views = _boards_open(project_window)
    assert len(views) == 2
    assert views[0].board_id == views[1].board_id
    project_window._kanban_store().add_card(project_window._kanban_store().list_columns(views[0].board_id)[0].id, "shared")
    assert all(v.columns[0].card_list.count() == 1 for v in views)


# -- palette (.claude/rules/shortcuts-and-command-palette.md) ---------------------------------------


def test_palette_has_new_and_open_kanban_board_entries(project_window: MainWindow) -> None:
    labels = [c.label for c in project_window.build_command_palette_commands()]

    assert "New Kanban Board" in labels
    assert "Open Kanban Board" in labels
    assert "Kanban" in labels


def test_open_kanban_board_palette_entry_lists_this_projects_boards(project_window: MainWindow, tmp_path: Path) -> None:
    project_window._on_project_opened(_project(tmp_path))
    project_window.activity_bar.kanban_button.click()
    store = project_window._kanban_store()
    store.create_board(project_window.kanban_panel.project.id, "Backlog")
    project_window.main_panel.active_pane.close_current()

    open_command = next(c for c in project_window.build_command_palette_commands() if c.label == "Open Kanban Board")
    assert [c.label for c in open_command.children] == ["Main Board", "Backlog"]
    next(c for c in open_command.children if c.label == "Backlog").action()

    assert [v.title_label.text() for v in _boards_open(project_window)] == ["Backlog"]


def test_open_kanban_board_palette_entry_is_empty_before_the_store_exists(project_window: MainWindow, tmp_path: Path) -> None:
    project_window._on_project_opened(_project(tmp_path))

    open_command = next(c for c in project_window.build_command_palette_commands() if c.label == "Open Kanban Board")

    assert open_command.children == []
    assert project_window._kanban_store_obj is None  # merely opening the palette never creates the database


def test_new_kanban_board_palette_entry_creates_and_opens_a_board(project_window: MainWindow, tmp_path: Path, monkeypatch) -> None:
    project_window._on_project_opened(_project(tmp_path))
    monkeypatch.setattr(project_window.kanban_panel, "_ask_text", lambda *a, **k: "From Palette")

    next(c for c in project_window.build_command_palette_commands() if c.label == "New Kanban Board").action()

    assert [v.title_label.text() for v in _boards_open(project_window)] == ["From Palette"]


def test_new_kanban_board_with_no_project_is_a_no_op(project_window: MainWindow) -> None:
    project_window.new_kanban_board()

    assert project_window._kanban_store_obj is None
    assert _boards_open(project_window) == []


# -- lifecycle ------------------------------------------------------------------------------------


def test_closing_the_window_closes_the_store(project_window: MainWindow, tmp_path: Path) -> None:
    import sqlite3

    project_window._on_project_opened(_project(tmp_path))
    project_window.activity_bar.kanban_button.click()
    store = project_window._kanban_store()

    project_window.close()

    assert project_window._kanban_store_obj is None
    with pytest.raises(sqlite3.ProgrammingError):
        store.list_projects()


def test_a_second_store_on_the_same_folder_sees_the_same_boards(project_window: MainWindow, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    project_window._on_project_opened(folder)
    project_window.activity_bar.kanban_button.click()

    other = KanbanStore(tmp_path / ".in-reach")
    try:
        project_row = other.ensure_project(folder.name)
        assert [b.name for b in other.list_boards(project_row.id)] == ["Main Board"]
    finally:
        other.close()
