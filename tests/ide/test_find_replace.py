from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPlainTextEdit

from in_reach.ide.editor import TextEditorWidget
from in_reach.ide.find_replace import FindReplaceBar, compile_search_pattern, preserve_case
from in_reach.ide.main_window import MainWindow

# -- compile_search_pattern --------------------------------------------------------------------


def test_compile_search_pattern_returns_none_for_an_empty_query() -> None:
    assert compile_search_pattern("", match_case=False, whole_word=False, regex=False) is None


def test_compile_search_pattern_returns_none_for_invalid_regex() -> None:
    assert compile_search_pattern("(", match_case=False, whole_word=False, regex=True) is None


def test_compile_search_pattern_is_case_insensitive_by_default() -> None:
    pattern = compile_search_pattern("cat", match_case=False, whole_word=False, regex=False)
    assert pattern.search("The CAT sat") is not None


def test_compile_search_pattern_match_case_is_case_sensitive() -> None:
    pattern = compile_search_pattern("cat", match_case=True, whole_word=False, regex=False)
    assert pattern.search("CAT") is None
    assert pattern.search("cat") is not None


def test_compile_search_pattern_whole_word_excludes_substring_matches() -> None:
    pattern = compile_search_pattern("cat", match_case=False, whole_word=True, regex=False)
    assert pattern.search("category") is None
    assert pattern.search("a cat sat") is not None


def test_compile_search_pattern_regex_mode_uses_the_query_as_a_real_pattern() -> None:
    pattern = compile_search_pattern(r"c.t", match_case=False, whole_word=False, regex=True)
    assert pattern.search("cot") is not None


def test_compile_search_pattern_non_regex_mode_escapes_special_characters() -> None:
    pattern = compile_search_pattern("a.b", match_case=False, whole_word=False, regex=False)
    assert pattern.search("axb") is None
    assert pattern.search("a.b") is not None


# -- preserve_case ------------------------------------------------------------------------------


def test_preserve_case_all_uppercase_original_uppercases_the_replacement() -> None:
    assert preserve_case("CAT", "dog") == "DOG"


def test_preserve_case_capitalized_original_capitalizes_the_replacement() -> None:
    assert preserve_case("Cat", "dog") == "Dog"


def test_preserve_case_lowercase_original_leaves_the_replacement_alone() -> None:
    assert preserve_case("cat", "dog") == "dog"


def test_preserve_case_mixed_case_original_leaves_the_replacement_alone() -> None:
    assert preserve_case("cAt", "dog") == "dog"


# -- FindReplaceBar: open/close ------------------------------------------------------------------


def _bar(qtbot, text: str = "") -> tuple[FindReplaceBar, QPlainTextEdit]:
    edit = QPlainTextEdit()
    edit.setPlainText(text)
    qtbot.addWidget(edit)
    # bar's Qt parent is edit itself (not None) -- both need to be part of the same visible top-
    # level window for real OS-level focus transfer between them (a bare setFocus() on an orphaned
    # top-level widget is unreliable in a headless test run) to actually work, see
    # test_close_bar_hides_it_and_returns_focus_to_the_editor.
    bar = FindReplaceBar(edit, edit)
    edit.show()
    return bar, edit


def test_bar_starts_hidden(qtbot) -> None:
    bar, _edit = _bar(qtbot)
    assert bar.isVisible() is False


def test_open_in_find_mode_shows_only_the_find_row_and_focuses_it(qtbot) -> None:
    bar, _edit = _bar(qtbot)
    bar.show()

    bar.open(replace=False)

    assert bar.isVisible() is True
    assert bar._replace_row.isVisible() is False
    qtbot.waitUntil(lambda: bar.find_input.hasFocus(), timeout=2000)


def test_open_in_replace_mode_shows_the_replace_row_and_focuses_it(qtbot) -> None:
    bar, _edit = _bar(qtbot)
    bar.show()

    bar.open(replace=True)

    assert bar._replace_row.isVisible() is True
    qtbot.waitUntil(lambda: bar.replace_input.hasFocus(), timeout=2000)


def test_close_bar_hides_it_and_returns_focus_to_the_editor(qtbot) -> None:
    bar, edit = _bar(qtbot)
    edit.show()
    bar.show()
    bar.open()

    bar.close_bar()

    assert bar.isVisible() is False
    qtbot.waitUntil(lambda: edit.hasFocus(), timeout=2000)


