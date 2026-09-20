"""Tests for :mod:`in_reach.ide.kanban_panel` (PROMPT.md: "the icon should open the side panel and
allow the user to choose or create a board and set background colour or custom image")."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PyQt6.QtGui import QColor, QPixmap

from in_reach.app.kanban_db import KanbanStore
from in_reach.ide.kanban_panel import KanbanPanel


@pytest.fixture
def store(tmp_path: Path):
    s = KanbanStore(tmp_path / ".in-reach")
    yield s
    s.close()


def _project_folder(tmp_path: Path, name: str = "abcd1234", title: str | None = None) -> Path:
    folder = tmp_path / name
    (folder / "settings").mkdir(parents=True)
    if title:
        (folder / "settings" / "settings.json").write_text(json.dumps({"meta": {"title": title}}), encoding="utf-8")
    return folder


@pytest.fixture
def panel(qtbot, store: KanbanStore, tmp_path: Path) -> KanbanPanel:
    widget = KanbanPanel()
    qtbot.addWidget(widget)
    widget.show()
    widget.set_store(store)
    widget.set_project_folder(_project_folder(tmp_path, title="My Gametype"))
    return widget


def _names(panel: KanbanPanel) -> list[str]:
    return [panel.boards_list.item(i).text() for i in range(panel.boards_list.count())]


def _select(panel: KanbanPanel, row: int) -> None:
    panel.boards_list.setCurrentRow(row)


# -- no project / no store ------------------------------------------------------------------------


def test_starts_with_the_no_project_message_and_everything_disabled(qtbot) -> None:
    panel = KanbanPanel()
    qtbot.addWidget(panel)
    panel.show()

    assert "No project" in panel.status_label.text()
    assert panel.status_label.isVisibleTo(panel) is True
    assert panel.new_button.isEnabled() is False
    assert panel.boards_list.isEnabled() is False


def test_a_project_without_a_store_yet_stays_disabled(qtbot, tmp_path: Path) -> None:
    panel = KanbanPanel()
    qtbot.addWidget(panel)
    panel.set_project_folder(_project_folder(tmp_path))

    assert panel.new_button.isEnabled() is False


def test_closing_the_project_returns_to_the_no_project_state(panel: KanbanPanel) -> None:
    panel.set_project_folder(None)

    assert panel.boards_list.count() == 0
    assert panel.status_label.isVisibleTo(panel) is True
    assert panel.new_button.isEnabled() is False


# -- listing --------------------------------------------------------------------------------------


def test_lists_the_projects_boards_and_marks_the_default(panel: KanbanPanel, store: KanbanStore) -> None:
    project = panel.project
    store.create_board(project.id, "Main")
    store.create_board(project.id, "Backlog")

    assert _names(panel) == ["Main  (default)", "Backlog"]


def test_heading_names_the_project(panel: KanbanPanel) -> None:
    assert panel.boards_label.text() == "Boards -- My Gametype"


def test_each_project_only_sees_its_own_boards(panel: KanbanPanel, store: KanbanStore, tmp_path: Path) -> None:
    store.create_board(panel.project.id, "Mine")
    other = _project_folder(tmp_path, "efgh5678", "Other")

    panel.set_project_folder(other)
    assert _names(panel) == []
    store.create_board(panel.project.id, "Theirs")
    assert _names(panel) == ["Theirs  (default)"]

    panel.set_project_folder(tmp_path / "abcd1234")
    assert _names(panel) == ["Mine  (default)"]
    assert len(store.list_projects()) == 2  # one database, many projects


def test_the_list_follows_changes_made_elsewhere(panel: KanbanPanel, store: KanbanStore) -> None:
    board = store.create_board(panel.project.id, "Main")
    assert _names(panel) == ["Main  (default)"]

    store.rename_board(board.id, "Renamed")

    assert _names(panel) == ["Renamed  (default)"]


def test_the_selection_survives_a_refresh(panel: KanbanPanel, store: KanbanStore) -> None:
    store.create_board(panel.project.id, "A")
    second = store.create_board(panel.project.id, "B")
    _select(panel, 1)

    store.rename_board(second.id, "B2")

    assert panel.selected_board_id() == second.id


def test_buttons_need_a_selected_board(panel: KanbanPanel, store: KanbanStore) -> None:
    store.create_board(panel.project.id, "Main")
    panel.boards_list.clearSelection()
    panel.boards_list.setCurrentRow(-1)
    assert panel.new_button.isEnabled() is True
    for button in (panel.open_button, panel.rename_button, panel.delete_button, panel.default_button, panel.color_button, panel.image_button):
        assert button.isEnabled() is False

    _select(panel, 0)

    for button in (panel.open_button, panel.rename_button, panel.delete_button, panel.default_button, panel.color_button, panel.image_button):
        assert button.isEnabled() is True


# -- create / open / rename / delete / default ----------------------------------------------------


def test_new_board_creates_selects_and_requests_opening_it(panel: KanbanPanel, store: KanbanStore, qtbot, monkeypatch) -> None:
    monkeypatch.setattr(panel, "_ask_text", lambda *a, **k: "Sprint 2")

    with qtbot.waitSignal(panel.open_board_requested) as blocker:
        panel.new_button.click()

    boards = store.list_boards(panel.project.id)
    assert [b.name for b in boards] == ["Sprint 2"]
    assert blocker.args == [boards[0].id]
    assert panel.selected_board_id() == boards[0].id


def test_new_board_cancelled_creates_nothing(panel: KanbanPanel, store: KanbanStore, monkeypatch) -> None:
    monkeypatch.setattr(panel, "_ask_text", lambda *a, **k: None)

    panel.new_board()

    assert store.list_boards(panel.project.id) == []


def test_open_and_double_click_request_the_selected_board(panel: KanbanPanel, store: KanbanStore, qtbot) -> None:
    board = store.create_board(panel.project.id, "Main")
    _select(panel, 0)

    with qtbot.waitSignal(panel.open_board_requested) as blocker:
        panel.open_button.click()
    assert blocker.args == [board.id]

    with qtbot.waitSignal(panel.open_board_requested) as blocker:
        panel.boards_list.itemActivated.emit(panel.boards_list.item(0))
    assert blocker.args == [board.id]


def test_rename_board(panel: KanbanPanel, store: KanbanStore, monkeypatch) -> None:
    board = store.create_board(panel.project.id, "Old")
    _select(panel, 0)
    seen = []
    monkeypatch.setattr(panel, "_ask_text", lambda title, label, default="": seen.append(default) or "New")

    panel.rename_button.click()

    assert seen == ["Old"]
    assert store.get_board(board.id).name == "New"


def test_delete_board_confirms(panel: KanbanPanel, store: KanbanStore, monkeypatch) -> None:
    board = store.create_board(panel.project.id, "Doomed")
    _select(panel, 0)
    monkeypatch.setattr(panel, "_confirm_delete", lambda b: False)
    panel.delete_button.click()
    assert store.get_board(board.id) is not None

    monkeypatch.setattr(panel, "_confirm_delete", lambda b: True)
    panel.delete_button.click()

    assert store.get_board(board.id) is None
    assert _names(panel) == []


def test_set_as_default(panel: KanbanPanel, store: KanbanStore) -> None:
    store.create_board(panel.project.id, "A")
    b = store.create_board(panel.project.id, "B")
    _select(panel, 1)

    panel.default_button.click()

    assert store.default_board(panel.project.id).id == b.id
    assert _names(panel) == ["A", "B  (default)"]


# -- background (PROMPT.md: "set background colour or custom image (which is added to the repo)") --


def test_choosing_a_colour_sets_the_boards_background(panel: KanbanPanel, store: KanbanStore, monkeypatch) -> None:
    board = store.create_board(panel.project.id, "Main")
    _select(panel, 0)
    offered = []
    monkeypatch.setattr(panel, "_ask_color", lambda initial: offered.append(initial) or "#336699")

    panel.color_button.click()

    assert offered == [None]
    assert store.get_board(board.id).background_color == "#336699"


def test_the_colour_picker_starts_on_the_current_colour(panel: KanbanPanel, store: KanbanStore, monkeypatch) -> None:
    board = store.create_board(panel.project.id, "Main", background_color="#abcdef")
    _select(panel, 0)
    offered = []
    monkeypatch.setattr(panel, "_ask_color", lambda initial: offered.append(initial))

    panel.choose_color()

    assert offered == ["#abcdef"]
    assert store.get_board(board.id).background_color == "#abcdef"  # cancelling changed nothing


def test_choosing_an_image_copies_it_into_the_in_reach_folder(panel: KanbanPanel, store: KanbanStore, tmp_path: Path, monkeypatch) -> None:
    board = store.create_board(panel.project.id, "Main")
    _select(panel, 0)
    picture = tmp_path / "wallpaper.png"
    pixmap = QPixmap(20, 20)
    pixmap.fill(QColor("#ff8800"))
    pixmap.save(str(picture))
    monkeypatch.setattr(panel, "_ask_image", lambda: picture)

    panel.image_button.click()

    stored = store.get_board(board.id)
    assert stored.background_image is not None
    copy = store.in_reach_dir / stored.background_image
    assert copy.is_file() and copy != picture
    assert "kanban" in copy.parts and "backgrounds" in copy.parts
    assert not panel.boards_list.item(0).icon().isNull()  # the list shows the image as its thumbnail


def test_choosing_an_image_cancelled_changes_nothing(panel: KanbanPanel, store: KanbanStore, monkeypatch) -> None:
    board = store.create_board(panel.project.id, "Main", background_color="#123456")
    _select(panel, 0)
    monkeypatch.setattr(panel, "_ask_image", lambda: None)

    panel.choose_image()

    assert store.get_board(board.id).background_color == "#123456"


def test_a_missing_image_file_warns_instead_of_crashing(panel: KanbanPanel, store: KanbanStore, tmp_path: Path, monkeypatch) -> None:
    store.create_board(panel.project.id, "Main")
    _select(panel, 0)
    warnings = []
    monkeypatch.setattr(panel, "_ask_image", lambda: tmp_path / "gone.png")
    monkeypatch.setattr(panel, "_warn", warnings.append)

    panel.choose_image()

    assert len(warnings) == 1 and "gone.png" in warnings[0]


def test_clear_removes_the_background(panel: KanbanPanel, store: KanbanStore) -> None:
    board = store.create_board(panel.project.id, "Main", background_color="#123456")
    _select(panel, 0)

    panel.clear_background_button.click()

    assert store.get_board(board.id).background_color is None


def test_a_coloured_board_shows_a_swatch_in_the_list(panel: KanbanPanel, store: KanbanStore) -> None:
    store.create_board(panel.project.id, "Plain")
    store.create_board(panel.project.id, "Blue", background_color="#0000ff")

    assert panel.boards_list.item(0).icon().isNull()
    assert not panel.boards_list.item(1).icon().isNull()


# -- default selection ----------------------------------------------------------------------------


def test_the_default_board_is_selected_automatically(panel: KanbanPanel, store: KanbanStore) -> None:
    store.create_board(panel.project.id, "First")
    second = store.create_board(panel.project.id, "Second")
    store.set_default_board(second.id)
    panel.boards_list.setCurrentRow(-1)

    panel.refresh()

    assert panel.selected_board_id() == second.id
    assert panel.open_button.isEnabled() is True


def test_a_board_action_is_available_straight_after_opening_a_project(panel: KanbanPanel, store: KanbanStore) -> None:
    board = store.create_board(panel.project.id, "Main")

    assert panel.selected_board_id() == board.id
    assert panel.color_button.isEnabled() is True
