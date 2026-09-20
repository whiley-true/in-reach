"""Coverage for :mod:`in_reach.app.script_preprocess` -- env profiles for a project's script.

The two properties the module promises beyond "it substitutes and strips", each pinned directly:
line numbers never shift (the compiler's messages are a script author's only feedback), and text that
uses neither feature comes back untouched (so every project written before this existed is unaffected).
"""
from pathlib import Path

import pytest

from in_reach.app import script_preprocess as sp
from in_reach.app.script_preprocess import PreprocessError, Profile, parse_profile, preprocess


def _profile(text: str = "", name: str = "dev") -> Profile:
    return parse_profile(name, text)


# -- values -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, kind",
    [
        ("5", "int"), ("-1", "int"), ("0", "int"), ("32767", "int"), ("-32768", "int"),
        ("-100%", "percent"), ("50%", "percent"),
        ("everyone", "name"), ("_x1", "name"),
        ('"hill"', "string"), ('"a \\" b"', "string"), ('""', "string"),
    ],
)
def test_value_kind_accepts_what_megalo_can_hold(value: str, kind: str) -> None:
    assert sp.value_kind(value) == kind


@pytest.mark.parametrize(
    "value", ["32768", "-32769", "1.5", "+5", "1 2", "a-b", "end)", "5%%", "%", '"open', "'single'", "a b", "${X}", ""]
)
def test_value_kind_rejects_anything_that_could_carry_code_or_isnt_a_value(value: str) -> None:
    assert sp.value_kind(value) is None


def test_an_out_of_range_number_is_reported_as_such_not_as_a_generic_bad_value() -> None:
    with pytest.raises(PreprocessError, match=r"outside Megalo's number range \(-32768 to 32767\)"):
        sp.check_value("SCORE", "40000")


def test_a_bad_value_names_what_is_allowed() -> None:
    with pytest.raises(PreprocessError, match="isn't a number, a percentage"):
        sp.check_value("X", "1 + 2")


# -- profiles -----------------------------------------------------------------------------------------


def test_a_profile_has_flags_and_constants() -> None:
    profile = parse_profile("dev", "# a comment\n\nFLAGS=DEV, VERBOSE_HUD\nSCORE=5\nHILL=\"hill\"\n")
    assert profile.name == "dev"
    assert profile.flags == {"DEV", "VERBOSE_HUD"}
    assert profile.constants == {"SCORE": "5", "HILL": '"hill"'}


def test_a_string_constant_keeps_its_quotes() -> None:
    assert parse_profile("p", 'LABEL="hill"').constants["LABEL"] == '"hill"'


def test_an_empty_profile_is_fine() -> None:
    profile = parse_profile("empty", "")
    assert profile.flags == frozenset() and profile.constants == {}


def test_flags_may_be_empty() -> None:
    assert parse_profile("release", "FLAGS=\n").flags == frozenset()


@pytest.mark.parametrize(
    "text, line, message",
    [
        ("A=1\nnot a pair\n", 2, "expected NAME=VALUE"),
        ("1BAD=1\n", 1, "isn't a valid name"),
        ("A=1\nA=2\n", 2, "A is defined twice"),
        ("A=\n", 1, "A has no value"),
        ("A=1 + 2\n", 1, "isn't a number"),
        ("A=99999\n", 1, "outside Megalo's number range"),
        ("FLAGS=OK,not ok\n", 1, "isn't a valid flag name"),
    ],
)
def test_a_malformed_profile_line_is_reported_at_its_own_line(text: str, line: int, message: str) -> None:
    path = Path("dev.env")
    with pytest.raises(PreprocessError, match=message) as excinfo:
        parse_profile("dev", text, path)
    assert excinfo.value.line == line and excinfo.value.path == path


# -- @if / @else / @end ---------------------------------------------------------------------------------


def test_a_block_is_kept_when_its_flag_is_set() -> None:
    assert preprocess("-- @if DEV\na\n-- @end\n", _profile("FLAGS=DEV")) == "-- @if DEV\na\n-- @end\n"


def test_a_block_is_dropped_when_its_flag_is_not_set() -> None:
    assert preprocess("-- @if DEV\na\n-- @end\nb\n", _profile("FLAGS=OTHER")) == "-- @if DEV\n\n-- @end\nb\n"


