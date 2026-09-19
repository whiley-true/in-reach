from in_reach.ide.unified_diff_view import UnifiedDiffViewWidget, UnifiedLine, unify


def test_identical_lines_are_all_equal_with_both_linenos() -> None:
    lines = unify(["a", "b"], ["a", "b"])

    assert lines == [
        UnifiedLine(1, 1, "a", "equal"),
        UnifiedLine(2, 2, "b", "equal"),
    ]


def test_a_pure_addition_has_no_old_lineno() -> None:
    lines = unify(["a"], ["a", "b"])

    assert lines == [
        UnifiedLine(1, 1, "a", "equal"),
        UnifiedLine(None, 2, "b", "added"),
    ]


def test_a_pure_deletion_has_no_new_lineno() -> None:
    lines = unify(["a", "b"], ["a"])

    assert lines == [
        UnifiedLine(1, 1, "a", "equal"),
        UnifiedLine(2, None, "b", "removed"),
    ]


def test_a_replace_block_lists_removed_lines_before_added_ones() -> None:
    lines = unify(["old1", "old2"], ["new1"])

    assert lines == [
        UnifiedLine(1, None, "old1", "removed"),
        UnifiedLine(2, None, "old2", "removed"),
        UnifiedLine(None, 1, "new1", "added"),
    ]


def test_both_sides_empty() -> None:
    assert unify([], []) == []


# -- UnifiedDiffViewWidget ------------------------------------------------------------------------


def test_widget_shows_a_single_pane_with_markers(qtbot) -> None:
    widget = UnifiedDiffViewWidget(rel_path="Notes.txt", sha="abcd1234", old_text="a\nb\n", new_text="a\nc\n")
    qtbot.addWidget(widget)

    text = widget.pane.toPlainText()
    assert "  a" in text
    assert "- b" in text
    assert "+ c" in text


def test_widget_pane_is_read_only(qtbot) -> None:
    widget = UnifiedDiffViewWidget(rel_path="Notes.txt", sha="abcd1234", old_text="a\n", new_text="b\n")
    qtbot.addWidget(widget)

    assert widget.pane.isReadOnly() is True


def test_widget_highlights_changed_lines(qtbot) -> None:
    widget = UnifiedDiffViewWidget(rel_path="Notes.txt", sha="abcd1234", old_text="a\nb\n", new_text="a\nc\n")
    qtbot.addWidget(widget)

    assert len(widget.pane.extraSelections()) >= 2


def test_widget_treats_none_as_empty(qtbot) -> None:
    widget = UnifiedDiffViewWidget(rel_path="new.txt", sha="abcd1234", old_text=None, new_text="new\n")
    qtbot.addWidget(widget)

    assert "+ new" in widget.pane.toPlainText()


def test_json_file_gets_syntax_highlighting(qtbot) -> None:
    widget = UnifiedDiffViewWidget(rel_path="settings.json", sha="abcd1234", old_text='{"a": 1}', new_text='{"a": 2}')
    qtbot.addWidget(widget)

    assert widget.pane._highlighter is not None


def test_non_json_file_gets_no_syntax_highlighting(qtbot) -> None:
    widget = UnifiedDiffViewWidget(rel_path="output.txt", sha="abcd1234", old_text="a", new_text="b")
    qtbot.addWidget(widget)

    assert widget.pane._highlighter is None


def test_set_diff_refreshes_content_in_place(qtbot) -> None:
    widget = UnifiedDiffViewWidget(rel_path="Notes.txt", sha="abcd1234", old_text="a\n", new_text="b\n")
    qtbot.addWidget(widget)

    widget.set_diff("x\n", "y\n")

    text = widget.pane.toPlainText()
    assert "- x" in text
    assert "+ y" in text
