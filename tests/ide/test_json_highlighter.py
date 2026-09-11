from PyQt6.QtGui import QColor, QTextDocument

from in_reach.ide.json_highlighter import JsonSyntaxHighlighter, _DARK_COLORS, _LIGHT_COLORS


def _highlight(text: str, *, base_color: str = "#ffffff") -> list[tuple[int, int, str]]:
    doc = QTextDocument()
    doc.setPlainText(text)
    highlighter = JsonSyntaxHighlighter(doc, base_color=QColor(base_color))
    highlighter.rehighlight()
    block = doc.findBlockByNumber(0)
    return [
        (r.start, r.length, r.format.foreground().color().name())
        for r in block.layout().formats()
    ]


def test_a_key_is_colored_distinctly_from_a_string_value() -> None:
    ranges = _highlight('{"key": "value"}')
    key_color, string_color, _, _ = _LIGHT_COLORS

    assert (1, 5, key_color) in ranges
    assert (8, 7, string_color) in ranges
    assert key_color != string_color


def test_digits_inside_a_string_value_are_not_recolored_as_a_number() -> None:
    ranges = _highlight('{"key": "Score 100 points"}')
    _, string_color, number_color, _ = _LIGHT_COLORS

    # The whole string, digits included, is one uniform string-colored range -- no separate
    # number-colored sub-range for "100".
    assert (8, 18, string_color) in ranges
    assert not any(color == number_color for _start, _length, color in ranges)


def test_a_real_number_outside_any_string_is_colored_as_a_number() -> None:
    ranges = _highlight('{"n": 42}')
    _, _, number_color, _ = _LIGHT_COLORS

    assert (6, 2, number_color) in ranges


def test_true_false_and_null_are_colored_as_literals() -> None:
    _, _, _, literal_color = _LIGHT_COLORS

    for text, expected in [
        ('{"a": true}', (6, 4)),
        ('{"a": false}', (6, 5)),
        ('{"a": null}', (6, 4)),
    ]:
        ranges = _highlight(text)
        start, length = expected
        assert (start, length, literal_color) in ranges


def test_true_inside_a_string_is_not_colored_as_a_literal() -> None:
    ranges = _highlight('{"a": "this is true actually"}')
    _, string_color, _, literal_color = _LIGHT_COLORS

    assert not any(color == literal_color for _start, _length, color in ranges)
    assert (6, 23, string_color) in ranges


def test_a_light_base_color_uses_the_light_palette() -> None:
    ranges = _highlight('{"key": 1}', base_color="#ffffff")
    key_color, *_ = _LIGHT_COLORS

    assert any(color == key_color for _start, _length, color in ranges)


def test_a_dark_base_color_uses_the_dark_palette() -> None:
    ranges = _highlight('{"key": 1}', base_color="#252526")
    key_color, *_ = _DARK_COLORS

    assert any(color == key_color for _start, _length, color in ranges)


def test_light_palette_colors_are_dark_enough_to_read_against_a_white_background() -> None:
    # Regression guard: the light palette started as VS Code's own Light+ colors, which read as
    # too pale against this app's white editor background -- every token color should sit well
    # below a mid-grey lightness, not just "technically not white".
    for hex_color in _LIGHT_COLORS:
        color = QColor(hex_color)
        luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
        assert luminance < 100