def test_a_negated_block_is_kept_exactly_when_the_flag_is_not_set() -> None:
    src = "-- @if !DEV\nrelease only\n-- @end\n"
    assert "release only" in preprocess(src, _profile("FLAGS="))
    assert "release only" not in preprocess(src, _profile("FLAGS=DEV"))


def test_else_takes_the_other_branch() -> None:
    src = "-- @if DEV\na\n-- @else\nb\n-- @end\n"
    on, off = preprocess(src, _profile("FLAGS=DEV")), preprocess(src, _profile("FLAGS="))
    assert (on.split("\n")[1], on.split("\n")[3]) == ("a", "")
    assert (off.split("\n")[1], off.split("\n")[3]) == ("", "b")


def test_blocks_nest_and_an_inner_one_cannot_outlive_its_outer() -> None:
    src = "-- @if A\n-- @if B\nboth\n-- @end\nonly a\n-- @end\n"
    assert preprocess(src, _profile("FLAGS=A,B")).split("\n")[2:5] == ["both", "-- @end", "only a"]
    assert "both" not in preprocess(src, _profile("FLAGS=A"))
    assert "only a" in preprocess(src, _profile("FLAGS=A"))
    none = preprocess(src, _profile("FLAGS=B"))  # B alone: the outer block is off, so the inner can't be on
    assert "both" not in none and "only a" not in none


def test_an_else_inside_a_dropped_block_does_not_switch_it_on() -> None:
    src = "-- @if A\n-- @if B\nx\n-- @else\ny\n-- @end\n-- @end\n"
    out = preprocess(src, _profile("FLAGS=B"))  # A is off, so neither x nor y
    assert "x" not in out and "y" not in out


def test_directives_stay_visible_when_their_own_block_is_active_even_if_a_branch_is_not() -> None:
    out = preprocess("-- @if DEV\na\n-- @else\nb\n-- @end\n", _profile("FLAGS=DEV"))
    assert out.split("\n") == ["-- @if DEV", "a", "-- @else", "", "-- @end", ""]


def test_directives_disappear_along_with_the_dropped_block_they_sit_in() -> None:
    out = preprocess("-- @if X\n-- @if DEV\na\n-- @end\n-- @end\nc\n", _profile("FLAGS=DEV"))
    assert out.split("\n") == ["-- @if X", "", "", "", "-- @end", "c", ""]


def test_a_dropped_block_is_never_scanned_for_constants() -> None:
    """So a dev-only block can use a constant only the dev profile defines."""
    assert preprocess("-- @if DEV\nx = ${DEV_ONLY}\n-- @end\n", _profile("FLAGS=")).split("\n")[1] == ""


def test_other_annotation_comments_are_left_alone() -> None:
    src = "-- @doc Runs once.\n-- @block SETUP\n-- @iffy\nx = 1\n"
    assert preprocess(src, _profile()) == src


def test_a_trailing_directive_is_just_a_comment() -> None:
    src = "x = 1 -- @if DEV\n"
    assert preprocess(src, _profile("FLAGS=")) == src


def test_a_directive_may_be_indented_and_spaced() -> None:
    assert preprocess("   --   @if   DEV  \na\n-- @end\n", _profile("FLAGS=")).split("\n")[1] == ""


@pytest.mark.parametrize(
    "src, message, line",
    [
        ("-- @if DEV\na\n", "never closed", 1),
        ("a\n-- @end\n", "'-- @end' without a matching '-- @if'", 2),
        ("a\n-- @else\n", "'-- @else' without a matching '-- @if'", 2),
        ("-- @if A\n-- @else\n-- @else\n-- @end\n", "a second '-- @else'", 3),
        ("-- @if\na\n-- @end\n", "needs one flag name", 1),
        ("-- @if A B\n-- @end\n", "needs one flag name", 1),
        ("-- @if !\n-- @end\n", "needs one flag name", 1),
        ("-- @if A\n-- @end now\n", "takes nothing after it", 2),
        ("-- @if A\n-- @else x\n-- @end\n", "takes nothing after it", 2),
    ],
)
def test_malformed_or_unbalanced_directives_are_errors_at_the_right_line(src: str, message: str, line: int) -> None:
    with pytest.raises(PreprocessError, match=message) as excinfo:
        preprocess(src, _profile("FLAGS=A"))
    assert excinfo.value.line == line


