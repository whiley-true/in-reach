from in_reach.ide.code_folding import compute_fold_ranges


def test_a_single_multiline_object_is_foldable() -> None:
    text = '{\n  "a": 1\n}'
    assert compute_fold_ranges(text) == {0: 2}


def test_an_empty_object_on_one_line_is_not_foldable() -> None:
    assert compute_fold_ranges('{"a": {}}') == {}


def test_a_nested_multiline_array_and_object_both_fold() -> None:
    text = '{\n  "items": [\n    1,\n    2\n  ]\n}'
    assert compute_fold_ranges(text) == {0: 5, 1: 4}


def test_a_line_with_two_openers_maps_to_the_outermost_close() -> None:
    text = '{\n  "a": {"b": [\n    1\n  ]}\n}'
    # Line 1 opens both the "b" object and the "b" array on the same line -- folding line 1
    # should span down to line 3, where the outer object closes (not line 3's own "]" alone,
    # since both brackets close on the same line there anyway).
    assert compute_fold_ranges(text) == {0: 4, 1: 3}


def test_brackets_inside_a_string_value_are_ignored() -> None:
    text = '{\n  "note": "a { b [ c"\n}'
    assert compute_fold_ranges(text) == {0: 2}


def test_an_escaped_quote_inside_a_string_does_not_end_it_early() -> None:
    text = '{\n  "note": "say \\"hi\\" { not a fold"\n}'
    assert compute_fold_ranges(text) == {0: 2}


def test_unmatched_closing_bracket_is_ignored_rather_than_raising() -> None:
    text = '}\n{\n  "a": 1\n}'
    assert compute_fold_ranges(text) == {1: 3}


def test_unclosed_opening_bracket_is_simply_not_foldable() -> None:
    text = '{\n  "a": {\n  "b": 1'
    assert compute_fold_ranges(text) == {}


def test_empty_text_has_no_folds() -> None:
    assert compute_fold_ranges("") == {}


def test_a_single_line_document_has_no_folds() -> None:
    assert compute_fold_ranges('{"a": 1, "b": [1, 2, 3]}') == {}
