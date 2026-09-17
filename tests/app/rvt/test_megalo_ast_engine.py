"""in_reach.app.rvt.megalo_ast.engine -- pydantic extraction over the real, compiled Megalo
trigger/opcode object graph. Ported from a prior prototype's own test suite
(``D:\\whileyRepos\\sort\\mega-ide\\tests\\test_megalo_ast_engine.py``, PROMPT.md: "we want a fromm
scratch compiler then") -- see :mod:`in_reach.app.rvt.megalo_ast.engine`'s own module docstring for
the full port note, and :mod:`in_reach.app.rvt.megalo_ast.nodes` for the separate, text-derived
``Script``/``Statement``/``Expression`` tree this is a sibling to, not a replacement for.
"""
import json
from pathlib import Path

import pytest

from in_reach.app.blank_variant import resolve_blank_variant
from in_reach.app.rvt import rvt_bridge
from in_reach.app.rvt.megalo_ast import (
    EngineActionStatement, EngineAst, EngineDoBlock, EngineForEachBlock, EngineIfStatement,
    EngineInlineBlock, EngineRawStatement, EngineTrigger, EngineTriggerCallStatement,
    extract_triggers, parse, render_expr,
)
from in_reach.app.rvt.megalo_ast import nodes as _text_nodes

_FIXTURES_DIR = Path(__file__).parent / "resources"
_FIXTURE_BINS = {
    "juggernaut": _FIXTURES_DIR / "juggernaut" / "juggernaut.bin",
    "infection": _FIXTURES_DIR / "infection" / "infection.bin",
    "invasion": _FIXTURES_DIR / "invasion" / "invasion.bin",
}
_MULTIPLAYER_FIXTURE_NAMES = ["blank_mp", "infection", "invasion", "juggernaut"]
_NEEDS_NATIVE_RVT = pytest.mark.skipif(
    not rvt_bridge.is_available(), reason="native _reachvarianttool extension not available on this platform"
)


def _fixture_bin_path(name: str) -> Path:
    if name == "blank_mp":
        return resolve_blank_variant(firefight=False)
    if name == "blank_ff":
        return resolve_blank_variant(firefight=True)
    return _FIXTURE_BINS[name]


def _fixture_text(name: str) -> str:
    rvt = rvt_bridge.get_rvt()
    return rvt.load(str(_fixture_bin_path(name))).decompile_script()


pytestmark = _NEEDS_NATIVE_RVT


# -- extract_triggers() ------------------------------------------------------------------------


@pytest.mark.parametrize("name", _MULTIPLAYER_FIXTURE_NAMES)
def test_every_multiplayer_fixture_extracts(name: str) -> None:
    rvt = rvt_bridge.get_rvt()
    variant = rvt.load(str(_fixture_bin_path(name)))
    triggers = extract_triggers(variant)
    assert isinstance(triggers, list)
    for t in triggers:
        assert isinstance(t, EngineTrigger)


@pytest.mark.parametrize("name", ["infection", "invasion", "juggernaut"])
def test_real_gametypes_produce_a_non_trivial_graph(name: str) -> None:
    rvt = rvt_bridge.get_rvt()
    variant = rvt.load(str(_fixture_bin_path(name)))
    triggers = extract_triggers(variant)
    assert len(triggers) > 5
    total_opcodes = sum(len(t.opcodes) for t in triggers)
    assert total_opcodes > 20


def test_firefight_only_variant_has_no_multiplayer_to_extract_from() -> None:
    rvt = rvt_bridge.get_rvt()
    variant = rvt.load(str(_fixture_bin_path("blank_ff")))
    assert variant.multiplayer is None
    with pytest.raises(AttributeError):
        extract_triggers(variant)


# -- juggernaut.bin node shape spot checks -----------------------------------------------------


@pytest.fixture
def juggernaut_triggers():
    rvt = rvt_bridge.get_rvt()
    variant = rvt.load(str(_FIXTURE_BINS["juggernaut"]))
    return extract_triggers(variant)


def test_trigger_0_is_a_for_each_player_loop(juggernaut_triggers) -> None:
    t0 = juggernaut_triggers[0]
    assert t0.block_type == "for_each_player"
    assert t0.entry_type == "normal"
    assert len(t0.opcodes) == 2
    for op in t0.opcodes:
        assert op.kind == "action"
        assert op.mapping_type == "none"
        assert op.text == "nop"


def test_trigger_1_is_the_is_elite_subroutine(juggernaut_triggers) -> None:
    t1 = juggernaut_triggers[1]
    assert t1.block_type == "normal"
    assert t1.entry_type == "subroutine"
    cond, action = t1.opcodes
    assert cond.kind == "condition"
    assert not cond.inverted
    assert cond.or_group == 0
    assert cond.gated_action_index == 0
    assert cond.text == "current_player.is_elite()"
    assert cond.function_name == "Species Is Elite"
    assert action.kind == "action"
    assert action.inverted is None
    assert action.text == "current_player.set_loadout_palette(elite_tier_1)"