def test_escape_in_the_find_field_closes_the_bar(qtbot) -> None:
    bar, edit = _bar(qtbot)
    edit.show()
    bar.show()
    bar.open()

    qtbot.keyClick(bar.find_input, Qt.Key.Key_Escape)

    assert bar.isVisible() is False


# -- FindReplaceBar: search -----------------------------------------------------------------------


def test_typing_a_query_selects_the_first_match_and_shows_the_count(qtbot) -> None:
    bar, edit = _bar(qtbot, "cat cat cat")
    bar.open()

    bar.find_input.setText("cat")

    assert bar._matches == [(0, 3), (4, 7), (8, 11)]
    assert bar.count_label.text() == "1 of 3"
    assert edit.textCursor().selectedText() == "cat"


def test_no_matches_shows_no_results(qtbot) -> None:
    bar, _edit = _bar(qtbot, "cat cat cat")
    bar.open()

    bar.find_input.setText("dog")

    assert bar._matches == []
    assert bar.count_label.text() == "No results"


def test_find_next_wraps_around_to_the_first_match(qtbot) -> None:
    bar, _edit = _bar(qtbot, "cat cat cat")
    bar.open()
    bar.find_input.setText("cat")
    assert bar._current == 0

    bar.find_next()
    bar.find_next()
    assert bar._current == 2

    bar.find_next()  # wraps
    assert bar._current == 0


def test_find_previous_wraps_around_to_the_last_match(qtbot) -> None:
    bar, _edit = _bar(qtbot, "cat cat cat")
    bar.open()
    bar.find_input.setText("cat")
    assert bar._current == 0

    bar.find_previous()  # wraps backward

    assert bar._current == 2


