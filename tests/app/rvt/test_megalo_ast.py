"""in_reach.app.rvt.megalo_ast -- parses script/output.txt (RVT's decompiler output) into a
traversable AST and back. Ported from a prior prototype's own test suite
(``D:\\whileyRepos\\sort\\mega-ide\\tests\\test_megalo_ast.py``, PROMPT.md: "we want a fromm
scratch compiler then") -- see :mod:`in_reach.app.rvt.megalo_ast.nodes`'s own module docstring for
the full port note.

Round-trip tests use a freshly ``decompile_script()``'d string for each fixture (not a checked-in
golden ``type_code.txt``, unlike the prior prototype's own version of this file) -- keeps every
fixture's expected text derived from the one real, authoritative source (the ``.bin`` itself) rather
than a second, separately-maintained golden copy.
"""
import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from in_reach.app.blank_variant import resolve_blank_variant
from in_reach.app.rvt import rvt_bridge
from in_reach.app.rvt.megalo_ast import (
    Assignment, BinaryOp, Call, DoBlock, EventTrigger, ExprStatement, ForEach, Identifier,
    IfStatement, Index, IntLiteral, Member, MegaloLexError, MegaloParseError, PercentLiteral,
    Script, StringLiteral, UnaryOp, VariableDeclaration, find_at, parse, render_expr, unparse, walk,
)

_FIXTURES_DIR = Path(__file__).parent / "resources"
_FIXTURE_BINS = {
    "juggernaut": _FIXTURES_DIR / "juggernaut" / "juggernaut.bin",
    "infection": _FIXTURES_DIR / "infection" / "infection.bin",
    "invasion": _FIXTURES_DIR / "invasion" / "invasion.bin",
}
_NEEDS_NATIVE_RVT = pytest.mark.skipif(
    not rvt_bridge.is_available(), reason="native _reachvarianttool extension not available on this platform"
)


def _fixture_text(name: str) -> str:
    """The real, freshly-decompiled Megalo script text for one of ``_FIXTURE_BINS``, or the
    packaged blank multiplayer/Firefight variant for "blank_mp"/"blank_ff"."""
    rvt = rvt_bridge.get_rvt()
    if name == "blank_mp":
        bin_path = resolve_blank_variant(firefight=False)
    elif name == "blank_ff":
        bin_path = resolve_blank_variant(firefight=True)
    else:
        bin_path = _FIXTURE_BINS[name]
    return rvt.load(str(bin_path)).decompile_script()


def _dump_no_span(obj):
    """Structural comparison helper: strips `span` (position-in-source metadata) so two trees
    parsed from differently-formatted-but-equivalent text -- e.g. the original fixture text vs.
    unparse()'s own re-canonicalized rendering of it -- can be compared shape-for-shape without
    positions (which necessarily differ) getting in the way."""
    if isinstance(obj, BaseModel):
        return {k: _dump_no_span(v) for k, v in obj.__dict__.items() if k != "span"}
    if isinstance(obj, list):
        return [_dump_no_span(v) for v in obj]
    return obj


# -- parsing real fixtures -----------------------------------------------------------------------


@_NEEDS_NATIVE_RVT
@pytest.mark.parametrize("name", ["blank_ff", "blank_mp", "infection", "invasion", "juggernaut"])
def test_every_fixture_parses(name: str) -> None:
    script = parse(_fixture_text(name))
    assert isinstance(script, Script)


@_NEEDS_NATIVE_RVT
@pytest.mark.parametrize("name", ["infection", "invasion", "juggernaut"])
def test_real_gametypes_produce_a_non_trivial_tree(name: str) -> None:
    script = parse(_fixture_text(name))
    assert len(script.body) > 10
    assert sum(1 for _ in walk(script)) > 100


@_NEEDS_NATIVE_RVT
@pytest.mark.parametrize("name", ["blank_ff", "blank_mp"])
def test_blank_fixtures_parse_to_an_empty_script(name: str) -> None:
    assert parse(_fixture_text(name)).body == []


# -- round-tripping -------------------------------------------------------------------------------


@_NEEDS_NATIVE_RVT
@pytest.mark.parametrize("name", ["blank_ff", "blank_mp", "infection", "invasion", "juggernaut"])
def test_unparse_output_is_stable_under_a_second_pass(name: str) -> None:
    script = parse(_fixture_text(name))
    once = unparse(script)
    twice = unparse(parse(once))
    assert once == twice


