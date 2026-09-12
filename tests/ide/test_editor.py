from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPalette, QTextFormat
from PyQt6.QtWidgets import QApplication

from in_reach.app import indent_settings
from in_reach.ide import indent_state
from in_reach.ide.editor import TextEditorWidget, _indent_level
from in_reach.ide.json_highlighter import JsonSyntaxHighlighter


@pytest.fixture(autouse=True)
def _reset_indent_state():
    # indent_state is process-global (see its own module docstring) -- reset it around every test
    # here so one test's Tab-key setting can't leak into the next.
    saved = indent_state.get_indent()
    yield
    indent_state.set_indent(*saved)


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
    path = Path("/project/script/output.txt")
    editor = TextEditorWidget(path=path)
    qtbot.addWidget(editor)

    assert editor._breadcrumb.text() == "script > output.txt"


def test_breadcrumb_includes_the_project_name_when_inside_a_real_project(qtbot, tmp_path) -> None:
    # PROMPT.md: "include the project name (not file dir) in the breadcrumb".
    project = tmp_path / "abcd1234"
    (project / "script").mkdir(parents=True)
    (project / "Notes.txt").write_text("Use this space for free form notes.\n", encoding="utf-8")
    (project / "settings").mkdir(parents=True)
    (project / "settings" / "settings.json").write_text(
        '{"meta": {"title": "Slayer Plus"}}', encoding="utf-8"
    )
    path = project / "script" / "output.txt"
    path.write_text("", encoding="utf-8")

    editor = TextEditorWidget(path=path)
    qtbot.addWidget(editor)

    assert editor._breadcrumb.text() == "Slayer Plus > script > output.txt"


def test_breadcrumb_omits_the_project_name_outside_any_real_project(qtbot) -> None:
    path = Path("/project/script/output.txt")  # no real Notes.txt ancestor on disk
    editor = TextEditorWidget(path=path)
    qtbot.addWidget(editor)

    assert editor._breadcrumb.text() == "script > output.txt"


def test_set_path_refreshes_the_project_name_in_the_breadcrumb(qtbot, tmp_path) -> None:
    project = tmp_path / "abcd1234"
    (project / "settings").mkdir(parents=True)
    (project / "Notes.txt").write_text("Use this space for free form notes.\n", encoding="utf-8")
    path = project / "settings" / "settings.json"
    path.write_text('{"meta": {"title": "Wave Defense"}}', encoding="utf-8")

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
    path = Path("/project/script/output.txt")
    editor = TextEditorWidget(path=path)
    qtbot.addWidget(editor)
    editor.setPlainText('{\n  "meta": 1\n}')  # incidentally JSON-shaped, but not a .json file

    cursor = editor.textCursor()
    cursor.setPosition(editor.toPlainText().index("1"))
    editor.setTextCursor(cursor)

    assert editor._breadcrumb.text() == "script > output.txt"


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
    editor = TextEditorWidget(path=Path("/project/script/output.txt"))
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

    editor.set_path(Path("/project/script/output.txt"))

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
    background = editor.palette().color(QPalette.ColorRole.Base)  # the minimap's own fill color

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
    path = Path("/project/script/output.txt")
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


def _non_background_pixels(image, background) -> int:
    return sum(
        1
        for x in range(image.width())
        for y in range(image.height())
        if image.pixelColor(x, y) != background
    )


def test_minimap_renders_text_not_solid_blocks(qtbot) -> None:
    # PROMPT.md: "and should contain text instead of blocks" -- a real (if tiny) glyph rendering
    # paints a sparser set of pixels than a filled bar covering the same line would, so a document
    # with real content still leaves most of its own line height untouched, unlike the old
    # solid-bar rendering it replaced.
    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.resize(300, 200)
    editor.show()
    QApplication.processEvents()
    background = editor.palette().color(QPalette.ColorRole.Base)  # the minimap's own fill color
    empty_count = _non_background_pixels(editor._minimap.grab().toImage(), background)

    editor.setPlainText("\n".join(f"some real code on line {i}" for i in range(20)))
    QApplication.processEvents()

    filled_count = _non_background_pixels(editor._minimap.grab().toImage(), background)
    assert filled_count > empty_count


