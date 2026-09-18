import pytest

from in_reach.ide.diff_view import DiffViewWidget, _align


def test_identical_lines_are_all_equal_with_no_padding() -> None:
    left, left_kinds, right, right_kinds = _align(["a", "b", "c"], ["a", "b", "c"])

    assert left == right == ["a", "b", "c"]
    assert left_kinds == right_kinds == ["equal", "equal", "equal"]


def test_a_pure_addition_pads_the_left_side_with_blanks() -> None:
    left, left_kinds, right, right_kinds = _align(["a", "b"], ["a", "b", "c"])

    assert left == ["a", "b", ""]
    assert left_kinds == ["equal", "equal", "blank"]
    assert right == ["a", "b", "c"]
    assert right_kinds == ["equal", "equal", "added"]


def test_a_pure_deletion_pads_the_right_side_with_blanks() -> None:
    left, left_kinds, right, right_kinds = _align(["a", "b", "c"], ["a", "b"])

    assert left == ["a", "b", "c"]
    assert left_kinds == ["equal", "equal", "removed"]
    assert right == ["a", "b", ""]
    assert right_kinds == ["equal", "equal", "blank"]


def test_a_replace_block_of_equal_size_has_no_padding() -> None:
    left, left_kinds, right, right_kinds = _align(["old1", "old2"], ["new1", "new2"])

    assert left == ["old1", "old2"]
    assert left_kinds == ["removed", "removed"]
    assert right == ["new1", "new2"]
    assert right_kinds == ["added", "added"]


def test_a_replace_block_with_more_new_lines_pads_the_old_side() -> None:
    left, left_kinds, right, right_kinds = _align(["old1"], ["new1", "new2", "new3"])

    assert left == ["old1", "", ""]
    assert left_kinds == ["removed", "blank", "blank"]
    assert right == ["new1", "new2", "new3"]
    assert right_kinds == ["added", "added", "added"]


def test_a_replace_block_with_more_old_lines_pads_the_new_side() -> None:
    left, left_kinds, right, right_kinds = _align(["old1", "old2", "old3"], ["new1"])

    assert left == ["old1", "old2", "old3"]
    assert left_kinds == ["removed", "removed", "removed"]
    assert right == ["new1", "", ""]
    assert right_kinds == ["added", "blank", "blank"]


def test_both_sides_empty() -> None:
    left, left_kinds, right, right_kinds = _align([], [])

    assert left == right == []
    assert left_kinds == right_kinds == []


def test_a_change_in_the_middle_keeps_the_surrounding_equal_lines_aligned() -> None:
    left, left_kinds, right, right_kinds = _align(
        ["header", "old_body", "footer"], ["header", "new_body1", "new_body2", "footer"]
    )

    assert left == ["header", "old_body", "", "footer"]
    assert left_kinds == ["equal", "removed", "blank", "equal"]
    assert right == ["header", "new_body1", "new_body2", "footer"]
    assert right_kinds == ["equal", "added", "added", "equal"]


@pytest.mark.parametrize("old,new", [([], ["only", "new"]), (["only", "old"], [])])
def test_one_side_entirely_empty(old, new) -> None:
    left, left_kinds, right, right_kinds = _align(old, new)

    assert len(left) == len(left_kinds) == len(right) == len(right_kinds) == max(len(old), len(new))


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
