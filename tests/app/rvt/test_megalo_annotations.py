"""``-- @name ...`` annotation comments: :func:`~in_reach.app.rvt.megalo_ast.parse_annotations`.

The grammar is in the module's own docstring (and ``TO_IMPLEMENT`` §4.8). What's pinned here: every annotation
of the design parses to the right shape, every malformed one is reported at the right line and column without
losing the good ones around it, and annotations really are ordinary comments -- the statement parser and the
compilers are unaffected by them.
"""
import pytest

from in_reach.app.rvt import megalo_compiler, rvt_bridge, template_source
from in_reach.app.rvt.decompile import normalize_script_text
from in_reach.app.rvt.megalo_ast import (
    Annotations, IntLiteral, MegaloParseError, parse, parse_annotations, parse_expression,
)


def _one(text: str):
    result = parse_annotations(text)
    assert result.diagnostics == [], [d.message for d in result.diagnostics]
    assert len(result.items) == 1
    return result.items[0]


def _problem(text: str):
    """The single diagnostic for a single malformed annotation line."""
    result = parse_annotations(text)
    assert result.items == []
    assert len(result.diagnostics) == 1, [d.message for d in result.diagnostics]
    return result.diagnostics[0]


# -- what counts as an annotation -----------------------------------------------------------------------


def test_only_a_comment_that_starts_its_line_with_an_at_sign_is_an_annotation() -> None:
    text = "-- an ordinary comment\nx = 1 -- @doc not one, it trails code\n-- @ doc space after the @\n"

    assert parse_annotations(text) == Annotations()


def test_indentation_and_spacing_around_the_dashes_are_free() -> None:
    assert _one("      --   @doc hello").text == "hello"
    assert _one("--@doc hello").text == "hello"


def test_profile_directives_are_not_annotations() -> None:
    text = "-- @if DEV\n-- @if !DEV\n-- @else\n-- @end\n"

    assert parse_annotations(text) == Annotations()


def test_a_guard_end_is_not_the_end_directive() -> None:
    assert _one("-- @guard-end").kind == "guard_end"


def test_annotations_come_back_in_source_order_with_the_ones_around_them() -> None:
    text = "x = 1\n-- @doc first\ny = 2\n\n  -- @see SECOND\n"

    result = parse_annotations(text)

    assert [(a.kind, a.span.start_line) for a in result.items] == [("doc", 2), ("see", 5)]


def test_a_span_covers_from_the_at_sign_to_the_end_of_the_line() -> None:
    annotation = _one("    -- @see HEALTH   ")

    assert (annotation.span.start_line, annotation.span.start_col, annotation.span.end_col) == (1, 7, 18)


def test_a_note_after_a_second_dash_pair_is_kept_and_not_parsed() -> None:
    annotation = _one("-- @pnumber p_hud priority=high   -- player.number, shown on the HUD")

    assert annotation.name == "p_hud" and annotation.priority == "high"
    assert annotation.note == "player.number, shown on the HUD"


def test_dashes_inside_a_string_do_not_start_a_note() -> None:
    annotation = _one('-- @label L_a = "a -- b"')

    assert annotation.text == "a -- b" and annotation.note is None


# -- storage --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("annotation", "scope", "type_"),
    [
        (f"{prefix}{type_}", scope, type_)
        for prefix, scope in (("", "global"), ("p", "player"), ("o", "object"), ("t", "team"))
        for type_ in ("number", "object", "player", "team", "timer")
    ],
)
def test_every_storage_annotation_names_its_scope_and_type(annotation: str, scope: str, type_: str) -> None:
    target = {"global": "g_x", "player": "p_x", "object": "carrier.c_x", "team": "team3.t_x"}[scope]

    parsed = _one(f"-- @{annotation} {target}")

    assert (parsed.kind, parsed.scope, parsed.type) == ("storage", scope, type_)


def test_global_and_player_storage_take_a_plain_name() -> None:
    parsed = _one("-- @number g_phase priority=low")

    assert (parsed.name, parsed.owner, parsed.priority) == ("g_phase", None, "low")


def test_object_and_team_storage_are_declared_against_an_owner() -> None:
    assert (_one("-- @onumber carrier.c_role").owner, _one("-- @onumber carrier.c_role").name) == ("carrier", "c_role")
    team = _one("-- @tnumber team3.tc_mines_alive priority=low")
    assert (team.owner, team.name) == ("team3", "tc_mines_alive")


