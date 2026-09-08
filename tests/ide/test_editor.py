from PyQt6.QtWidgets import QApplication

from in_reach.ide.editor import TextEditorWidget


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
    assert geometry.height() == editor.contentsRect().height()


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