@_NEEDS_NATIVE_RVT
@pytest.mark.parametrize("name", ["infection", "invasion", "juggernaut"])
def test_reparsing_unparsed_output_matches_original_tree_shape(name: str) -> None:
    """Structural equality (see _dump_no_span()) rather than full node equality -- positions
    necessarily shift between the original text and unparse()'s re-canonicalized rendering of it
    (different indentation/line-ending bytes), only the tree shape has to survive."""
    original = parse(_fixture_text(name))
    reparsed = parse(unparse(original))
    assert _dump_no_span(original) == _dump_no_span(reparsed)


def test_empty_script_unparses_to_a_single_blank_line() -> None:
    assert unparse(Script(body=[])) == "\r\n"


# -- JSON serialization -----------------------------------------------------------------------


@_NEEDS_NATIVE_RVT
def test_model_dump_json_round_trips_through_model_validate_json() -> None:
    script = parse(_fixture_text("invasion"))
    dumped = script.model_dump_json()
    reloaded = Script.model_validate_json(dumped)
    assert script == reloaded


@_NEEDS_NATIVE_RVT
def test_dumped_json_is_plain_json() -> None:
    script = parse(_fixture_text("juggernaut"))
    # model_dump_json() must produce something json.loads() itself accepts, independent of
    # pydantic.
    data = json.loads(script.model_dump_json())
    assert data["kind"] == "script"
    assert isinstance(data["body"], list)


# -- node shape spot checks (pinned to real juggernaut.bin content) -------------------------------


@pytest.fixture
def juggernaut_script():
    if not rvt_bridge.is_available():
        pytest.skip("native _reachvarianttool extension not available on this platform")
    return parse(_fixture_text("juggernaut"))


def test_first_declaration(juggernaut_script) -> None:
    decl = juggernaut_script.body[0]
    assert isinstance(decl, VariableDeclaration)
    assert (decl.scope, decl.type, decl.index) == ("global", "number", 0)
    assert decl.priority == "local"
    assert decl.value is None


def test_declaration_with_a_default_value(juggernaut_script) -> None:
    # declare global.timer[0] = script_option[2]
    decl = next(
        d for d in juggernaut_script.body
        if isinstance(d, VariableDeclaration) and d.type == "timer" and d.index == 0
    )
    assert isinstance(decl.value, Index)
    assert decl.value.target == Identifier(name="script_option", span=decl.value.target.span)
    assert decl.value.index == IntLiteral(value=2, span=decl.value.index.span)


def test_for_each_with_label_and_bare_statement_body(juggernaut_script) -> None:
    for_each = next(s for s in walk(juggernaut_script) if isinstance(s, ForEach) and s.selector == "object")
    assert for_each.label == IntLiteral(value=2, span=for_each.label.span)
    assert for_each.randomly is False


def test_for_each_randomly(juggernaut_script) -> None:
    for_each = next(s for s in walk(juggernaut_script) if isinstance(s, ForEach) and s.randomly)
    assert for_each.selector == "player"
    assert for_each.label is None


def test_on_event_trigger(juggernaut_script) -> None:
    trigger = next(s for s in walk(juggernaut_script) if isinstance(s, EventTrigger))
    assert trigger.event == "host migration"
    assert isinstance(trigger.body, DoBlock)


def test_member_index_call_chain(juggernaut_script) -> None:
    # global.timer[0].set_rate(-100%)
    call = next(
        n for n in walk(juggernaut_script)
        if isinstance(n, Call) and isinstance(n.target, Member) and n.target.name == "set_rate"
    )
    assert len(call.args) == 1
    assert isinstance(call.args[0], PercentLiteral)
    assert call.args[0].value == -100
    set_rate_member = call.target
    assert isinstance(set_rate_member.target, Index)
    timer_index = set_rate_member.target
    assert timer_index.index == IntLiteral(value=0, span=timer_index.index.span)
    assert isinstance(timer_index.target, Member)
    assert timer_index.target.name == "timer"
    assert timer_index.target.target == Identifier(name="global", span=timer_index.target.target.span)


def test_and_or_not_precedence(juggernaut_script) -> None:
    # if global.timer[1].is_zero() and not global.player[0] == no_player and
    #    not global.player[0].is_not_respawning() then
    if_stmt = next(
        s for s in walk(juggernaut_script)
        if isinstance(s, IfStatement) and isinstance(s.condition, BinaryOp) and s.condition.op == "and"
        and isinstance(s.condition.right, UnaryOp)
    )
    cond = if_stmt.condition
    assert cond.op == "and"
    # right-hand side is itself "and"-chained left-associatively: (A and B) and C
    assert isinstance(cond.left, BinaryOp)
    assert cond.left.op == "and"
    assert isinstance(cond.right, UnaryOp)
    assert cond.right.op == "not"