def test_a_default_is_a_parsed_expression_located_where_it_was_written() -> None:
    text = "-- @timer g_phase_timer default=6"

    parsed = _one(text)

    assert isinstance(parsed.default, IntLiteral) and parsed.default.value == 6
    assert parsed.default.span.start_col == text.index("6")


@pytest.mark.parametrize("value", ["-3", "script_option[2]", "game.loadout_cam_time", "team[1]", "neutral_team"])
def test_a_default_can_be_any_single_expression(value: str) -> None:
    assert _one(f"-- @number g default={value}").default is not None


def test_owns_default_is_a_boolean_for_object_storage() -> None:
    assert _one("-- @otimer carrier.c_cap default=24 owns_default=true").owns_default is True
    assert _one("-- @otimer carrier.c_cap default=24 owns_default=false").owns_default is False
    assert _one("-- @otimer carrier.c_cap default=24").owns_default is False


@pytest.mark.parametrize(
    ("text", "message", "at"),
    [
        ("-- @timer g priority=low", "a timer has no network priority", "priority=low"),
        ("-- @player g default=1", "a player variable has no initial value", "default=1"),
        ("-- @object g default=1", "an object variable has no initial value", "default=1"),
        ("-- @number g priority=urgent", "priority must be one of local, low, high", "priority=urgent"),
        ("-- @number g colour=red", "unknown option 'colour'", "colour=red"),
        ("-- @number g priority=low priority=high", "priority is given twice", "priority=high"),
        ("-- @number g default=", "default= needs a value", "default="),
        ("-- @number g low", "expected key=value", "low"),
        ("-- @number g default=1 +", "expected key=value", "+"),
        ("-- @number g owns_default=true", "unknown option 'owns_default'", "owns_default=true"),
        ("-- @onumber carrier.c owns_default=maybe", "owns_default must be true or false", "owns_default=maybe"),
        ("-- @onumber c_role", "expected KIND.NAME", "c_role"),
        ("-- @tnumber c_role", "expected TEAM.NAME", "c_role"),
        ("-- @number carrier.c_role", "must be a plain name", "carrier.c_role"),
        ("-- @number 9lives", "must be a plain name", "9lives"),
        ("-- @number current_player", "can't be used as a name", "current_player"),
        ("-- @number if", "can't be used as a name", "if"),
        ("-- @onumber carrier.game", "can't be used as a name", "carrier.game"),
    ],
)
def test_storage_problems_point_at_the_offending_argument(text: str, message: str, at: str) -> None:
    problem = _problem(text)

    assert message in problem.message
    assert (problem.span.start_line, problem.span.start_col) == (1, text.index(at))
    assert problem.span.end_col == text.index(at) + len(at)


def test_storage_without_a_name_is_reported() -> None:
    problem = _problem("-- @number")

    assert "needs a name" in problem.message


def test_a_default_that_is_not_an_expression_is_reported() -> None:
    assert "isn't a valid value" in _problem("-- @number g default=1==").message


# -- bitfields ------------------------------------------------------------------------------------------


def test_a_bitfield_lists_its_flags_in_order() -> None:
    parsed = _one("-- @bitfield carrier.c_flags { kit_given, aa_latch,small_scale }")

    assert (parsed.owner, parsed.name, parsed.flags) == ("carrier", "c_flags", ["kit_given", "aa_latch", "small_scale"])


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("-- @bitfield carrier.c_flags { a, b, a }", "flag a is listed twice"),
        ("-- @bitfield carrier.c_flags { }", "at least one flag"),
        ("-- @bitfield carrier.c_flags { a, 9b }", "isn't a valid flag name"),
        ("-- @bitfield carrier.c_flags a, b", "expected a { ... } group"),
        ("-- @bitfield carrier.c_flags { a, b", "never closed"),
        ("-- @bitfield carrier.c_flags", "needs KIND.NAME and a { flag, flag } group"),
        ("-- @bitfield c_flags { a }", "expected KIND.NAME"),
        ("-- @bitfield carrier.c_flags { a } extra", "unexpected 'extra'"),
    ],
)
def test_bitfield_problems(text: str, message: str) -> None:
    assert message in _problem(text).message


