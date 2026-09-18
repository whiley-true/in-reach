import pytest

from in_reach.ide.diff_view import DiffViewWidget, _align


def test_identical_lines_are_all_equal_with_no_padding() -> None:
    left, left_kinds, left_linenos, right, right_kinds, right_linenos = _align(["a", "b", "c"], ["a", "b", "c"])

    assert left == right == ["a", "b", "c"]
    assert left_kinds == right_kinds == ["equal", "equal", "equal"]
    assert left_linenos == right_linenos == [1, 2, 3]


def test_a_pure_addition_pads_the_left_side_with_blanks() -> None:
    left, left_kinds, left_linenos, right, right_kinds, right_linenos = _align(["a", "b"], ["a", "b", "c"])

    assert left == ["a", "b", ""]
    assert left_kinds == ["equal", "equal", "blank"]
    assert left_linenos == [1, 2, None]
    assert right == ["a", "b", "c"]
    assert right_kinds == ["equal", "equal", "added"]
    assert right_linenos == [1, 2, 3]


def test_a_pure_deletion_pads_the_right_side_with_blanks() -> None:
    left, left_kinds, left_linenos, right, right_kinds, right_linenos = _align(["a", "b", "c"], ["a", "b"])

    assert left == ["a", "b", "c"]
    assert left_kinds == ["equal", "equal", "removed"]
    assert left_linenos == [1, 2, 3]
    assert right == ["a", "b", ""]
    assert right_kinds == ["equal", "equal", "blank"]
    assert right_linenos == [1, 2, None]


def test_a_replace_block_of_equal_size_has_no_padding() -> None:
    left, left_kinds, left_linenos, right, right_kinds, right_linenos = _align(["old1", "old2"], ["new1", "new2"])

    assert left == ["old1", "old2"]
    assert left_kinds == ["removed", "removed"]
    assert left_linenos == [1, 2]
    assert right == ["new1", "new2"]
    assert right_kinds == ["added", "added"]
    assert right_linenos == [1, 2]


def test_a_replace_block_with_more_new_lines_pads_the_old_side() -> None:
    left, left_kinds, left_linenos, right, right_kinds, right_linenos = _align(["old1"], ["new1", "new2", "new3"])

    assert left == ["old1", "", ""]
    assert left_kinds == ["removed", "blank", "blank"]
    assert left_linenos == [1, None, None]
    assert right == ["new1", "new2", "new3"]
    assert right_kinds == ["added", "added", "added"]
    assert right_linenos == [1, 2, 3]


def test_a_replace_block_with_more_old_lines_pads_the_new_side() -> None:
    left, left_kinds, left_linenos, right, right_kinds, right_linenos = _align(["old1", "old2", "old3"], ["new1"])

    assert left == ["old1", "old2", "old3"]
    assert left_kinds == ["removed", "removed", "removed"]
    assert left_linenos == [1, 2, 3]
    assert right == ["new1", "", ""]
    assert right_kinds == ["added", "blank", "blank"]
    assert right_linenos == [1, None, None]


def test_both_sides_empty() -> None:
    left, left_kinds, left_linenos, right, right_kinds, right_linenos = _align([], [])

    assert left == right == []
    assert left_kinds == right_kinds == []
    assert left_linenos == right_linenos == []


def test_a_change_in_the_middle_keeps_the_surrounding_equal_lines_aligned() -> None:
    left, left_kinds, left_linenos, right, right_kinds, right_linenos = _align(
        ["header", "old_body", "footer"], ["header", "new_body1", "new_body2", "footer"]
    )

    assert left == ["header", "old_body", "", "footer"]
    assert left_kinds == ["equal", "removed", "blank", "equal"]
    assert left_linenos == [1, 2, None, 3]
    assert right == ["header", "new_body1", "new_body2", "footer"]
    assert right_kinds == ["equal", "added", "added", "equal"]
    assert right_linenos == [1, 2, 3, 4]


@pytest.mark.parametrize("old,new", [([], ["only", "new"]), (["only", "old"], [])])
def test_one_side_entirely_empty(old, new) -> None:
    left, left_kinds, left_linenos, right, right_kinds, right_linenos = _align(old, new)

    assert len(left) == len(left_kinds) == len(left_linenos) == len(right) == len(right_kinds) == len(right_linenos)
    assert len(left) == max(len(old), len(new))


# -- DiffViewWidget -------------------------------------------------------------------------------