def test_an_unclosed_block_is_reported_at_the_innermost_open_if() -> None:
    with pytest.raises(PreprocessError) as excinfo:
        preprocess("-- @if A\n-- @if B\n", _profile("FLAGS=A,B"))
    assert excinfo.value.line == 2


# -- ${constants} -----------------------------------------------------------------------------------------


def test_a_constant_is_substituted() -> None:
    assert preprocess("x = ${SCORE}\n", _profile("SCORE=5")) == "x = 5\n"


def test_several_constants_in_one_line_and_repeated_ones() -> None:
    assert preprocess("${A} ${B} ${A}\n", _profile("A=1\nB=-100%")) == "1 -100% 1\n"


def test_a_string_constant_stands_in_for_a_string() -> None:
    assert preprocess("label ${HILL}\n", _profile('HILL="hill"')) == 'label "hill"\n'


def test_a_name_constant_may_go_inside_a_string_literal() -> None:
    assert preprocess('msg "score ${N}"\n', _profile("N=5")) == 'msg "score 5"\n'
    assert preprocess('msg "for ${WHO}"\n', _profile("WHO=everyone")) == 'msg "for everyone"\n'


@pytest.mark.parametrize("value", ["-100%", '"hill"'])
def test_a_percentage_or_quoted_string_cannot_go_inside_a_string_literal(value: str) -> None:
    with pytest.raises(PreprocessError, match="can't go inside a string literal"):
        preprocess('msg "${X}"\n', _profile(f"X={value}"))


def test_a_constant_is_left_alone_inside_a_comment() -> None:
    src = "x = 1 -- set ${SCORE} later\n"
    assert preprocess(src, _profile()) == src


def test_a_comment_marker_inside_a_string_does_not_hide_a_constant_after_it() -> None:
    assert preprocess('msg "a -- b" ${N}\n', _profile("N=3")) == 'msg "a -- b" 3\n'


def test_an_escaped_quote_does_not_end_the_string() -> None:
    assert preprocess('msg "say \\"hi\\" ${N}"\n', _profile("N=3")) == 'msg "say \\"hi\\" 3"\n'


def test_a_constant_the_profile_lacks_is_an_error_naming_it_and_the_profile() -> None:
    with pytest.raises(PreprocessError, match=r"'\$\{MISSING\}' isn't defined in the 'dev' profile") as excinfo:
        preprocess("a\nx = ${MISSING}\n", _profile("OTHER=1"))
    assert (excinfo.value.line, excinfo.value.col) == (2, 4)


def test_with_no_profile_a_constant_says_none_is_active() -> None:
    with pytest.raises(PreprocessError, match="no environment profile is active"):
        preprocess("x = ${A}\n")


@pytest.mark.parametrize("src", ["x = ${A\n", "x = ${}\n", "x = ${1BAD}\n", "x = ${a b}\n"])
def test_a_malformed_placeholder_is_an_error(src: str) -> None:
    with pytest.raises(PreprocessError):
        preprocess(src, _profile("A=1"))


def test_the_error_column_points_at_the_placeholder() -> None:
    with pytest.raises(PreprocessError) as excinfo:
        preprocess("abc ${NOPE} def\n", _profile())
    assert excinfo.value.col == 4


# -- the two promises ---------------------------------------------------------------------------------------


def test_text_using_neither_feature_comes_back_exactly_as_it_went_in() -> None:
    src = "declare global.number[0]\r\nif global.number[0] == 1 then\r\n   game.end_round()\r\nend\r\n-- plain comment\r\n"
    assert preprocess(src) == src
    assert preprocess(src, _profile("FLAGS=DEV\nX=1")) == src


def test_no_trailing_newline_survives() -> None:
    assert preprocess("a\nb", _profile()) == "a\nb"


def test_the_empty_script_is_fine() -> None:
    assert preprocess("", _profile()) == ""


def test_crlf_line_endings_are_preserved_through_a_dropped_block_and_substitution() -> None:
    out = preprocess("-- @if A\r\nx\r\n-- @end\r\ny = ${N}\r\n", _profile("N=2"))
    assert out == "-- @if A\r\n\r\n-- @end\r\ny = 2\r\n"