def test_a_trailing_comma_in_a_group_is_fine() -> None:
    assert _one("-- @bitfield carrier.c { a, b, }").flags == ["a", "b"]


# -- engine resources -----------------------------------------------------------------------------------


def test_a_trait_carries_its_fields_with_their_types() -> None:
    parsed = _one('-- @trait t_freeze { movement_speed = "value_000", jump_height = 0, sprint = true, mode = fast }')

    assert parsed.kind == "trait" and parsed.name == "t_freeze"
    assert parsed.fields == {"movement_speed": "value_000", "jump_height": 0, "sprint": True, "mode": "fast"}
    assert list(parsed.fields) == ["movement_speed", "jump_height", "sprint", "mode"]  # order kept
    assert parsed.fields["sprint"] is True and parsed.fields["jump_height"] == 0


def test_options_and_widgets_parse_like_traits() -> None:
    option = _one('-- @option o_round { type = "range", min = 1, max = 30, default = 10, name = "Round minutes" }')
    widget = _one('-- @widget w_hud { position = "top_left" }')

    assert option.kind == "option" and option.fields["name"] == "Round minutes" and option.fields["max"] == 30
    assert widget.kind == "widget" and widget.fields == {"position": "top_left"}


def test_negative_numbers_and_commas_inside_strings_are_values() -> None:
    parsed = _one('-- @option o { name = "a, b", offset = -5, }')

    assert parsed.fields == {"name": "a, b", "offset": -5}


def test_a_resource_without_a_group_has_no_fields() -> None:
    assert _one("-- @widget w_hud").fields == {}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("-- @trait", "needs a name"),
        ("-- @trait current_player { a = 1 }", "can't be used as a name"),
        ("-- @trait t { a = 1, a = 2 }", "a is given twice"),
        ("-- @trait t { a }", "expected name = value"),
        ("-- @trait t { = 1 }", "expected name = value"),
        ("-- @trait t { a = }", "isn't a number"),
        ("-- @trait t { a = 1 2 }", "isn't a number"),
        ("-- @trait t a = 1", "expected a { ... } group"),
        ("-- @trait t { a = 1 } { b = 2 }", "unexpected '{ b = 2 }'"),
        ('-- @trait t { a = "open }', "never closed"),
    ],
)
def test_resource_problems(text: str, message: str) -> None:
    assert message in _problem(text).message


def test_a_label_maps_a_name_to_its_text() -> None:
    parsed = _one('-- @label L_hill = "hill"')

    assert (parsed.kind, parsed.name, parsed.text) == ("label", "L_hill", "hill")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('-- @label L_hill "hill"', "needs NAME"),
        ('-- @label L_hill hill "x"', "expected '='"),
        ("-- @label L_hill = hill", "must be a \"quoted string\""),
        ('-- @label L_hill = "a" "b"', "unexpected"),
        ('-- @label none = "a"', "can't be used as a name"),
    ],
)
def test_label_problems(text: str, message: str) -> None:
    assert message in _problem(text).message


# -- fragments and preambles ----------------------------------------------------------------------------


def test_a_fragment_is_a_block_and_a_name() -> None:
    parsed = _one("-- @fragment HUMAN_PASS.health_tiers")

    assert (parsed.block, parsed.name) == ("HUMAN_PASS", "health_tiers")


@pytest.mark.parametrize("selector", ["player", "object", "team"])
def test_a_loop_names_what_it_iterates(selector: str) -> None:
    assert _one(f"-- @loop {selector}").selector == selector


def test_a_gate_is_a_parsed_condition_located_where_it_was_written() -> None:
    text = "  -- @gate     g_phase == phase_live"

    parsed = _one(text)

    assert parsed.condition.kind == "binary" and parsed.condition.op == "=="
    assert (parsed.condition.span.start_line, parsed.condition.span.start_col) == (1, text.index("g_phase"))


def test_a_guard_may_use_and_and_or_and_a_note() -> None:
    parsed = _one("-- @guard role == 1 or role == 2 and cx != no_object   -- only marines")

    assert parsed.kind == "guard" and parsed.condition.op == "and"
    assert parsed.note == "only marines"


def test_a_condition_reports_where_it_stops_making_sense() -> None:
    text = "-- @gate g_phase == "

    problem = _problem(text)

    assert "expected an expression" in problem.message
    assert problem.span.start_line == 1 and problem.span.start_col >= text.index("==")