def test_widget_shows_old_and_new_text_on_each_side(qtbot) -> None:
    widget = DiffViewWidget(rel_path="Notes.txt", old_text="line1\nline2\n", new_text="line1\nCHANGED\n")
    qtbot.addWidget(widget)

    assert widget.old_pane.toPlainText() == "line1\nline2"
    assert widget.new_pane.toPlainText() == "line1\nCHANGED"


def test_widget_treats_none_as_an_empty_side(qtbot) -> None:
    widget = DiffViewWidget(rel_path="new_file.txt", old_text=None, new_text="brand new\n")
    qtbot.addWidget(widget)

    assert widget.old_pane.toPlainText() == ""
    assert widget.new_pane.toPlainText() == "brand new"


def test_widget_panes_are_read_only(qtbot) -> None:
    widget = DiffViewWidget(rel_path="Notes.txt", old_text="a\n", new_text="b\n")
    qtbot.addWidget(widget)

    assert widget.old_pane.isReadOnly() is True
    assert widget.new_pane.isReadOnly() is True


def test_widget_highlights_changed_lines(qtbot) -> None:
    widget = DiffViewWidget(rel_path="Notes.txt", old_text="a\nb\n", new_text="a\nCHANGED\n")
    qtbot.addWidget(widget)

    assert len(widget.old_pane.extraSelections()) >= 1
    assert len(widget.new_pane.extraSelections()) >= 1


def test_widget_has_no_highlights_when_nothing_changed(qtbot) -> None:
    widget = DiffViewWidget(rel_path="Notes.txt", old_text="a\nb\n", new_text="a\nb\n")
    qtbot.addWidget(widget)

    assert widget.old_pane.extraSelections() == []
    assert widget.new_pane.extraSelections() == []


def test_set_diff_refreshes_content_in_place(qtbot) -> None:
    widget = DiffViewWidget(rel_path="Notes.txt", old_text="a\n", new_text="b\n")
    qtbot.addWidget(widget)

    widget.set_diff("x\n", "y\n")

    assert widget.old_pane.toPlainText() == "x"
    assert widget.new_pane.toPlainText() == "y"


def test_scrolling_one_pane_syncs_the_other(qtbot) -> None:
    long_old = "\n".join(f"line{i}" for i in range(200))
    long_new = "\n".join(f"line{i}" for i in range(200))
    widget = DiffViewWidget(rel_path="Notes.txt", old_text=long_old, new_text=long_new)
    qtbot.addWidget(widget)
    widget.resize(400, 100)
    widget.show()

    widget.old_pane.verticalScrollBar().setValue(50)

    assert widget.new_pane.verticalScrollBar().value() == 50


# -- line numbers + JSON syntax highlighting (PROMPT.md, a later pass: "where we have the changes
# view - this should maintain the text colouring of the theme, and also have line numbers in the
# separate views and still have the text preview on the left") -----------------------------------


def test_pane_gutter_shows_the_real_line_number_for_a_kept_line(qtbot) -> None:
    widget = DiffViewWidget(rel_path="Notes.txt", old_text="a\nb\nc\n", new_text="a\nCHANGED\nc\n")
    qtbot.addWidget(widget)

    assert widget.old_pane._linenos == [1, 2, 3]
    assert widget.new_pane._linenos == [1, 2, 3]


def test_pane_gutter_is_blank_for_an_alignment_filler_row(qtbot) -> None:
    widget = DiffViewWidget(rel_path="Notes.txt", old_text="a\n", new_text="a\nb\nc\n")
    qtbot.addWidget(widget)

    assert widget.old_pane._linenos == [1, None, None]
    assert widget.new_pane._linenos == [1, 2, 3]


def test_json_file_gets_syntax_highlighting_on_both_panes(qtbot) -> None:
    widget = DiffViewWidget(rel_path="settings/settings.json", old_text='{"a": 1}', new_text='{"a": 2}')
    qtbot.addWidget(widget)

    assert widget.old_pane._highlighter is not None
    assert widget.new_pane._highlighter is not None


def test_non_json_file_gets_no_syntax_highlighting(qtbot) -> None:
    widget = DiffViewWidget(rel_path="script/output.txt", old_text="a", new_text="b")
    qtbot.addWidget(widget)

    assert widget.old_pane._highlighter is None
    assert widget.new_pane._highlighter is None


def test_gutter_width_grows_with_more_lines(qtbot) -> None:
    widget = DiffViewWidget(rel_path="Notes.txt", old_text="a\n" * 5, new_text="a\n" * 5)
    qtbot.addWidget(widget)
    small_width = widget.old_pane.gutter_width()

    widget.set_diff("a\n" * 500, "a\n" * 500)

    assert widget.old_pane.gutter_width() > small_width