def test_minimap_does_not_stretch_to_fill_a_short_document(qtbot) -> None:
    # PROMPT.md: "if the editor file is not long, the preview does not need to fill the full
    # screen vertically" -- the bottom of a tall minimap column should stay untouched background
    # when the document itself only has a few lines.
    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.resize(300, 400)
    editor.setPlainText("only\na few\nlines")
    editor.show()
    QApplication.processEvents()

    background = editor.palette().color(QPalette.ColorRole.Base)  # the minimap's own fill color
    image = editor._minimap.grab().toImage()
    bottom_row = image.height() - 1
    assert all(image.pixelColor(x, bottom_row) == background for x in range(image.width()))


def test_minimap_starts_from_the_editors_own_first_visible_block_and_tracks_scrolling(qtbot) -> None:
    # PROMPT.md: "it should scroll with the editor" -- rather than always squashing the whole
    # document to fit, the minimap's own first rendered line follows firstVisibleBlock().
    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.resize(300, 200)
    editor.setPlainText("\n".join(f"line {i}" for i in range(500)))
    editor.show()
    QApplication.processEvents()
    assert editor._minimap._first_line() == editor.firstVisibleBlock().blockNumber() == 0

    editor.verticalScrollBar().setValue(editor.verticalScrollBar().maximum())
    QApplication.processEvents()

    assert editor._minimap._first_line() == editor.firstVisibleBlock().blockNumber() > 0


def test_clicking_the_minimap_scrolls_the_editor(qtbot) -> None:
    from PyQt6.QtCore import QEvent, QPointF
    from PyQt6.QtGui import QMouseEvent

    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.resize(300, 200)
    editor.setPlainText("\n".join(f"line {i}" for i in range(500)))
    editor.show()
    QApplication.processEvents()
    before = editor.verticalScrollBar().value()

    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(2, editor._minimap.height() - 1),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    editor._minimap.mousePressEvent(press)

    assert editor.verticalScrollBar().value() > before


def test_dragging_the_minimap_scrolls_the_editor_further(qtbot) -> None:
    from PyQt6.QtCore import QEvent, QPointF
    from PyQt6.QtGui import QMouseEvent

    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.resize(300, 200)
    editor.setPlainText("\n".join(f"line {i}" for i in range(500)))
    editor.show()
    QApplication.processEvents()

    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(2, 0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    editor._minimap.mousePressEvent(press)
    after_press = editor.verticalScrollBar().value()

    move = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(2, 60),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    editor._minimap.mouseMoveEvent(move)

    assert editor.verticalScrollBar().value() > after_press

    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(2, 60),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    editor._minimap.mouseReleaseEvent(release)
    assert editor._minimap._drag_anchor is None


# -- +10% font for the 3 settings json files (PROMPT.md: "please increase the font size of the 3
# setting json files by 10%") ---------------------------------------------------------------------


@pytest.mark.parametrize("name", ["settings.json", "script_settings.json", "strings.json"])
def test_opening_a_settings_json_file_enlarges_its_own_font(qtbot, tmp_path, name: str) -> None:
    path = tmp_path / name
    editor = TextEditorWidget(path=path)
    qtbot.addWidget(editor)

    app_size = QApplication.instance().font().pointSizeF()
    assert editor.font().pointSizeF() == pytest.approx(app_size * 1.1)


def test_opening_an_unrelated_json_file_does_not_enlarge_its_font(qtbot, tmp_path) -> None:
    path = tmp_path / "output.txt"
    editor = TextEditorWidget(path=path)
    qtbot.addWidget(editor)

    app_size = QApplication.instance().font().pointSizeF()
    assert editor.font().pointSizeF() == pytest.approx(app_size)


def test_an_untitled_tab_with_no_path_is_not_enlarged(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)

    app_size = QApplication.instance().font().pointSizeF()
    assert editor.font().pointSizeF() == pytest.approx(app_size)


def test_save_as_onto_a_settings_json_name_enlarges_the_font(qtbot, tmp_path) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)

    editor.set_path(tmp_path / "settings.json")

    app_size = QApplication.instance().font().pointSizeF()
    assert editor.font().pointSizeF() == pytest.approx(app_size * 1.1)