@pytest.mark.parametrize("text", ["-- @gate", "-- @guard   ", "-- @gate a == b c"])
def test_a_missing_or_overlong_condition_is_reported(text: str) -> None:
    assert _problem(text).message


def test_a_condition_on_a_later_line_is_reported_on_that_line() -> None:
    result = parse_annotations("x = 1\n\n-- @gate a ==\n")

    assert [d.span.start_line for d in result.diagnostics] == [3]


def test_a_preamble_is_a_name_and_provides_lists_typed_variables() -> None:
    assert _one("-- @preamble human_ctx").name == "human_ctx"
    provided = _one("-- @provides cx:object cb:object role:number")

    assert [(v.name, v.type) for v in provided.variables] == [("cx", "object"), ("cb", "object"), ("role", "number")]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("-- @provides", "needs name:type pairs"),
        ("-- @provides cx", "expected name:type"),
        ("-- @provides cx:thing", "isn't a type"),
        ("-- @provides cx:object cx:number", "cx is listed twice"),
        ("-- @provides none:object", "can't be used as a name"),
        ("-- @preamble", "needs a name"),
        ("-- @preamble a b", "unexpected 'b'"),
    ],
)
def test_preamble_problems(text: str, message: str) -> None:
    assert message in _problem(text).message


def test_traits_names_a_layer() -> None:
    assert _one("-- @traits layer=injury").layer == "injury"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("-- @traits", "needs layer=NAME"),
        ("-- @traits injury", "expected key=value"),
        ("-- @traits order=1", "unknown option 'order'"),
        ("-- @traits layer=9x", "must be a plain name"),
    ],
)
def test_traits_problems(text: str, message: str) -> None:
    assert message in _problem(text).message


@pytest.mark.parametrize(
    ("value", "mode", "group"),
    [("auto", "auto", None), ("never", "never", None), ("subroutine", "subroutine", None), ("force:hill", "force", "hill")],
)
def test_fusion_modes(value: str, mode: str, group: str | None) -> None:
    parsed = _one(f"-- @fusion {value}")

    assert (parsed.mode, parsed.group) == (mode, group)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("-- @fusion", "needs auto, never"),
        ("-- @fusion always", "expected auto, never, subroutine or force:GROUP"),
        ("-- @fusion force", "force needs a group"),
        ("-- @fusion force:", "force needs a group"),
        ("-- @fusion auto:x", "expected auto, never"),
        ("-- @fusion auto never", "unexpected 'never'"),
    ],
)
def test_fusion_problems(text: str, message: str) -> None:
    assert message in _problem(text).message


def test_a_loop_and_guard_end_take_exactly_what_they_should() -> None:
    assert "expected one of player, object, team" in _problem("-- @loop players").message
    assert "takes no arguments" in _problem("-- @guard-end now").message
    assert "needs BLOCK.NAME" in _problem("-- @fragment").message or "needs" in _problem("-- @fragment").message
    assert "expected BLOCK.NAME" in _problem("-- @fragment HUMAN_PASS").message


# -- documentation --------------------------------------------------------------------------------------


def test_doc_keeps_the_whole_rest_of_the_line_including_dashes() -> None:
    parsed = _one("-- @doc Heals a marine -- slowly, over ten seconds.")

    assert parsed.text == "Heals a marine -- slowly, over ten seconds."


def test_see_and_assumes_take_one_name() -> None:
    assert _one("-- @see HEALTH_TIERS").tag == "HEALTH_TIERS"
    assert _one("-- @assumes HUMAN_PASS").block == "HUMAN_PASS"


@pytest.mark.parametrize(
    ("text", "message"),
    [("-- @doc", "needs some text"), ("-- @see", "needs a tag"), ("-- @see a b", "unexpected 'b'"), ("-- @assumes", "needs a block name")],
)
def test_documentation_problems(text: str, message: str) -> None:
    assert message in _problem(text).message


# -- diagnostics ----------------------------------------------------------------------------------------


def test_an_unknown_annotation_is_reported_with_a_suggestion() -> None:
    problem = _problem("-- @fragmnet HUMAN_PASS.x")

    assert "unknown annotation @fragmnet" in problem.message
    assert "did you mean @fragment?" in problem.message
    assert (problem.span.start_col, problem.span.end_col) == (3, 3 + len("@fragmnet"))


