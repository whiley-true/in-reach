"""Tests for :mod:`in_reach.ide.notepad` -- the Dashboard's Notepad box -- and its placement in
:class:`~in_reach.ide.explorer.ExplorerPanel` (PROMPT.md: "in dashboard please add a 'Notepad'
section that should be box at the bottom that loads the contents of a notepad (with line nums)")."""

from __future__ import annotations

from pathlib import Path

import pytest

from in_reach.ide.explorer import ExplorerPanel
from in_reach.ide.notepad import AUTOSAVE_DELAY_MS, NOTEPAD_PLACEHOLDER, NotepadBox, NotepadEdit


@pytest.fixture
def box(qtbot) -> NotepadBox:
    widget = NotepadBox()
    qtbot.addWidget(widget)
    widget.show()
    return widget


def test_placeholder_is_the_text_the_prompt_asked_for(box: NotepadBox) -> None:
    assert box.edit.placeholderText() == (
        "- Use this space for any rough notes. For more structured Documentation use the Documentation Panel"
    )
    assert box.edit.placeholderText() == NOTEPAD_PLACEHOLDER


def test_starts_unbound_and_disabled(box: NotepadBox) -> None:
    assert box.path is None
    assert box.edit.isEnabled() is False
    assert box.open_in_editor_button.isEnabled() is False
    assert box.open_in_window_button.isEnabled() is False


def test_set_path_loads_the_files_content_and_enables_the_box(box: NotepadBox, tmp_path: Path) -> None:
    notes = tmp_path / "Notes.txt"
    notes.write_text("line one\nline two\n", encoding="utf-8")

    box.set_path(notes)

    assert box.edit.toPlainText() == "line one\nline two\n"
    assert box.edit.isEnabled() is True
    assert box.open_in_editor_button.isEnabled() is True
    assert box.open_in_window_button.isEnabled() is True


def test_a_missing_file_loads_empty_and_is_not_created_by_loading(box: NotepadBox, tmp_path: Path) -> None:
    notes = tmp_path / "Notes.txt"

    box.set_path(notes)

    assert box.edit.toPlainText() == ""
    assert not notes.exists()


def test_typing_autosaves_after_the_delay(box: NotepadBox, tmp_path: Path, qtbot) -> None:
    notes = tmp_path / "Notes.txt"
    box.set_path(notes)

    box.edit.setPlainText("jotted down")
    assert not notes.exists()  # not written synchronously on every keystroke

    qtbot.waitUntil(lambda: notes.exists(), timeout=AUTOSAVE_DELAY_MS * 5)
    assert notes.read_text(encoding="utf-8") == "jotted down"


def test_flush_writes_immediately_and_emits_saved(box: NotepadBox, tmp_path: Path, qtbot) -> None:
    notes = tmp_path / "Notes.txt"
    box.set_path(notes)
    box.edit.setPlainText("now")

    with qtbot.waitSignal(box.saved) as blocker:
        box.flush()

    assert blocker.args == [notes]
    assert notes.read_text(encoding="utf-8") == "now"


def test_flush_with_nothing_pending_does_nothing(box: NotepadBox, tmp_path: Path) -> None:
    notes = tmp_path / "Notes.txt"
    notes.write_text("keep", encoding="utf-8")
    box.set_path(notes)
    seen = []
    box.saved.connect(seen.append)

    box.flush()

    assert seen == []
    assert notes.read_text(encoding="utf-8") == "keep"


def test_loading_a_file_does_not_count_as_an_edit(box: NotepadBox, tmp_path: Path) -> None:
    notes = tmp_path / "Notes.txt"
    notes.write_text("loaded", encoding="utf-8")
    seen = []
    box.saved.connect(seen.append)

    box.set_path(notes)
    box.flush()

    assert seen == []