def test_save_as_off_a_settings_json_name_shrinks_the_font_back(qtbot, tmp_path) -> None:
    editor = TextEditorWidget(path=tmp_path / "settings.json")
    qtbot.addWidget(editor)

    editor.set_path(tmp_path / "renamed.txt")

    app_size = QApplication.instance().font().pointSizeF()
    assert editor.font().pointSizeF() == pytest.approx(app_size)


def test_refresh_font_scale_tracks_a_later_app_font_change(qtbot, tmp_path) -> None:
    from PyQt6.QtGui import QFont

    editor = TextEditorWidget(path=tmp_path / "strings.json")
    qtbot.addWidget(editor)
    app = QApplication.instance()
    original = QFont(app.font())
    try:
        bigger = QFont(original)
        bigger.setPointSizeF(original.pointSizeF() * 2)
        app.setFont(bigger)

        editor.refresh_font_scale()

        assert editor.font().pointSizeF() == pytest.approx(bigger.pointSizeF() * 1.1)
    finally:
        app.setFont(original)


# -- Tab key indentation (PROMPT.md: Quick Access Bar work -- "Indent using spaces") -------------


def test_tab_inserts_spaces_when_the_indent_style_is_spaces(qtbot) -> None:
    indent_state.set_indent(indent_settings.STYLE_SPACES, 3)
    editor = TextEditorWidget()
    qtbot.addWidget(editor)

    qtbot.keyClick(editor, Qt.Key.Key_Tab)

    assert editor.toPlainText() == "   "


def test_tab_inserts_a_literal_tab_when_the_indent_style_is_tabs(qtbot) -> None:
    indent_state.set_indent(indent_settings.STYLE_TABS, 4)
    editor = TextEditorWidget()
    qtbot.addWidget(editor)

    qtbot.keyClick(editor, Qt.Key.Key_Tab)

    assert editor.toPlainText() == "\t"


# -- "Go to Line" highlight (PROMPT.md: "when going to line number, the editor should highlight
# the selected line (in both the main window and in the side preview)") ------------------------


def test_highlight_line_shows_a_full_width_extra_selection_on_that_block(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.setPlainText("a\nb\nc\nd")

    editor.highlight_line(2)

    selections = editor.extraSelections()
    assert len(selections) == 1
    assert selections[0].cursor.blockNumber() == 2
    assert selections[0].format.property(QTextFormat.Property.FullWidthSelection) is True


def test_highlight_line_also_marks_the_minimap(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.setPlainText("a\nb\nc\nd")

    editor.highlight_line(2)

    assert editor._minimap.highlight_line == 2


def test_highlight_line_persists_while_the_cursor_stays_on_that_line(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.setPlainText("a\nb\nc\nd")

    editor.highlight_line(2)
    cursor = editor.textCursor()
    block = editor.document().findBlockByNumber(2)
    cursor.setPosition(block.position() + 1)  # still line 2, just a different column
    editor.setTextCursor(cursor)

    assert len(editor.extraSelections()) == 1
    assert editor._minimap.highlight_line == 2


def test_highlight_line_clears_once_the_cursor_moves_to_a_different_line(qtbot) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.setPlainText("a\nb\nc\nd")

    editor.highlight_line(2)
    cursor = editor.textCursor()
    cursor.setPosition(editor.document().findBlockByNumber(3).position())
    editor.setTextCursor(cursor)

    assert editor.extraSelections() == []
    assert editor._minimap.highlight_line is None


def test_highlight_line_and_schema_error_underlines_coexist(qtbot, tmp_path) -> None:
    path = tmp_path / "settings.json"
    editor = TextEditorWidget(path=path)
    qtbot.addWidget(editor)
    editor.setPlainText('{"meta": {"category": "not_a_real_category"}}')
    assert len(editor.extraSelections()) == 1  # the error underline, before any goto-highlight

    editor.highlight_line(0)

    assert len(editor.extraSelections()) == 2