def test_an_unknown_annotation_with_nothing_close_gets_no_suggestion() -> None:
    assert "did you mean" not in _problem("-- @zzzzzz thing").message


def test_a_bad_annotation_does_not_lose_the_good_ones_around_it() -> None:
    text = "-- @number ok\n-- @timer bad priority=low\n-- @number also_ok\n"

    result = parse_annotations(text)

    assert [a.name for a in result.items] == ["ok", "also_ok"]
    assert [(d.span.start_line, d.message) for d in result.diagnostics] == [(2, "a timer has no network priority")]


def test_every_malformed_annotation_is_reported_not_just_the_first() -> None:
    text = "-- @loop nope\n-- @unknown\n-- @trait t { a }\n"

    assert [d.span.start_line for d in parse_annotations(text).diagnostics] == [1, 2, 3]


def test_an_unterminated_string_is_reported_at_the_string() -> None:
    text = '-- @label L = "never closed'

    problem = _problem(text)

    assert "never closed" in problem.message
    assert problem.span.start_col == text.index('"')


def test_parse_annotations_never_raises_on_garbage() -> None:
    garbage = "-- @\n-- @@\n-- @{{{\n-- @doc\n-- @trait {\n-- @trait t {\n-- @number \"\n-- @gate (((\n" + "-- @x" * 50
    parse_annotations(garbage)


def test_crlf_line_endings_are_fine() -> None:
    result = parse_annotations("-- @number g\r\n-- @loop player\r\n")

    assert [a.kind for a in result.items] == ["storage", "loop"]


# -- annotations are ordinary comments ------------------------------------------------------------------


_ANNOTATED = (
    "-- @number g_phase priority=low\n"
    "-- @doc Scores a point each second.\n"
    "global.number[0] = 1\n"
    "-- @loop player\n"
    "for each player do\n"
    "   -- @guard current_player.number[0] == 1\n"
    "   current_player.number[0] += 1\n"
    "end\n"
)


def test_the_statement_parser_sees_annotations_only_as_comments() -> None:
    script = parse(_ANNOTATED)

    annotation_comments = [c for c in script.comments if c.text.lstrip().startswith("@")]
    assert len(annotation_comments) == len(parse_annotations(_ANNOTATED).items) == 4
    assert [s.kind for s in script.body] == ["assign", "for_each"]  # the code is what it would be without them


def test_annotations_survive_a_json_round_trip() -> None:
    result = parse_annotations(_ANNOTATED + '-- @trait t { a = 1 }\n-- @fusion force:g\n')

    assert Annotations.model_validate_json(result.model_dump_json()) == result


@pytest.mark.skipif(not rvt_bridge.is_available(), reason="native _reachvarianttool extension not available on this platform")
def test_annotation_lines_change_nothing_about_what_is_compiled() -> None:
    from in_reach.app.blank_variant import resolve_blank_variant

    rvt = rvt_bridge.get_rvt()

    def compiled(source: str) -> str:
        variant = rvt.load(str(resolve_blank_variant(firefight=False)))
        megalo_compiler.compile_script(rvt, variant, source, template_pool=lambda: template_source.build_variants(rvt))
        return normalize_script_text(variant.decompile_script())

    plain = "\n".join(line for line in _ANNOTATED.splitlines() if not line.lstrip().startswith("--")) + "\n"

    assert compiled(_ANNOTATED) == compiled(plain)


# -- parse_expression -----------------------------------------------------------------------------------


def test_parse_expression_places_every_span_where_the_text_really_is() -> None:
    expression = parse_expression("a == b", line=5, col=10)

    assert (expression.span.start_line, expression.span.start_col, expression.span.end_col) == (5, 10, 16)
    assert expression.left.span.start_col == 10 and expression.right.span.start_col == 15


@pytest.mark.parametrize("bad", ["", "a ==", "a == b c", "(", "a b"])
def test_parse_expression_rejects_anything_but_one_expression(bad: str) -> None:
    with pytest.raises(MegaloParseError):
        parse_expression(bad)


def test_a_parse_expression_error_reports_the_real_line_and_column() -> None:
    with pytest.raises(MegaloParseError) as raised:
        parse_expression("a == b c", line=9, col=4)

    assert (raised.value.token.start_line, raised.value.token.start_col) == (9, 11)