def test_killer_type_is_flag_combination(juggernaut_script) -> None:
    call = next(
        n for n in walk(juggernaut_script)
        if isinstance(n, Call) and isinstance(n.target, Member) and n.target.name == "killer_type_is"
    )
    assert len(call.args) == 1
    flags = call.args[0]
    assert isinstance(flags, BinaryOp)
    assert flags.op == "|"
    names = []
    node = flags
    while isinstance(node, BinaryOp) and node.op == "|":
        names.append(node.right.name)
        node = node.left
    names.append(node.name)
    assert set(names) == {"guardians", "suicide", "kill", "betrayal", "quit"}


def test_string_literal_with_embedded_escape_text(juggernaut_script) -> None:
    lit = next(n for n in walk(juggernaut_script) if isinstance(n, StringLiteral) and "Juggernaut" in n.value)
    assert "\\r\\n" in lit.value  # literal backslash-r-backslash-n, not real control chars


def test_assignment_and_bare_call_statement() -> None:
    do_block = parse("do\n   global.number[0] = 1\n   current_object.delete()\nend\n").body[0]
    assert isinstance(do_block, DoBlock)
    assign, call_stmt = do_block.body
    assert isinstance(assign, Assignment)
    assert assign.op == "="
    assert isinstance(call_stmt, ExprStatement)
    assert isinstance(call_stmt.expr, Call)


@pytest.mark.parametrize("op", ["+=", "-=", "*=", "/=", "%="])
def test_compound_assignment_operators(op: str) -> None:
    stmt = parse(f"global.number[0] {op} 1\n").body[0]
    assert isinstance(stmt, Assignment)
    assert stmt.op == op


# -- span / find_at ---------------------------------------------------------------------------

_SNIPPET = (
    "for each player do\n"
    "   if current_player.is_elite() then \n"
    "      current_player.set_loadout_palette(elite_tier_1)\n"
    "   end\n"
    "end\n"
)


@pytest.fixture
def snippet_script():
    return parse(_SNIPPET)


def test_every_node_has_a_1_based_line_span(snippet_script) -> None:
    for node in walk(snippet_script):
        if node is snippet_script:
            continue
        assert node.span.start_line >= 1
        assert node.span.end_line >= node.span.start_line


def test_find_at_locates_the_most_specific_node(snippet_script) -> None:
    # line 3, col 6: start of "current_player.set_loadout_palette(elite_tier_1)"
    node = find_at(snippet_script, 3, 6)
    assert node is not None
    assert node.kind == "identifier"
    assert node.name == "current_player"


def test_find_at_returns_none_outside_any_span(snippet_script) -> None:
    assert find_at(snippet_script, 10_000, 0) is None


# -- lexer/parser errors ---------------------------------------------------------------------


def test_unterminated_string_raises() -> None:
    with pytest.raises(MegaloLexError):
        parse('current_player.set_objective_text("unterminated')


def test_unexpected_character_raises() -> None:
    with pytest.raises(MegaloLexError):
        parse("global.number[0] = @")


def test_missing_end_raises() -> None:
    with pytest.raises(MegaloParseError):
        parse("do\n   global.number[0] = 1\n")


@pytest.mark.parametrize("keyword", ["function", "enum", "inline"])
def test_unimplemented_reserved_keywords_raise_rather_than_silently_misparse(keyword: str) -> None:
    """function/enum/inline are real, reserved Compiler keywords (confirmed via compile_script(),
    see nodes.py's module docstring) this grammar doesn't implement a production for -- must raise,
    not silently fall through to being treated as a bare Identifier/Call expression."""
    with pytest.raises(MegaloParseError):
        parse(f"{keyword} foo\nend\n")


@pytest.mark.parametrize("keyword", ["else", "elseif"])
def test_literal_else_elseif_still_do_not_work(keyword: str) -> None:
    """Confirmed directly against the real compiler (compile_script() fails with "Word "else" is
    reserved for potential future use as a keyword") -- alt/altif are the real, working equivalent
    (see IfStatementAltTests below), not else/elseif."""
    with pytest.raises(MegaloParseError):
        parse(f"if global.number[0] == 0 then\n   global.number[0] = 1\n{keyword}\n   global.number[0] = 2\nend\n")


# -- comments ---------------------------------------------------------------------------------


def test_standalone_and_trailing_comments_are_collected_not_woven_into_the_tree() -> None:
    script = parse(
        "-- leading comment\n"
        "do\n"
        "   global.number[0] = 0 -- trailing comment\n"
        "   -- standalone comment\n"
        "end\n"
    )
    assert len(script.body) == 1  # comments never became statements
    assert [c.text for c in script.comments] == [" leading comment", " trailing comment", " standalone comment"]