def test_variable_argument_has_structured_fields(juggernaut_triggers) -> None:
    # trigger 4's "current_player.number[0] == 0" Compare condition
    arg = juggernaut_triggers[4].opcodes[0].arguments[0]
    assert arg.is_variable is True
    assert arg.variable_type == "scalar"
    assert arg.scope_format == "%w.number[%i]"
    assert arg.index == 0
    assert arg.text == "current_player.number[0]"


def test_non_variable_argument_has_no_structured_fields(juggernaut_triggers) -> None:
    # trigger 1's "elite_tier_1" loadout-palette argument
    arg = juggernaut_triggers[1].opcodes[1].arguments[1]
    assert arg.is_variable is False
    assert arg.variable_type == "not_a_variable"
    assert arg.scope_format is None
    assert arg.which is None
    assert arg.index is None
    assert arg.text == "elite_tier_1"


def test_description_differs_from_text(juggernaut_triggers) -> None:
    cond = juggernaut_triggers[1].opcodes[0]
    assert cond.description == "current_player is an Elite."
    assert cond.description != cond.text


# -- cross-check against the independent text grammar --------------------------------------------


def test_is_elite_condition_and_action_text_matches_between_both_ast_layers() -> None:
    """The engine-bound graph and the text-derived grammar (megalo_ast.parse()) are two
    independent implementations reading the same underlying script content -- juggernaut's "if
    current_player.is_elite() then ... end" subroutine should decompile to identical text through
    both paths. A mismatch here would mean one of the two AST layers has drifted from real Megalo
    syntax."""
    rvt = rvt_bridge.get_rvt()
    variant = rvt.load(str(_FIXTURE_BINS["juggernaut"]))
    engine_trigger = extract_triggers(variant)[1]
    engine_cond_text = engine_trigger.opcodes[0].text
    engine_action_text = engine_trigger.opcodes[1].text

    script = parse(_fixture_text("juggernaut"))
    # for each player do / if current_player.is_elite() then / current_player.set_loadout_palette(elite_tier_1) / end / end
    for_each = next(s for s in script.body if s.kind == "for_each")
    if_stmt = next(s for s in for_each.body if s.kind == "if")
    text_cond_text = render_expr(if_stmt.condition)
    text_action_text = render_expr(if_stmt.body[0].expr)

    assert engine_cond_text == text_cond_text
    assert engine_action_text == text_action_text


# -- JSON serialization -----------------------------------------------------------------------


def test_engine_ast_round_trips_through_json() -> None:
    rvt = rvt_bridge.get_rvt()
    variant = rvt.load(str(_FIXTURE_BINS["juggernaut"]))
    ast = EngineAst(triggers=extract_triggers(variant))
    dumped = ast.model_dump_json()
    reloaded = EngineAst.model_validate_json(dumped)
    assert ast == reloaded


def test_dumped_json_is_plain_json() -> None:
    rvt = rvt_bridge.get_rvt()
    variant = rvt.load(str(_FIXTURE_BINS["juggernaut"]))
    ast = EngineAst(triggers=extract_triggers(variant))
    data = json.loads(ast.model_dump_json())
    assert isinstance(data["triggers"], list)
    assert len(data["triggers"]) > 0


# -- nested tree reconstruction (EngineTrigger.body) ---------------------------------------------


def test_trigger_0_for_each_player_splices_both_inlined_subroutines_directly(juggernaut_triggers) -> None:
    # trigger 0: for each player do / two "Run Nested Trigger" calls, both to single-caller
    # subroutines (1: is_elite, 2: not is_elite) whose own first opcode is a Condition -- so both
    # splice in directly (no do-wrapper), matching Trigger::decompile()'s trigger_is_if_block
    # handling, not EngineDoBlock/EngineTriggerCallStatement.
    body = juggernaut_triggers[0].body
    assert len(body) == 2
    for stmt in body:
        assert isinstance(stmt, EngineIfStatement)


def test_spliced_if_from_trigger_1_matches_its_own_opcodes(juggernaut_triggers) -> None:
    t1 = juggernaut_triggers[1]
    stmt = juggernaut_triggers[0].body[0]
    assert [c.text for c in stmt.conditions] == [t1.opcodes[0].text]
    assert len(stmt.body) == 1
    assert isinstance(stmt.body[0], EngineActionStatement)
    assert stmt.body[0].opcode.text == t1.opcodes[1].text


