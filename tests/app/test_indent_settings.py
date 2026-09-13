from pathlib import Path

from in_reach.app import indent_settings


def test_get_indent_defaults_when_nothing_saved(tmp_path: Path) -> None:
    style, width = indent_settings.get_indent(tmp_path / ".env")

    assert style == indent_settings.DEFAULT_INDENT_STYLE
    assert width == indent_settings.DEFAULT_INDENT_WIDTH


def test_set_indent_round_trips(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"

    indent_settings.set_indent(env_path, indent_settings.STYLE_TABS, 2)

    assert indent_settings.get_indent(env_path) == (indent_settings.STYLE_TABS, 2)


def test_set_indent_clamps_width(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"

    style, width = indent_settings.set_indent(env_path, indent_settings.STYLE_SPACES, 99)

    assert width == indent_settings.MAX_INDENT_WIDTH


def test_set_indent_falls_back_to_default_style_for_an_unknown_value(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"

    style, _width = indent_settings.set_indent(env_path, "nonsense", 4)

    assert style == indent_settings.DEFAULT_INDENT_STYLE


def test_get_indent_ignores_an_unparsable_saved_width(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(f"{indent_settings.INDENT_WIDTH_KEY}=not-a-number\n", encoding="utf-8")

    _style, width = indent_settings.get_indent(env_path)

    assert width == indent_settings.DEFAULT_INDENT_WIDTH


def test_convert_to_spaces_replaces_leading_tabs_only() -> None:
    text = "\tfoo\n\t\tbar\nno\tindent\there"

    result = indent_settings.convert_to_spaces(text, 2)

    assert result == "  foo\n    bar\nno\tindent\there"


def test_convert_to_tabs_replaces_full_leading_space_groups() -> None:
    text = "  foo\n    bar\n   baz"  # baz has a partial trailing group (3 spaces, width 2)

    result = indent_settings.convert_to_tabs(text, 2)

    assert result == "\tfoo\n\t\tbar\n\t baz"


def test_convert_indentation_round_trips() -> None:
    text = "\t\tfoo\n\tbar"

    spaces = indent_settings.convert_to_spaces(text, 4)
    back_to_tabs = indent_settings.convert_to_tabs(spaces, 4)

    assert back_to_tabs == text


def test_trim_trailing_whitespace_strips_spaces_and_tabs_but_not_content() -> None:
    text = "foo   \nbar\t\n  baz  \nkeep this"

    result = indent_settings.trim_trailing_whitespace(text)

    assert result == "foo\nbar\n  baz\nkeep this"


def test_detect_indent_picks_tabs_when_more_lines_start_with_a_tab() -> None:
    text = "\tfoo\n\tbar\n  baz"

    style, width = indent_settings.detect_indent(text, (indent_settings.STYLE_SPACES, 4))

    assert (style, width) == (indent_settings.STYLE_TABS, 4)  # width untouched -- can't detect it


def test_detect_indent_picks_spaces_and_its_gcd_width_when_more_lines_start_with_spaces() -> None:
    text = "def foo():\n    x = 1\n    if x:\n        return x"  # levels of 4 and 8 spaces

    style, width = indent_settings.detect_indent(text, (indent_settings.STYLE_TABS, 4))

    assert (style, width) == (indent_settings.STYLE_SPACES, 4)


def test_detect_indent_clamps_a_wide_gcd() -> None:
    text = "foo\n          bar"  # a single 10-space indent -- gcd is just that one number

    _style, width = indent_settings.detect_indent(text, (indent_settings.STYLE_SPACES, 4))

    assert width == indent_settings.MAX_INDENT_WIDTH


def test_detect_indent_returns_current_unchanged_with_no_indentation_at_all() -> None:
    text = "foo\nbar\nbaz"

    result = indent_settings.detect_indent(text, (indent_settings.STYLE_TABS, 7))

    assert result == (indent_settings.STYLE_TABS, 7)


def test_detect_indent_breaks_a_tie_toward_spaces() -> None:
    text = "\tfoo\n  bar"  # one tab-started line, one space-started line

    style, _width = indent_settings.detect_indent(text, (indent_settings.STYLE_TABS, 4))

    assert style == indent_settings.STYLE_SPACES
