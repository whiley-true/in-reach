from pathlib import Path

from PyQt6.QtWidgets import QApplication

from in_reach.ide.editor import TextEditorWidget, _indent_level
from in_reach.ide.json_highlighter import JsonSyntaxHighlighter


def _has_opaque_pixel(image) -> bool:
    return any(
        image.pixelColor(x, y).alpha() > 0
        for x in range(image.width())
        for y in range(image.height())
    )


def test_editor_reserves_viewport_space_for_the_gutter(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)

    assert editor.viewportMargins().left() == editor.line_number_area_width()
    assert editor.viewportMargins().left() > 0


def test_gutter_width_grows_as_line_count_passes_a_digit_boundary(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)

    editor.setPlainText("\n".join(str(i) for i in range(9)))  # 9 lines -- single digit
    single_digit_width = editor.line_number_area_width()

    editor.setPlainText("\n".join(str(i) for i in range(150)))  # 150 lines -- triple digit
    triple_digit_width = editor.line_number_area_width()

    assert triple_digit_width > single_digit_width


def test_gutter_repaints_wider_when_the_viewport_margin_changes(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.show()
    QApplication.processEvents()

    editor.setPlainText("\n".join(str(i) for i in range(200)))
    QApplication.processEvents()

    assert editor.viewportMargins().left() == editor.line_number_area_width()


def test_line_number_area_paints_visible_digits(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.resize(300, 200)
    editor.setPlainText("\n".join(f"line {i}" for i in range(30)))
    editor.show()
    QApplication.processEvents()
    QApplication.processEvents()

    pixmap = editor._line_number_area.grab()
    assert not pixmap.isNull()
    assert _has_opaque_pixel(pixmap.toImage())


def test_resize_event_repositions_the_gutter_to_fill_the_left_edge(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.show()
    editor.resize(400, 300)
    QApplication.processEvents()

    geometry = editor._line_number_area.geometry()
    assert geometry.left() == editor.contentsRect().left()
    assert geometry.width() == editor.line_number_area_width()
    # The gutter sits below the breadcrumb bar (see test_breadcrumb.py), not the full contents
    # height -- the breadcrumb bar itself owns that top strip.
    assert geometry.top() == editor.contentsRect().top() + editor._breadcrumb.height()
    assert geometry.height() == editor.contentsRect().height() - editor._breadcrumb.height()


def test_scrolling_updates_the_gutter_without_raising(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.resize(300, 100)
    editor.setPlainText("\n".join(f"line {i}" for i in range(200)))
    editor.show()
    QApplication.processEvents()
    width_before_scroll = editor.line_number_area_width()

    editor.verticalScrollBar().setValue(editor.verticalScrollBar().maximum())
    QApplication.processEvents()

    # No crash, and the gutter still reflects the (3-digit) line count -- unchanged by scrolling.
    assert editor.line_number_area_width() == width_before_scroll
    assert editor._line_number_area.isVisible()


# -- breadcrumb -----------------------------------------------------------------------------------


def test_breadcrumb_is_empty_with_no_path(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)

    assert editor._breadcrumb.text() == ""


def test_breadcrumb_shows_the_folder_and_file_name(qtbot) -> None:
    path = Path("/project/edit/rvt/script.txt")
    editor = TextEditorWidget(path=path)
    qtbot.addWidget(editor)

    assert editor._breadcrumb.text() == "rvt > script.txt"


def test_breadcrumb_includes_the_project_name_when_inside_a_real_project(qtbot, tmp_path) -> None:
    # PROMPT.md: "include the project name (not file dir) in the breadcrumb".
    project = tmp_path / "abcd1234"
    (project / "edit" / "rvt").mkdir(parents=True)
    (project / "README.md").write_text("# Slayer Plus\n\nA better slayer.\n", encoding="utf-8")
    path = project / "edit" / "rvt" / "script.txt"
    path.write_text("", encoding="utf-8")

    editor = TextEditorWidget(path=path)
    qtbot.addWidget(editor)

    assert editor._breadcrumb.text() == "Slayer Plus > rvt > script.txt"


def test_breadcrumb_omits_the_project_name_outside_any_real_project(qtbot) -> None:
    path = Path("/project/edit/rvt/script.txt")  # no real README.md ancestor on disk
    editor = TextEditorWidget(path=path)
    qtbot.addWidget(editor)

    assert editor._breadcrumb.text() == "rvt > script.txt"


def test_set_path_refreshes_the_project_name_in_the_breadcrumb(qtbot, tmp_path) -> None:
    project = tmp_path / "abcd1234"
    (project / "settings").mkdir(parents=True)
    (project / "README.md").write_text("# Wave Defense\n", encoding="utf-8")
    path = project / "settings" / "settings.json"
    path.write_text("{}", encoding="utf-8")

    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    assert editor._breadcrumb.text() == ""

    editor.set_path(path)

    assert editor._breadcrumb.text().startswith("Wave Defense > settings > settings.json")


def test_breadcrumb_appends_the_live_json_path_for_a_json_file(qtbot) -> None:
    path = Path("/project/edit/settings/settings.json")
    editor = TextEditorWidget(path=path)
    qtbot.addWidget(editor)
    editor.setPlainText('{\n  "meta": {\n    "title": "Slayer"\n  }\n}')

    cursor = editor.textCursor()
    cursor.setPosition(editor.toPlainText().index('"Slayer"'))
    editor.setTextCursor(cursor)

    assert editor._breadcrumb.text() == "settings > settings.json > meta"


def test_breadcrumb_does_not_append_a_json_path_for_a_non_json_file(qtbot) -> None:
    path = Path("/project/edit/rvt/script.txt")
    editor = TextEditorWidget(path=path)
    qtbot.addWidget(editor)
    editor.setPlainText('{\n  "meta": 1\n}')  # incidentally JSON-shaped, but not a .json file

    cursor = editor.textCursor()
    cursor.setPosition(editor.toPlainText().index("1"))
    editor.setTextCursor(cursor)

    assert editor._breadcrumb.text() == "rvt > script.txt"


def test_set_path_refreshes_the_breadcrumb(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    assert editor._breadcrumb.text() == ""

    editor.set_path(Path("/project/edit/settings/strings.json"))

    assert editor._breadcrumb.text() == "settings > strings.json"


# -- JSON syntax highlighting ------------------------------------------------------------------


def test_a_json_path_attaches_a_highlighter(qtbot) -> None:
    editor = TextEditorWidget(path=Path("/project/edit/settings/settings.json"))
    qtbot.addWidget(editor)

    assert isinstance(editor._highlighter, JsonSyntaxHighlighter)


def test_a_non_json_path_does_not_attach_a_highlighter(qtbot) -> None:
    editor = TextEditorWidget(path=Path("/project/edit/rvt/script.txt"))
    qtbot.addWidget(editor)

    assert editor._highlighter is None


def test_no_path_does_not_attach_a_highlighter(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)

    assert editor._highlighter is None


def test_set_path_attaches_and_detaches_the_highlighter(qtbot) -> None:
    editor = TextEditorWidget(path=Path("/project/edit/settings/settings.json"))
    qtbot.addWidget(editor)
    assert editor._highlighter is not None

    editor.set_path(Path("/project/edit/rvt/script.txt"))

    assert editor._highlighter is None


# -- code folding -----------------------------------------------------------------------------


def test_setting_json_text_computes_fold_ranges(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)

    editor.setPlainText('{\n  "a": 1\n}')

    assert editor._fold_ranges == {0: 2}


def test_toggle_fold_hides_the_interior_blocks(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.setPlainText('{\n  "a": 1\n}')

    editor.toggle_fold(0)

    doc = editor.document()
    # Collapsing hides everything from the line after the opener through the closing bracket's
    # own line inclusive -- same convention as VS Code's own folding (only the opening line stays
    # visible, showing where the fold is).
    assert doc.findBlockByNumber(0).isVisible() is True
    assert doc.findBlockByNumber(1).isVisible() is False
    assert doc.findBlockByNumber(2).isVisible() is False
    assert 0 in editor._collapsed_folds


def test_toggle_fold_again_re_expands_it(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.setPlainText('{\n  "a": 1\n}')
    editor.toggle_fold(0)

    editor.toggle_fold(0)

    doc = editor.document()
    assert doc.findBlockByNumber(1).isVisible() is True
    assert 0 not in editor._collapsed_folds


def test_toggle_fold_on_a_non_foldable_line_is_a_no_op(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.setPlainText('{\n  "a": 1\n}')

    editor.toggle_fold(1)  # not a fold-start line

    assert editor._collapsed_folds == set()


def test_editing_away_a_collapsed_folds_brackets_drops_its_collapsed_state(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.setPlainText('{\n  "a": 1\n}')
    editor.toggle_fold(0)
    assert 0 in editor._collapsed_folds

    editor.setPlainText("no brackets here at all")

    assert editor._collapsed_folds == set()
    assert editor._fold_ranges == {}


def test_clicking_the_gutter_on_a_foldable_line_toggles_it(qtbot) -> None:
    from PyQt6.QtCore import QPoint

    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.resize(300, 200)
    editor.setPlainText('{\n  "a": 1\n}')
    editor.show()
    QApplication.processEvents()

    block = editor.document().findBlockByNumber(0)
    top = round(editor.blockBoundingGeometry(block).translated(editor.contentOffset()).top())
    editor.toggle_fold_at(QPoint(2, top + 2))

    assert 0 in editor._collapsed_folds


def test_clicking_the_gutter_on_a_non_foldable_line_does_nothing(qtbot) -> None:
    from PyQt6.QtCore import QPoint

    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.resize(300, 200)
    editor.setPlainText('{\n  "a": 1\n}')
    editor.show()
    QApplication.processEvents()

    block = editor.document().findBlockByNumber(1)
    top = round(editor.blockBoundingGeometry(block).translated(editor.contentOffset()).top())
    editor.toggle_fold_at(QPoint(2, top + 2))

    assert editor._collapsed_folds == set()


# -- indent guides ------------------------------------------------------------------------------


def test_indent_level_counts_complete_two_space_levels() -> None:
    assert _indent_level("") == 0
    assert _indent_level('"a": 1') == 0
    assert _indent_level('  "a": 1') == 1
    assert _indent_level('    "a": 1') == 2
    assert _indent_level("   odd single space") == 1  # 3 leading spaces -- 1 complete level


def test_indent_guides_paint_a_line_at_each_indent_level(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.resize(300, 200)
    editor.setPlainText('{\n    "a": 1\n}')  # line 1 is indented two levels (4 spaces)
    editor.show()
    QApplication.processEvents()
    QApplication.processEvents()

    space_width = editor.fontMetrics().horizontalAdvance(" ")
    base_x = round(editor.contentOffset().x())
    background = editor.palette().color(editor.backgroundRole())

    pixmap = editor.viewport().grab()
    image = pixmap.toImage()
    block = editor.document().findBlockByNumber(1)
    y = round(editor.blockBoundingGeometry(block).translated(editor.contentOffset()).top()) + 2

    # A guide line should sit at 2 and 4 spaces in -- neither column is the plain background color.
    for level in (1, 2):
        x = base_x + level * 2 * space_width
        assert 0 <= x < image.width()
        assert image.pixelColor(x, y) != background


def test_indent_guides_do_not_crash_on_an_empty_document(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.resize(300, 200)
    editor.show()
    QApplication.processEvents()  # should not raise


# -- live schema validation (PROMPT.md: "highlighting and error message if schema is incorrect") -


def test_a_valid_settings_json_shows_no_error_underline(qtbot, tmp_path) -> None:
    path = tmp_path / "settings.json"
    editor = TextEditorWidget(path=path)
    qtbot.addWidget(editor)

    editor.setPlainText('{"meta": {"source_file": "x.bin", "generated_at": "2026-01-01T00:00:00Z"}}')

    assert editor.extraSelections() == []
    assert editor._error_spans == []
    assert editor._minimap.error_lines == set()


def test_an_invalid_settings_json_shows_an_underline_and_hover_message(qtbot, tmp_path) -> None:
    path = tmp_path / "settings.json"
    editor = TextEditorWidget(path=path)
    qtbot.addWidget(editor)

    text = '{"meta": {"category": "not_a_real_category", "source_file": "x.bin", "generated_at": "2026-01-01T00:00:00Z"}}'
    editor.setPlainText(text)

    selections = editor.extraSelections()
    assert len(selections) == 1
    selected_text = selections[0].cursor.selectedText()
    assert selected_text == '"not_a_real_category"'

    assert len(editor._error_spans) == 1
    start, end, message = editor._error_spans[0]
    assert text[start:end] == '"not_a_real_category"'
    assert "not_a_real_category" in message or "known category" in message
    # The line the offending value sits on (line 0 here) is flagged in the minimap too (PROMPT.md:
    # "it should highlight errors as a line in colour").
    assert editor._minimap.error_lines == {0}


def test_hovering_the_underlined_span_reports_its_error_message_elsewhere_reports_none(qtbot, tmp_path) -> None:
    # PROMPT.md: "it should be a window that appears when hovering on the red underlined text" --
    # exercises the lookup mouseMoveEvent()'s tooltip is driven from, without needing a real
    # (hard to assert against in a headless test) QToolTip popup.
    path = tmp_path / "settings.json"
    editor = TextEditorWidget(path=path)
    qtbot.addWidget(editor)
    editor.resize(400, 200)
    editor.show()
    QApplication.processEvents()
    text = '{"meta": {"category": "not_a_real_category"}}'
    editor.setPlainText(text)
    start, end, message = editor._error_spans[0]

    cursor = editor.textCursor()
    cursor.setPosition((start + end) // 2)
    inside_pos = editor.cursorRect(cursor).center()
    assert editor._error_message_at(inside_pos) == message

    cursor.setPosition(0)
    outside_pos = editor.cursorRect(cursor).center()
    assert editor._error_message_at(outside_pos) is None


def test_fixing_the_error_clears_the_underline_and_minimap_flag(qtbot, tmp_path) -> None:
    path = tmp_path / "settings.json"
    editor = TextEditorWidget(path=path)
    qtbot.addWidget(editor)
    editor.setPlainText('{"meta": {"category": "not_a_real_category"}}')
    assert editor._error_spans != []

    editor.setPlainText('{"meta": {"source_file": "x.bin", "generated_at": "2026-01-01T00:00:00Z"}}')

    assert editor.extraSelections() == []
    assert editor._error_spans == []
    assert editor._minimap.error_lines == set()


def test_a_non_schema_backed_file_never_shows_an_error(qtbot) -> None:
    path = Path("/project/edit/rvt/script.txt")
    editor = TextEditorWidget(path=path)
    qtbot.addWidget(editor)

    editor.setPlainText("this is not json at all, but this file has no schema anyway")

    assert editor._error_spans == []


def test_an_untitled_tab_with_no_path_never_shows_an_error(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)

    editor.setPlainText("{not even valid json")

    assert editor._error_spans == []


# -- minimap (PROMPT.md: "a live code preview on the right hand side next to the scrollbar") -----


def test_editor_reserves_viewport_space_for_the_minimap(qtbot) -> None:
    from in_reach.ide.editor import _MINIMAP_WIDTH

    editor = TextEditorWidget()
    qtbot.addWidget(editor)

    assert editor.viewportMargins().right() == _MINIMAP_WIDTH


def test_resize_event_positions_the_minimap_along_the_right_edge(qtbot) -> None:
    from in_reach.ide.editor import _MINIMAP_WIDTH

    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.show()
    editor.resize(400, 300)
    QApplication.processEvents()

    geometry = editor._minimap.geometry()
    assert geometry.right() == editor.contentsRect().right()
    assert geometry.width() == _MINIMAP_WIDTH
    assert geometry.top() == editor.contentsRect().top() + editor._breadcrumb.height()


def test_minimap_paints_without_raising_on_an_empty_document(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.resize(300, 200)
    editor.show()
    QApplication.processEvents()  # should not raise

    assert not editor._minimap.grab().isNull()


def test_minimap_scroll_to_moves_the_editors_cursor(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.resize(300, 200)
    editor.setPlainText("\n".join(f"line {i}" for i in range(500)))
    editor.show()
    QApplication.processEvents()
    before = editor.textCursor().blockNumber()

    editor._minimap._scroll_to(editor._minimap.height() - 1)  # click near the bottom

    assert editor.textCursor().blockNumber() > before