def test_a_directly_inlined_subroutine_is_not_flagged_as_a_function(juggernaut_triggers) -> None:
    # Both subroutines trigger 0 calls have exactly one caller, so should be inlined, not rendered
    # as trigger_N() calls.
    assert juggernaut_triggers[1].is_function is False
    assert juggernaut_triggers[2].is_function is False


def test_no_real_fixture_produces_a_raw_fallback_statement(juggernaut_triggers) -> None:
    # EngineRawStatement only exists for a malformed opcode graph -- never expected against a real,
    # engine-loaded variant.
    def walk_stmts(stmts):
        for s in stmts:
            assert not isinstance(s, EngineRawStatement)
            if isinstance(s, (EngineIfStatement, EngineDoBlock, EngineInlineBlock, EngineForEachBlock)):
                walk_stmts(s.body)

    for t in juggernaut_triggers:
        walk_stmts(t.body)


# -- structural cross-check of the nested tree against the text grammar --------------------------


def _count_engine(stmts, counts):
    for s in stmts:
        counts[s.node] = counts.get(s.node, 0) + 1
        if isinstance(s, (EngineIfStatement, EngineDoBlock, EngineInlineBlock, EngineForEachBlock)):
            _count_engine(s.body, counts)


def _count_text(stmts, counts):
    for s in stmts:
        name = type(s).__name__
        counts[name] = counts.get(name, 0) + 1
        if isinstance(s, _text_nodes.IfStatement):
            _count_text(s.body, counts)
            for clause in s.altif_clauses:
                _count_text(clause.body, counts)
            if s.alt_body:
                _count_text(s.alt_body, counts)
        elif isinstance(s, (_text_nodes.DoBlock, _text_nodes.ForEach, _text_nodes.EventTrigger)):
            _count_text(s.body, counts)


def _counts_for(name: str) -> tuple[int, int, int, int]:
    rvt = rvt_bridge.get_rvt()
    variant = rvt.load(str(_FIXTURE_BINS[name]))
    triggers = extract_triggers(variant)
    roots = [t for t in triggers if t.is_function or t.entry_type != "subroutine"]
    engine_counts: dict = {}
    top_level_for_each = sum(1 for t in roots if t.block_type != "normal")
    for t in roots:
        _count_engine(t.body, engine_counts)
    engine_ifs = engine_counts.get("if", 0)
    engine_for_each = engine_counts.get("for_each", 0) + top_level_for_each

    script = parse(_fixture_text(name))
    text_counts: dict = {}
    _count_text(script.body, text_counts)
    return engine_ifs, engine_for_each, text_counts.get("IfStatement", 0), text_counts.get("ForEach", 0)


def test_juggernaut_matches_exactly() -> None:
    engine_ifs, engine_for_each, text_ifs, text_for_each = _counts_for("juggernaut")
    assert engine_ifs == text_ifs
    assert engine_for_each == text_for_each


def test_infection_matches_exactly() -> None:
    engine_ifs, engine_for_each, text_ifs, text_for_each = _counts_for("infection")
    assert engine_ifs == text_ifs
    assert engine_for_each == text_for_each


def test_invasion_is_within_a_few_percent() -> None:
    # See _count_engine/_count_text -- expected to run slightly higher, not lower, due to
    # altif-chain collapsing that only the text grammar performs.
    engine_ifs, engine_for_each, text_ifs, text_for_each = _counts_for("invasion")
    assert engine_ifs >= text_ifs
    assert engine_for_each >= text_for_each
    assert (engine_ifs - text_ifs) / text_ifs < 0.05
    assert (engine_for_each - text_for_each) / text_for_each < 0.05


# -- is_function computation ------------------------------------------------------------------


def test_no_real_fixture_has_a_multiply_called_subroutine() -> None:
    rvt = rvt_bridge.get_rvt()
    for name in ["juggernaut", "infection", "invasion"]:
        variant = rvt.load(str(_FIXTURE_BINS[name]))
        triggers = extract_triggers(variant)
        assert not any(t.is_function and t.entry_type != "subroutine" for t in triggers)


def test_a_subroutine_called_from_two_places_becomes_a_function_and_is_not_inlined() -> None:
    rvt = rvt_bridge.get_rvt()
    variant = rvt.load(str(_FIXTURE_BINS["juggernaut"]))
    mp = variant.multiplayer

    run_nested = next(
        rvt.action_function(i) for i in range(rvt.action_function_count())
        if rvt.action_function(i).name == "Run Nested Trigger"
    )

    subroutine = mp.add_trigger()
    end_round = next(
        rvt.action_function(i) for i in range(rvt.action_function_count())
        if rvt.action_function(i).name == "End Round"
    )
    sub_action = rvt.Action()
    sub_action.function = end_round
    subroutine.add_opcode(sub_action)
    subroutine_index = mp.trigger_count - 1

    def _add_caller():
        caller = mp.add_trigger()
        call = rvt.Action()
        call.function = run_nested
        arg = run_nested.arguments[0].typeinfo.create()
        arg.value = subroutine_index
        call.add_argument(arg)
        caller.add_opcode(call)
        return mp.trigger_count - 1

    caller_a = _add_caller()
    caller_b = _add_caller()

    triggers = extract_triggers(variant)
    assert triggers[subroutine_index].is_function is True
    for caller_index in (caller_a, caller_b):
        body = triggers[caller_index].body
        assert len(body) == 1
        assert isinstance(body[0], EngineTriggerCallStatement)
        assert body[0].trigger_index == subroutine_index