def test_line_numbers_never_shift() -> None:
    src = "a\n-- @if A\nb\nc\n-- @else\nd\n-- @end\ne = ${N}\nf\n"
    for flags in ("FLAGS=A", "FLAGS="):
        out = preprocess(src, _profile(f"{flags}\nN=1"))
        assert out.count("\n") == src.count("\n")
        assert out.split("\n")[0] == "a" and out.split("\n")[7] == "e = 1" and out.split("\n")[8] == "f"


# -- profiles on disk ----------------------------------------------------------------------------------------


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "script" / "env").mkdir(parents=True)
    return tmp_path


def _write_env(project: Path, name: str, text: str) -> None:
    (project / "script" / "env" / f"{name}.env").write_text(text, encoding="utf-8")


def test_profiles_are_the_env_files_in_script_env_sorted(project: Path) -> None:
    _write_env(project, "release", "")
    _write_env(project, "dev", "")
    (project / "script" / "env" / "notes.txt").write_text("not a profile")
    assert sp.list_profiles(project) == ["dev", "release"]


def test_a_project_with_no_env_folder_has_no_profiles(tmp_path: Path) -> None:
    assert sp.list_profiles(tmp_path) == []
    assert sp.active_profile_name(tmp_path) is None


def test_the_active_profile_round_trips_and_can_be_cleared(project: Path) -> None:
    _write_env(project, "dev", "")
    sp.set_active_profile(project, "dev")
    assert sp.active_profile_name(project) == "dev"
    sp.set_active_profile(project, None)
    assert sp.active_profile_name(project) is None


def test_clearing_when_nothing_is_active_is_fine(project: Path) -> None:
    sp.set_active_profile(project, None)


def test_choosing_a_profile_that_does_not_exist_is_an_error_listing_the_real_ones(project: Path) -> None:
    _write_env(project, "dev", "")
    with pytest.raises(ValueError, match=r"'nope' isn't a profile of this project \(have: dev\)"):
        sp.set_active_profile(project, "nope")


def test_a_blank_active_file_means_none(project: Path) -> None:
    (project / "script" / "env" / sp.ACTIVE_PROFILE_FILENAME).write_text("  \n")
    assert sp.active_profile_name(project) is None


def test_preprocess_project_uses_the_active_profile(project: Path) -> None:
    _write_env(project, "dev", "FLAGS=DEV\nSCORE=5\n")
    _write_env(project, "release", "SCORE=50\n")
    src = "-- @if DEV\ndebug\n-- @end\nwin at ${SCORE}\n"
    sp.set_active_profile(project, "dev")
    dev = sp.preprocess_project(project, src)
    sp.set_active_profile(project, "release")
    release = sp.preprocess_project(project, src)
    assert "debug" in dev and "win at 5" in dev
    assert "debug" not in release and "win at 50" in release


def test_preprocess_project_with_no_active_profile_leaves_plain_text_untouched(project: Path) -> None:
    assert sp.preprocess_project(project, "x = 1\n") == "x = 1\n"


def test_preprocess_project_with_no_active_profile_still_drops_flag_blocks_and_rejects_constants(project: Path) -> None:
    assert "dev" not in sp.preprocess_project(project, "-- @if DEV\ndev\n-- @end\n")
    with pytest.raises(PreprocessError, match="no environment profile is active"):
        sp.preprocess_project(project, "x = ${A}\n")


def test_an_active_profile_whose_file_is_missing_is_a_clear_error(project: Path) -> None:
    (project / "script" / "env" / sp.ACTIVE_PROFILE_FILENAME).write_text("ghost\n")
    with pytest.raises(PreprocessError, match="the active profile 'ghost' has no file") as excinfo:
        sp.preprocess_project(project, "x\n")
    assert excinfo.value.path == project / "script" / "env" / "ghost.env"


def test_a_broken_env_file_is_reported_against_that_file(project: Path) -> None:
    _write_env(project, "dev", "A=1\nB=oops oops\n")
    sp.set_active_profile(project, "dev")
    with pytest.raises(PreprocessError) as excinfo:
        sp.preprocess_project(project, "x\n")
    assert excinfo.value.path == project / "script" / "env" / "dev.env" and excinfo.value.line == 2