def test_enter_in_the_find_field_finds_next_and_shift_enter_finds_previous(qtbot) -> None:
    bar, _edit = _bar(qtbot, "cat cat cat")
    bar.open()
    bar.find_input.setText("cat")

    qtbot.keyClick(bar.find_input, Qt.Key.Key_Return)
    assert bar._current == 1

    qtbot.keyClick(bar.find_input, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert bar._current == 0


def test_match_case_toggle_narrows_the_matches(qtbot) -> None:
    bar, _edit = _bar(qtbot, "Cat cat CAT")
    bar.open()
    bar.find_input.setText("cat")
    assert len(bar._matches) == 3

    bar.match_case_button.setChecked(True)

    assert bar._matches == [(4, 7)]


def test_whole_word_toggle_excludes_substring_matches(qtbot) -> None:
    bar, _edit = _bar(qtbot, "cat category")
    bar.open()
    bar.find_input.setText("cat")
    assert len(bar._matches) == 2

    bar.whole_word_button.setChecked(True)

    assert bar._matches == [(0, 3)]


def test_regex_toggle_treats_the_query_as_a_real_pattern(qtbot) -> None:
    bar, _edit = _bar(qtbot, "cat1 cat2 dog3")
    bar.open()
    bar.regex_button.setChecked(True)

    bar.find_input.setText(r"cat\d")

    assert bar._matches == [(0, 4), (5, 9)]


def test_find_in_selection_restricts_matches_to_the_captured_selection(qtbot) -> None:
    bar, edit = _bar(qtbot, "aaa bbb aaa ccc aaa")
    bar.open()
    bar.find_input.setText("")  # clear before selecting, so the selection below isn't overwritten

    cursor = edit.textCursor()
    cursor.setPosition(8)
    cursor.setPosition(16, cursor.MoveMode.KeepAnchor)
    edit.setTextCursor(cursor)

    bar.find_in_selection_button.setChecked(True)
    bar.find_input.setText("aaa")

    assert bar._matches == [(8, 11)]


def test_turning_off_find_in_selection_searches_the_whole_document_again(qtbot) -> None:
    bar, edit = _bar(qtbot, "aaa bbb aaa ccc aaa")
    bar.open()
    bar.find_input.setText("")
    cursor = edit.textCursor()
    cursor.setPosition(8)
    cursor.setPosition(16, cursor.MoveMode.KeepAnchor)
    edit.setTextCursor(cursor)
    bar.find_in_selection_button.setChecked(True)
    bar.find_input.setText("aaa")
    assert bar._matches == [(8, 11)]

    bar.find_in_selection_button.setChecked(False)

    assert bar._matches == [(0, 3), (8, 11), (16, 19)]


# -- FindReplaceBar: replace ---------------------------------------------------------------------


def test_replace_current_replaces_only_the_selected_match(qtbot) -> None:
    bar, edit = _bar(qtbot, "cat cat cat")
    bar.open(replace=True)
    bar.find_input.setText("cat")
    bar.replace_input.setText("dog")

    bar.replace_current()

    assert edit.toPlainText() == "dog cat cat"


def test_enter_in_the_replace_field_replaces_the_current_match(qtbot) -> None:
    bar, edit = _bar(qtbot, "cat cat cat")
    bar.open(replace=True)
    bar.find_input.setText("cat")
    bar.replace_input.setText("dog")

    qtbot.keyClick(bar.replace_input, Qt.Key.Key_Return)

    assert edit.toPlainText() == "dog cat cat"


def test_ctrl_shift_enter_in_the_replace_field_replaces_all(qtbot) -> None:
    bar, edit = _bar(qtbot, "cat cat cat")
    bar.open(replace=True)
    bar.find_input.setText("cat")
    bar.replace_input.setText("dog")

    qtbot.keyClick(
        bar.replace_input,
        Qt.Key.Key_Return,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )

    assert edit.toPlainText() == "dog dog dog"


def test_replace_all_replaces_every_match_in_one_undo_step(qtbot) -> None:
    bar, edit = _bar(qtbot, "foo bar foo baz foo")
    bar.open(replace=True)
    bar.find_input.setText("foo")
    bar.replace_input.setText("QUX")

    bar.replace_all()

    assert edit.toPlainText() == "QUX bar QUX baz QUX"
    edit.undo()
    assert edit.toPlainText() == "foo bar foo baz foo"


def test_replace_all_with_a_longer_replacement_does_not_corrupt_later_matches(qtbot) -> None:
    # Regression guard: replacing forwards would shift every match after the first one once the
    # replacement text is a different length than the original -- replace_all() must work from the
    # end of the document backwards instead.
    bar, edit = _bar(qtbot, "x x x")
    bar.open(replace=True)
    bar.find_input.setText("x")
    bar.replace_input.setText("longer")

    bar.replace_all()

    assert edit.toPlainText() == "longer longer longer"


def test_preserve_case_toggle_applies_the_heuristic_on_replace(qtbot) -> None:
    bar, edit = _bar(qtbot, "Cat cat CAT")
    bar.open(replace=True)
    bar.find_input.setText("cat")
    bar.replace_input.setText("dog")
    bar.preserve_case_button.setChecked(True)

    bar.replace_all()

    assert edit.toPlainText() == "Dog dog DOG"


# -- TextEditorWidget integration -----------------------------------------------------------------


@pytest.fixture
def project_window_with_text_tab(qtbot, tmp_path: Path) -> tuple[MainWindow, TextEditorWidget]:
    project_dir = tmp_path / ".in-reach"
    project_dir.mkdir()
    (project_dir / ".env").write_text("", encoding="utf-8")
    window = MainWindow(root_dir=tmp_path)
    qtbot.addWidget(window)
    window.show()
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    window.open_quick_access_file(path)
    editor = window._active_text_editor()
    assert editor is not None
    return window, editor


def test_open_find_shows_the_tabs_own_bar(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.show()

    editor.open_find()

    assert editor._find_bar.isVisible() is True
    assert editor._find_bar._replace_row.isVisible() is False


def test_open_find_with_replace_shows_the_replace_row(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.show()

    editor.open_find(replace=True)

    assert editor._find_bar._replace_row.isVisible() is True


def test_close_find_hides_the_bar(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.show()
    editor.open_find()

    editor.close_find()

    assert editor._find_bar.isVisible() is False


def test_main_window_edit_find_opens_the_active_tabs_bar(project_window_with_text_tab) -> None:
    window, editor = project_window_with_text_tab

    window.edit_find()

    assert editor._find_bar.isVisible() is True
    assert editor._find_bar._replace_row.isVisible() is False


def test_main_window_edit_replace_opens_the_active_tabs_bar_in_replace_mode(
    project_window_with_text_tab,
) -> None:
    window, editor = project_window_with_text_tab

    window.edit_replace()

    assert editor._find_bar.isVisible() is True
    assert editor._find_bar._replace_row.isVisible() is True