# -- enriched argument details ------------------------------------------------------------------


def test_trigger_index_argument_has_index_ref(juggernaut_triggers) -> None:
    arg = juggernaut_triggers[0].opcodes[0].arguments[0]
    assert arg.argument_type == "TriggerArgument"
    assert arg.raw_value is None
    assert arg.index_ref.name == "Trigger"
    assert arg.index_ref.quirk == "reference"
    assert arg.index_ref.value == 1


def test_const_bool_argument_has_raw_value(juggernaut_triggers) -> None:
    found = [a for op in juggernaut_triggers[10].opcodes for a in op.arguments if a.argument_type == "ConstBoolArgument"]
    assert found
    assert found[0].raw_value in (True, False)


def test_vector3_argument_has_vector_tuple(juggernaut_triggers) -> None:
    found = [a for op in juggernaut_triggers[10].opcodes for a in op.arguments if a.argument_type == "Vector3Argument"]
    assert found
    assert len(found[0].vector) == 3


def test_player_traits_argument_resolves_a_name(juggernaut_triggers) -> None:
    found = [a for op in juggernaut_triggers[14].opcodes for a in op.arguments if a.argument_type == "PlayerTraitsArgument"]
    assert found
    assert found[0].resolved_name == "Juggernaut Traits"


def test_waypoint_icon_argument_has_nested_engine_argument(juggernaut_triggers) -> None:
    found = [a for op in juggernaut_triggers[14].opcodes for a in op.arguments if a.argument_type == "WaypointIconArgument"]
    assert found
    assert found[0].waypoint_icon.icon == 3
    assert found[0].waypoint_icon.number.is_variable is True


def test_format_string_argument_has_resolved_text_and_nested_token(juggernaut_triggers) -> None:
    found = [
        a for op in juggernaut_triggers[5].opcodes for a in op.arguments
        if a.argument_type == "FormatStringPersistentArgument"
    ]
    assert found
    details = found[0].format_string
    assert details.persistent is True
    assert "Kill the Juggernaut" in details.string_text
    assert details.token_count == 1
    assert details.tokens[0].type == "number"
    assert details.tokens[0].value.text == "game.score_to_win"


def test_argument_type_is_always_set_even_with_no_extra_structure(juggernaut_triggers) -> None:
    for op in juggernaut_triggers[1].opcodes:
        for arg in op.arguments:
            assert arg.argument_type


def test_megalo_scope_argument_inline_scope_reuses_the_nested_tree_builder() -> None:
    # Zero real-fixture usage (confirmed by an earlier built-in-gametype sweep in the prior
    # prototype this was ported from) -- tested by construction.
    rvt = rvt_bridge.get_rvt()
    variant = rvt.load(str(_FIXTURE_BINS["juggernaut"]))
    mp = variant.multiplayer
    inline_func = next(
        rvt.action_function(i) for i in range(rvt.action_function_count())
        if rvt.action_function(i).name == "Run Inline Nested Trigger"
    )
    end_round = next(
        rvt.action_function(i) for i in range(rvt.action_function_count())
        if rvt.action_function(i).name == "End Round"
    )

    outer = rvt.Action()
    outer.function = inline_func
    scope_arg = inline_func.arguments[0].typeinfo.create()
    inner = rvt.Action()
    inner.function = end_round
    scope_arg.data.add_opcode(inner)
    outer.add_argument(scope_arg)
    mp.trigger(0).add_opcode(outer)

    triggers = extract_triggers(variant)
    new_opcode = triggers[0].opcodes[-1]
    scope = new_opcode.arguments[0]
    assert scope.argument_type == "MegaloScopeArgument"
    assert len(scope.inline_scope) == 1
    assert isinstance(scope.inline_scope[0], EngineActionStatement)
    assert scope.inline_scope[0].opcode.function_name == "End Round"

    # And the same content should also appear, inlined, in EngineTrigger.body via EngineInlineBlock
    # (the "Run Inline Nested Trigger" case in _build_action_statements).
    new_statement = triggers[0].body[-1]
    assert isinstance(new_statement, EngineInlineBlock)
    assert new_statement.body[0].opcode.function_name == "End Round"
