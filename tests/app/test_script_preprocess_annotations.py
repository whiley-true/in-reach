"""``${NAME}`` in an annotation's arguments is filled in by the preprocessor; everywhere else in a comment it is not.

A module's parameter reaches its storage through an annotation (``-- @ptimer p_t default=${interval}``), and
``TO_IMPLEMENT`` §13's example does exactly that -- but the preprocessor has always left comments alone, and an
annotation is a comment. So annotation arguments are substituted, while the ``-- @`` prefix, a note after a
second ``--``, an ``@doc`` line's prose, and every ordinary comment are not (a ``${...}`` mentioned in prose
must neither be replaced nor be reported as undefined).
"""
import pytest

from in_reach.app.script_preprocess import PreprocessError, Env, preprocess

_PROFILE = Env("dev", frozenset({"DEV"}), {"N": "6", "LABEL": '"hill"', "RATE": "-100%"})


def test_an_annotations_arguments_are_substituted() -> None:
    assert preprocess("-- @timer g_t default=${N}\n", _PROFILE) == "-- @timer g_t default=6\n"


def test_several_placeholders_and_kinds_of_annotation_are_substituted() -> None:
    text = "-- @label L_a = ${LABEL}\n-- @trait t { speed = ${N}, rate = ${RATE} }\n   -- @gate g_x == ${N}\n"

    assert preprocess(text, _PROFILE) == '-- @label L_a = "hill"\n-- @trait t { speed = 6, rate = -100% }\n   -- @gate g_x == 6\n'


def test_a_note_after_a_second_dash_pair_is_left_alone() -> None:
    text = "-- @timer g_t default=${N}   -- see ${NOT_DEFINED} for why\n"

    assert preprocess(text, _PROFILE) == "-- @timer g_t default=6   -- see ${NOT_DEFINED} for why\n"


def test_a_doc_annotations_prose_is_left_alone() -> None:
    text = "-- @doc waits ${N} seconds, or ${WHATEVER} the env says\n"

    assert preprocess(text, _PROFILE) == text


def test_an_ordinary_comment_is_left_alone() -> None:
    text = "-- plain comment ${NOT_DEFINED}\nx = ${N} -- trailing ${ALSO_NOT}\n"

    assert preprocess(text, _PROFILE) == "-- plain comment ${NOT_DEFINED}\nx = 6 -- trailing ${ALSO_NOT}\n"


def test_a_dash_pair_inside_a_string_argument_does_not_start_a_note() -> None:
    text = '-- @label L_a = "a -- ${N}"\n'

    # The `--` is inside a string, so what follows is still an argument and is still substituted.
    assert preprocess(text, _PROFILE) == '-- @label L_a = "a -- 6"\n'


def test_an_undefined_constant_in_an_annotation_is_an_error_at_its_column() -> None:
    text = "-- @timer g_t default=${MISSING}\n"

    with pytest.raises(PreprocessError) as raised:
        preprocess(text, _PROFILE)

    assert (raised.value.line, raised.value.col) == (1, text.index("${"))
    assert "MISSING" in raised.value.message


def test_line_numbers_and_the_line_count_never_change() -> None:
    text = "-- @timer a default=${N}\nx = 1\n-- @timer b default=${N}\n"

    result = preprocess(text, _PROFILE)

    assert result.count("\n") == text.count("\n") == 3


def test_an_annotation_inside_a_removed_if_block_is_dropped_and_not_checked() -> None:
    text = "-- @if RELEASE\n-- @timer g_t default=${NOT_DEFINED_ANYWHERE}\n-- @end\n"

    # No error for the undefined constant, and the inner line is blanked (the directive lines stay, as always).
    assert preprocess(text, _PROFILE) == "-- @if RELEASE\n\n-- @end\n"


def test_a_directive_is_still_a_directive_not_an_annotation() -> None:
    text = "-- @if DEV\nx = ${N}\n-- @else\nx = 0\n-- @end\n"

    # Directive lines stay visible whichever branch is kept; only the dropped branch's code is blanked.
    assert preprocess(text, _PROFILE) == "-- @if DEV\nx = 6\n-- @else\n\n-- @end\n"


def test_text_using_neither_feature_still_comes_back_unchanged() -> None:
    text = "-- @number g_x priority=low\n-- @doc nothing to substitute\nx = 1\n"

    assert preprocess(text, None) == text
