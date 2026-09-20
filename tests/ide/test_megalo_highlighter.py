from pathlib import Path

import pytest
from PyQt6.QtGui import QColor, QTextDocument

from in_reach.ide.editor import TextEditorWidget, is_megalo_path
from in_reach.ide.megalo_highlighter import _DARK, _LIGHT, _NAMES, MegaloSyntaxHighlighter

_COLORS = dict(zip(_NAMES, _LIGHT))


def _highlight(text: str, *, base_color: str = "#ffffff") -> list[tuple[str, str]]:
    """``(text, colour name)`` of each coloured range on the first line of ``text``."""
    doc = QTextDocument()
    doc.setPlainText(text)
    highlighter = MegaloSyntaxHighlighter(doc, base_color=QColor(base_color))
    highlighter.rehighlight()
    palette = dict(zip(_DARK if QColor(base_color).lightness() < 128 else _LIGHT, _NAMES))
    line = text.split("\n")[0]
    ranges = doc.findBlockByNumber(0).layout().formats()
    return [(line[r.start:r.start + r.length], palette[r.format.foreground().color().name()]) for r in ranges]


def test_keywords_and_roots_are_coloured_apart() -> None:
    found = _highlight("if current_player.number[0] == 1 then")

    assert ("if", "keyword") in found and ("then", "keyword") in found
    assert ("current_player", "root") in found
    assert ("number", "keyword") not in found  # a member name is plain text


def test_a_word_that_merely_contains_a_keyword_is_not_one() -> None:
    assert _highlight("endgame = doing") == []


def test_numbers_and_percentages_are_numbers() -> None:
    found = _highlight("x = -100% + 42")

    assert ("-100%", "number") in found and ("42", "number") in found


def test_a_digit_inside_a_name_is_not_a_number() -> None:
    assert _highlight("player2 = t1") == []


def test_a_string_is_one_range_and_its_contents_are_not_recoloured() -> None:
    found = _highlight('game.show_message_to(everyone, none, "if 5 then end")')

    assert ('"if 5 then end"', "string") in found
    assert not any(colour in ("keyword", "number") and text in ("if", "5", "then", "end") for text, colour in found)


def test_a_comment_marker_inside_a_string_is_not_a_comment() -> None:
    found = _highlight('x = "a -- b" -- real')

    assert ('"a -- b"', "string") in found and ("-- real", "comment") in found


def test_a_plain_comment_is_one_comment_range_with_nothing_inside_recoloured() -> None:
    assert _highlight("-- if this then that 5") == [("-- if this then that 5", "comment")]


def test_an_annotation_is_coloured_as_metadata_not_as_a_comment() -> None:
    assert _highlight("-- @number g_phase priority=low") == [("-- @number g_phase priority=low", "annotation")]


def test_profile_directives_are_coloured_apart_from_annotations() -> None:
    for line in ("-- @if DEV", "-- @else", "-- @end"):
        assert _highlight(line) == [(line, "directive")]


def test_at_doc_is_an_annotation_too() -> None:
    assert _highlight("-- @doc ends the game") == [("-- @doc ends the game", "annotation")]


def test_placeholders_are_coloured_in_code_and_in_annotation_arguments() -> None:
    assert ("${SCORE_TO_WIN}", "placeholder") in _highlight("if x == ${SCORE_TO_WIN} then")
    assert ("${interval}", "placeholder") in _highlight("-- @ptimer p_t default=${interval}")


def test_a_placeholder_inside_a_plain_comment_is_left_as_comment() -> None:
    assert _highlight("-- costs ${SCORE}") == [("-- costs ${SCORE}", "comment")]


def test_code_before_a_trailing_comment_is_coloured_too() -> None:
    found = _highlight("end -- done")

    assert ("end", "keyword") in found and ("-- done", "comment") in found


def test_an_unterminated_string_colours_to_the_end_of_the_line() -> None:
    assert ('"never closed', "string") in _highlight('x = "never closed')


def test_the_dark_palette_is_used_on_a_dark_background() -> None:
    doc = QTextDocument()
    doc.setPlainText("if")
    MegaloSyntaxHighlighter(doc, base_color=QColor("#1e1e1e")).rehighlight()

    [format_range] = doc.findBlockByNumber(0).layout().formats()

    assert format_range.format.foreground().color().name() == _DARK[0]


def test_directives_are_bold() -> None:
    doc = QTextDocument()
    doc.setPlainText("-- @if DEV")
    MegaloSyntaxHighlighter(doc, base_color=QColor("#ffffff")).rehighlight()

    [format_range] = doc.findBlockByNumber(0).layout().formats()

    assert format_range.format.fontWeight() > 400


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        ("script/blocks/setup.mgl", True), ("script/modules/m/m.mgl", True), ("script/output.txt", True),
        ("build/Compiled.txt", True), ("notes/output.txt", False), ("settings/settings.json", False),
        ("script/env/dev.env", False), ("readme.md", False),
    ],
)
def test_which_files_are_megalo(relative: str, expected: bool) -> None:
    assert is_megalo_path(Path("proj") / relative) is expected
    assert is_megalo_path(None) is False


def test_the_editor_highlights_a_mgl_file_and_not_a_plain_txt(qtbot, tmp_path: Path) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)

    editor.set_path(tmp_path / "blocks" / "setup.mgl")
    assert isinstance(editor._edit._highlighter, MegaloSyntaxHighlighter)

    editor.set_path(tmp_path / "notes.txt")
    assert editor._edit._highlighter is None

    editor.set_path(tmp_path / "script" / "output.txt")
    assert isinstance(editor._edit._highlighter, MegaloSyntaxHighlighter)


def test_saving_a_untitled_tab_as_mgl_starts_highlighting_it(qtbot, tmp_path: Path) -> None:
    editor = TextEditorWidget()
    qtbot.addWidget(editor)
    editor.set_path(None)
    assert editor._edit._highlighter is None

    editor.set_path(tmp_path / "x.mgl")

    assert editor._edit._highlighter is not None
    editor.set_path(tmp_path / "x.json")  # switching type swaps the highlighter rather than stacking two
    assert not isinstance(editor._edit._highlighter, MegaloSyntaxHighlighter)