def test_switching_files_flushes_the_previous_ones_pending_text_first(box: NotepadBox, tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    second.write_text("second's own", encoding="utf-8")
    box.set_path(first)
    box.edit.setPlainText("typed for first")

    box.set_path(second)

    assert first.read_text(encoding="utf-8") == "typed for first"
    assert box.edit.toPlainText() == "second's own"
    assert second.read_text(encoding="utf-8") == "second's own"


def test_unbinding_flushes_and_disables(box: NotepadBox, tmp_path: Path) -> None:
    notes = tmp_path / "Notes.txt"
    box.set_path(notes)
    box.edit.setPlainText("last words")

    box.set_path(None)

    assert notes.read_text(encoding="utf-8") == "last words"
    assert box.edit.isEnabled() is False
    assert box.edit.toPlainText() == ""


def test_reload_rereads_from_disk_and_drops_pending_text(box: NotepadBox, tmp_path: Path) -> None:
    notes = tmp_path / "Notes.txt"
    notes.write_text("v1", encoding="utf-8")
    box.set_path(notes)
    box.edit.setPlainText("pending, never flushed")
    notes.write_text("v2 from elsewhere", encoding="utf-8")

    box.reload()
    box.flush()

    assert box.edit.toPlainText() == "v2 from elsewhere"
    assert notes.read_text(encoding="utf-8") == "v2 from elsewhere"


def test_non_utf8_content_loads_as_empty_rather_than_crashing(box: NotepadBox, tmp_path: Path) -> None:
    notes = tmp_path / "Notes.txt"
    notes.write_bytes(b"\xff\xfe\x00bad")

    box.set_path(notes)

    assert box.edit.toPlainText() == ""


def test_buttons_emit_their_request_signals(box: NotepadBox, tmp_path: Path, qtbot) -> None:
    box.set_path(tmp_path / "Notes.txt")

    with qtbot.waitSignal(box.open_in_editor_requested):
        box.open_in_editor_button.click()
    with qtbot.waitSignal(box.open_in_window_requested):
        box.open_in_window_button.click()


# -- line numbers -----------------------------------------------------------------------------------


def test_gutter_grows_with_the_line_count(qtbot) -> None:
    edit = NotepadEdit()
    qtbot.addWidget(edit)
    edit.show()
    narrow = edit.gutter_width()

    edit.setPlainText("\n".join(str(i) for i in range(1200)))

    assert edit.gutter_width() > narrow
    assert edit.viewportMargins().left() == edit.gutter_width()


def test_gutter_paints_line_numbers(qtbot) -> None:
    edit = NotepadEdit()
    qtbot.addWidget(edit)
    edit.resize(300, 200)
    edit.show()
    edit.setPlainText("a\nb\nc\nd")

    pixmap = edit._gutter.grab()
    image = pixmap.toImage()
    background = image.pixelColor(1, 1)
    painted = sum(
        1
        for x in range(image.width())
        for y in range(image.height())
        if image.pixelColor(x, y) != background
    )

    assert edit._gutter.width() == edit.gutter_width()
    assert painted > 0  # digits were drawn over the gutter's own fill


def test_gutter_sits_at_the_left_edge_of_the_box(qtbot) -> None:
    edit = NotepadEdit()
    qtbot.addWidget(edit)
    edit.resize(300, 200)
    edit.show()

    assert edit._gutter.x() == edit.contentsRect().left()
    assert edit._gutter.height() == edit.contentsRect().height()


# -- placement in the Dashboard -------------------------------------------------------------------


@pytest.fixture
def explorer(qtbot) -> ExplorerPanel:
    panel = ExplorerPanel()
    qtbot.addWidget(panel)
    panel.show()
    return panel


def test_notepad_section_is_hidden_with_no_project(explorer: ExplorerPanel) -> None:
    assert explorer.notepad_section.isVisible() is False
    assert explorer.notepad.path is None


def test_opening_a_project_shows_the_notepad_bound_to_its_notes_file(explorer: ExplorerPanel, tmp_path: Path) -> None:
    (tmp_path / "Notes.txt").write_text("project notes\n", encoding="utf-8")

    explorer.open_project(tmp_path)

    assert explorer.notepad_section.isVisible() is True
    assert explorer.notepad.path == tmp_path / "Notes.txt"
    assert explorer.notepad.edit.toPlainText() == "project notes\n"


def test_closing_the_project_unbinds_the_notepad(explorer: ExplorerPanel, tmp_path: Path) -> None:
    explorer.open_project(tmp_path)

    explorer.close_active_project()

    assert explorer.notepad.path is None
    assert explorer.notepad_section.isVisible() is False


def test_notepad_is_the_last_section_of_the_dashboard(explorer: ExplorerPanel, tmp_path: Path) -> None:
    explorer.open_project(tmp_path)
    layout = explorer.layout()

    sections = [layout.itemAt(i).widget() for i in range(layout.count()) if layout.itemAt(i).widget()]

    assert sections[-1] is explorer.notepad_section
    assert layout.stretch(layout.indexOf(explorer.notepad_section)) == 1


def test_notepad_request_signals_are_relayed_by_the_dashboard(explorer: ExplorerPanel, tmp_path: Path, qtbot) -> None:
    explorer.open_project(tmp_path)

    with qtbot.waitSignal(explorer.notepad_open_in_editor_requested):
        explorer.notepad.open_in_editor_button.click()
    with qtbot.waitSignal(explorer.notepad_open_in_window_requested):
        explorer.notepad.open_in_window_button.click()


def test_notepad_autosave_is_relayed_by_the_dashboard(explorer: ExplorerPanel, tmp_path: Path, qtbot) -> None:
    explorer.open_project(tmp_path)
    explorer.notepad.edit.setPlainText("typed")

    with qtbot.waitSignal(explorer.notepad_saved) as blocker:
        explorer.notepad.flush()

    assert blocker.args == [tmp_path / "Notes.txt"]