def test_comment_text_is_unstripped_after_the_dashes() -> None:
    script = parse("--no leading space\n")
    assert script.comments[0].text == "no leading space"


def test_unparse_does_not_re_emit_comments() -> None:
    script = parse("-- a comment\ndo\n   global.number[0] = 0\nend\n")
    assert "comment" not in unparse(script)


@_NEEDS_NATIVE_RVT
def test_real_compile_script_accepts_comments() -> None:
    """Belt-and-suspenders: confirm this grammar's assumption against the real compiler, not just
    against itself."""
    rvt = rvt_bridge.get_rvt()
    variant = rvt.load(str(_FIXTURE_BINS["juggernaut"]))
    result = variant.multiplayer.compile_script("-- a comment\ndo\n   global.number[0] = 0\nend\n")
    assert result.success is True


# -- alias declarations -----------------------------------------------------------------------


def test_alias_parses_as_its_own_node() -> None:
    script = parse("alias my_num = global.number[0]\n")
    decl = script.body[0]
    assert decl.kind == "alias"
    assert decl.name == "my_num"
    assert render_expr(decl.value) == "global.number[0]"


def test_alias_use_site_is_a_plain_identifier() -> None:
    # aliases are compile-time-only -- decompile_script() resolves them away entirely -- this
    # grammar doesn't resolve them either, a use site just parses as an ordinary Identifier.
    script = parse("alias my_num = global.number[0]\ndo\n   my_num = 5\nend\n")
    do_block = script.body[1]
    assign = do_block.body[0]
    assert assign.target.kind == "identifier"
    assert assign.target.name == "my_num"


def test_alias_round_trips() -> None:
    text = "alias my_num = global.number[0]\ndo\n   my_num = 5\nend\n"
    script = parse(text)
    reparsed = parse(unparse(script))
    assert _dump_no_span(script) == _dump_no_span(reparsed)


@_NEEDS_NATIVE_RVT
def test_real_compile_script_accepts_alias() -> None:
    rvt = rvt_bridge.get_rvt()
    variant = rvt.load(str(_FIXTURE_BINS["juggernaut"]))
    result = variant.multiplayer.compile_script("alias my_num = global.number[0]\ndo\n   my_num = 5\nend\n")
    assert result.success is True


# -- alt/altif (the real, working else/elseif equivalent) -----------------------------------


def test_bare_if_has_no_altif_or_alt() -> None:
    script = parse("if global.number[0] == 0 then\n   global.number[0] = 1\nend\n")
    stmt = script.body[0]
    assert stmt.altif_clauses == []
    assert stmt.alt_body is None


def test_if_alt_end() -> None:
    script = parse(
        "if global.number[0] == 0 then\n"
        "   global.number[0] = 1\n"
        "alt\n"
        "   global.number[0] = 2\n"
        "end\n"
    )
    stmt = script.body[0]
    assert stmt.altif_clauses == []
    assert stmt.alt_body is not None
    assert len(stmt.alt_body) == 1


def test_if_altif_altif_alt_chain() -> None:
    script = parse(
        "if global.number[0] == 0 then\n"
        "   global.number[0] = 1\n"
        "altif global.number[0] == 1 then\n"
        "   global.number[0] = 2\n"
        "altif global.number[0] == 2 then\n"
        "   global.number[0] = 3\n"
        "alt\n"
        "   global.number[0] = 4\n"
        "end\n"
    )
    stmt = script.body[0]
    assert len(stmt.altif_clauses) == 2
    assert render_expr(stmt.altif_clauses[0].condition) == "global.number[0] == 1"
    assert render_expr(stmt.altif_clauses[1].condition) == "global.number[0] == 2"
    assert stmt.alt_body is not None


def test_altif_alt_round_trips() -> None:
    text = (
        "if global.number[0] == 0 then\n"
        "   global.number[0] = 1\n"
        "altif global.number[0] == 1 then\n"
        "   global.number[0] = 2\n"
        "alt\n"
        "   global.number[0] = 3\n"
        "end\n"
    )
    script = parse(text)
    reparsed = parse(unparse(script))
    assert _dump_no_span(script) == _dump_no_span(reparsed)


@_NEEDS_NATIVE_RVT
def test_real_compile_script_accepts_altif_alt_chain() -> None:
    rvt = rvt_bridge.get_rvt()
    variant = rvt.load(str(_FIXTURE_BINS["juggernaut"]))
    src = (
        "if global.number[0] == 0 then\n"
        "   global.number[0] = 1\n"
        "altif global.number[0] == 1 then\n"
        "   global.number[0] = 2\n"
        "alt\n"
        "   global.number[0] = 3\n"
        "end\n"
    )
    result = variant.multiplayer.compile_script(src)
    assert result.success is True
