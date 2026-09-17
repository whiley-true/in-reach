"""Coverage for :mod:`in_reach.app.rvt.megalo_compiler` -- both direct unit-level tests against
:func:`~in_reach.app.rvt.megalo_compiler.compile_script` and integration tests proving
:mod:`in_reach.app.rvt.compile` actually reaches for it (and correctly falls back to the native
compiler for anything outside its supported subset). See that module's own docstring for the full
design/rationale (PROMPT.md: "we want a fromm scratch compiler then").
"""
import json
import tempfile
from pathlib import Path

import pytest

from in_reach.app import new_project, project
from in_reach.app.rvt import compile as compile_module
from in_reach.app.rvt import megalo_compiler, rvt_bridge

_FIXTURES_DIR = Path(__file__).parent / "resources"
_JUGGERNAUT_BIN = _FIXTURES_DIR / "juggernaut" / "juggernaut.bin"
_NEEDS_NATIVE_RVT = pytest.mark.skipif(
    not (_JUGGERNAUT_BIN.is_file() and rvt_bridge.is_available()),
    reason="fixture .bin not present, or native _reachvarianttool extension not available on this platform",
)

pytestmark = _NEEDS_NATIVE_RVT


def _project(tmp_path: Path, *, source_variant: Path) -> tuple[Path, Path]:
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir(parents=True)
    folder, warning = new_project.create_gametype_project(project_dir, "Compiler Test", source_variant=source_variant)
    assert warning is None
    return project_dir, folder


@pytest.fixture
def juggernaut():
    rvt = rvt_bridge.get_rvt()
    return rvt, rvt.load(str(_JUGGERNAUT_BIN))


def _save_and_reload(rvt, variant):
    fd, path = tempfile.mkstemp(suffix=".bin")
    import os

    os.close(fd)
    try:
        variant.save(path)
        return rvt.load(path)
    finally:
        os.remove(path)


# -- direct unit tests against compile_script() ---------------------------------------------------


def test_compiles_assignment_condition_and_end_round_end_to_end(juggernaut) -> None:
    rvt, variant = juggernaut
    source = (
        "global.number[0] = 1\r\n"
        "if global.number[0] == 1 then\r\n"
        "   game.end_round()\r\n"
        "end\r\n"
    )

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    text = reloaded.decompile_script()
    assert "global.number[0] = 1" in text
    assert "if global.number[0] == 1 then" in text
    assert "game.end_round()" in text


def test_a_trailing_if_body_is_compiled_directly_with_no_wrapper_trigger(juggernaut) -> None:
    """An "if" that's the last statement in its own tail-positioned body -- here, the whole script,
    so trivially true -- compiles its condition and body directly into the enclosing trigger: no "Run
    Inline Nested Trigger" wrapper, no separate trigger at all, since nothing follows it in that
    trigger that would need protecting from its own conditions' gating (see megalo_compiler's own
    _compile_if docstring for why this is safe and deterministic, not a reversion to the original
    bInlineIfs bug)."""
    rvt, variant = juggernaut
    mp = variant.multiplayer
    source = "if global.number[0] == 1 then\r\n   game.end_round()\r\nend\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    # compile() clears and rebuilds the trigger list from scratch (see its own docstring) -- just
    # the one top-level trigger for the whole script, no wrapper, no separate trigger for the if's
    # body either.
    assert mp.trigger_count == 1
    top = mp.trigger(mp.trigger_count - 1)
    assert any(isinstance(top.opcode(i), rvt.Condition) for i in range(top.opcode_count))
    assert not any(
        top.opcode(i).argument_count and isinstance(top.opcode(i).argument(0), rvt.MegaloScopeArgument)
        for i in range(top.opcode_count)
        if isinstance(top.opcode(i), rvt.Action)
    )
    reloaded = _save_and_reload(rvt, variant)
    assert "if global.number[0] == 1 then" in reloaded.decompile_script()


def test_a_non_tail_if_body_is_still_built_inline_using_a_wrapper_trigger(juggernaut) -> None:
    """When something follows the "if" within the same body, its conditions can't be allowed to gate
    that trailing code too -- so it still needs the "Run Inline Nested Trigger" wrapper (embedded
    directly in the parent's own opcode list, zero extra trigger slots) to isolate it, same as before
    tail-position flattening (see test_a_trailing_if_body_is_compiled_directly_with_no_wrapper_
    trigger) was added."""
    rvt, variant = juggernaut
    mp = variant.multiplayer
    source = "if global.number[0] == 1 then\r\n   game.end_round()\r\nend\r\nglobal.number[1] = 2\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    assert mp.trigger_count == 1
    top = mp.trigger(mp.trigger_count - 1)
    wrapper_actions = [
        top.opcode(i)
        for i in range(top.opcode_count)
        if isinstance(top.opcode(i), rvt.Action)
        and top.opcode(i).argument_count
        and isinstance(top.opcode(i).argument(0), rvt.MegaloScopeArgument)
    ]
    assert len(wrapper_actions) == 1
    assert wrapper_actions[0].argument(0).data.opcode(0).decompile(variant) == "game.end_round()"
    reloaded = _save_and_reload(rvt, variant)
    text = reloaded.decompile_script()
    assert "if global.number[0] == 1 then" in text
    assert "global.number[1] = 2" in text


def test_not_equal_comparison_is_supported(juggernaut) -> None:
    rvt, variant = juggernaut
    source = "if global.number[0] != 0 then\r\n   game.end_round()\r\nend\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "if global.number[0] != 0 then" in reloaded.decompile_script()


def test_assigning_between_two_global_numbers_is_supported(juggernaut) -> None:
    rvt, variant = juggernaut
    source = "global.number[1] = global.number[0]\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "global.number[1] = global.number[0]" in reloaded.decompile_script()


@pytest.mark.parametrize("op", ["+=", "-=", "*=", "/=", "%="])
def test_compound_assignment_operators_are_supported(juggernaut, op: str) -> None:
    rvt, variant = juggernaut
    source = f"global.number[0] {op} 3\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert f"global.number[0] {op} 3" in reloaded.decompile_script()


@pytest.mark.parametrize("op", ["<", ">", "<=", ">="])
def test_ordering_comparisons_are_supported(juggernaut, op: str) -> None:
    rvt, variant = juggernaut
    source = f"if global.number[0] {op} 5 then\r\n   game.end_round()\r\nend\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert f"if global.number[0] {op} 5 then" in reloaded.decompile_script()


def test_or_chained_conditions_share_one_or_group(juggernaut) -> None:
    rvt, variant = juggernaut
    mp = variant.multiplayer
    source = "if global.number[0] == 1 or global.number[0] == 2 then\r\n   game.end_round()\r\nend\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    top = mp.trigger(mp.trigger_count - 1)  # the if's body is inline now -- no separate trigger for it
    conditions = [top.opcode(i) for i in range(top.opcode_count) if isinstance(top.opcode(i), rvt.Condition)]
    assert len(conditions) == 2
    assert conditions[0].or_group == conditions[1].or_group

    reloaded = _save_and_reload(rvt, variant)
    text = reloaded.decompile_script()
    assert "global.number[0] == 1 or global.number[0] == 2" in text


def test_and_conjuncts_get_distinct_or_groups(juggernaut) -> None:
    rvt, variant = juggernaut
    mp = variant.multiplayer
    source = "if global.number[0] == 1 and global.number[1] == 2 then\r\n   game.end_round()\r\nend\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    top = mp.trigger(mp.trigger_count - 1)  # the if's body is inline -- no separate trigger for it
    conditions = [top.opcode(i) for i in range(top.opcode_count) if isinstance(top.opcode(i), rvt.Condition)]
    assert len(conditions) == 2
    assert conditions[0].or_group != conditions[1].or_group


def test_and_inside_or_condition_is_supported(juggernaut) -> None:
    """``a and b or c`` == ``(a and b) or c`` (that's how the grammar's own precedence parses it) --
    a real case confirmed in RCC Onslaught v13.bin. The engine's own flat or_group model can't
    express this directly (AND across groups, OR within one), so this needs real CNF distribution:
    ``(a and b) or c`` == ``(a or c) and (b or c)`` -- 2 groups, {a,c} and {b,c}, not the 2 groups
    {a},{b},{c} a naive "and gets its own group, or shares one" reading might produce instead."""
    rvt, variant = juggernaut
    mp = variant.multiplayer
    source = (
        "if global.number[0] == 1 and global.number[1] == 2 or global.number[0] == 3 then\r\n"
        "   game.end_round()\r\n"
        "end\r\n"
    )

    megalo_compiler.compile_script(rvt, variant, source)

    top = mp.trigger(mp.trigger_count - 1)  # the if's body is inline -- no separate trigger for it
    conditions = [top.opcode(i) for i in range(top.opcode_count) if isinstance(top.opcode(i), rvt.Condition)]
    assert len(conditions) == 4
    groups = {}
    for c in conditions:
        groups.setdefault(c.or_group, []).append(c.decompile(variant))
    assert len(groups) == 2
    (group_a, group_b) = sorted(groups.values(), key=len)
    assert len(group_a) == 2 and len(group_b) == 2
    assert "global.number[0] == 3" in group_a and "global.number[0] == 3" in group_b

    # Not asserting the round-tripped text matches the original source exactly: the decompiler
    # reconstructs *some* textually-equivalent CNF/DNF reading of the same flat or_group structure,
    # not necessarily the one the source happened to be written in -- the or_group/count assertions
    # above already verify the structure itself is correct.
    reloaded = _save_and_reload(rvt, variant)
    assert "game.end_round()" in reloaded.decompile_script()


# -- generalized variable resolution (player/object/team/temporaries/self/team[N]/null constants) --


def test_current_player_scoped_number_is_supported(juggernaut) -> None:
    rvt, variant = juggernaut
    source = "current_player.number[0] = 1\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "current_player.number[0] = 1" in reloaded.decompile_script()


def test_team_constant_index_is_supported(juggernaut) -> None:
    rvt, variant = juggernaut
    source = "current_player.team = team[0]\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "current_player.team = team[0]" in reloaded.decompile_script()


def test_null_player_constant_comparison_is_supported(juggernaut) -> None:
    rvt, variant = juggernaut
    source = "if global.player[0] == no_player then\r\n   game.end_round()\r\nend\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "if global.player[0] == no_player then" in reloaded.decompile_script()


def test_out_of_range_current_player_number_index_raises(juggernaut) -> None:
    rvt, variant = juggernaut
    with pytest.raises(megalo_compiler.UnsupportedConstruct):
        megalo_compiler.compile_script(rvt, variant, "current_player.number[8] = 1\r\n")


def test_property_chained_off_an_already_resolved_variable_is_supported_by_exact_match(juggernaut) -> None:
    """``global.player[0].biped`` -- confirmed directly (see megalo_compiler module docstring) that
    this can't be built via clone-and-retarget at all (the property's own ``.which`` value opaquely
    packs the owning slot too, no derivable formula), so it's matched by exact literal text against
    a real example already present in the variant's own script instead. juggernaut.bin's own real
    script uses exactly ``global.player[0].biped`` (global.object[]'s own natural index here is 1,
    not 0 -- object/player/team retargeting has the same limitation, see the module docstring, so
    this deliberately targets the template's own natural index rather than exercising that too)."""
    rvt, variant = juggernaut
    source = "global.object[1] = global.player[0].biped\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "global.object[1] = global.player[0].biped" in reloaded.decompile_script()


def test_property_chain_not_used_anywhere_in_the_variant_raises(juggernaut) -> None:
    rvt, variant = juggernaut
    with pytest.raises(megalo_compiler.UnsupportedConstruct):
        megalo_compiler.compile_script(rvt, variant, "global.object[1] = global.player[3].biped\r\n")


# -- retargeting object/player/team variables to an index other than their template's own ----------


def test_object_variable_can_be_retargeted_to_a_different_index(juggernaut) -> None:
    """Confirmed by reading the vendored engine source (see megalo_compiler module docstring's
    "Constructing variable references" section): object/player/team variables use ``.which``, not
    ``.index``, as their real pool slot -- offset from it by a fixed, per-type amount. This is the
    genuine fix (not a workaround) for what was originally reported as a flat "can't retarget
    object/player/team variables at all" limitation."""
    rvt, variant = juggernaut
    source = "global.object[0] = global.object[2]\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "global.object[0] = global.object[2]" in reloaded.decompile_script()


def test_player_variable_can_be_retargeted_to_a_different_index(juggernaut) -> None:
    rvt, variant = juggernaut
    source = "global.player[3] = global.player[1]\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "global.player[3] = global.player[1]" in reloaded.decompile_script()


# -- AND-chained / negated if-conditions -------------------------------------------------------


def test_and_chained_and_negated_conditions_are_supported(juggernaut) -> None:
    rvt, variant = juggernaut
    source = (
        "if global.number[0] == 1 and not current_player.is_elite() then\r\n"
        "   game.end_round()\r\n"
        "end\r\n"
    )

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    text = reloaded.decompile_script()
    assert "global.number[0] == 1 and not current_player.is_elite()" in text


# -- generic function-mapped action/condition dispatch -------------------------------------------


def test_generic_action_call_with_context_and_no_return_value_is_supported(juggernaut) -> None:
    rvt, variant = juggernaut
    source = "current_object.delete()\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "current_object.delete()" in reloaded.decompile_script()


def test_generic_action_call_with_a_return_value_assigned_is_supported(juggernaut) -> None:
    rvt, variant = juggernaut
    # index 0 specifically -- this "result" slot is a bare (unwrapped) PlayerVariable, one of the
    # argument classes confirmed unable to safely retarget to a different index (see megalo_compiler
    # module docstring's "Constructing variable references" -- _retarget()'s own verification would
    # correctly refuse index 1 here), so this exercises the same real template's own natural index.
    source = "global.player[0] = current_object.get_carrier()\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "global.player[0] = current_object.get_carrier()" in reloaded.decompile_script()


def test_generic_condition_call_used_as_an_if_condition_is_supported(juggernaut) -> None:
    rvt, variant = juggernaut
    source = "if current_object.is_of_type(plasma_cannon) then\r\n   game.end_round()\r\nend\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "if current_object.is_of_type(plasma_cannon) then" in reloaded.decompile_script()


def test_numeric_object_type_call_argument_is_supported(juggernaut) -> None:
    """Confirmed a real case in RCC Onslaught v13.bin: ``place_at_me(280, ...)`` -- some object
    types have no friendly name the decompiler knows, so the raw index is used directly instead."""
    rvt, variant = juggernaut
    source = "if current_object.is_of_type(280) then\r\n   game.end_round()\r\nend\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "if current_object.is_of_type(280) then" in reloaded.decompile_script()


@pytest.mark.parametrize("who", ["no_one", "everyone", "allies", "enemies"])
def test_player_set_argument_is_supported(juggernaut, who: str) -> None:
    """PlayerSetArgument (e.g. set_waypoint_visibility's own argument) has no .value at all -- it's
    a composite (set_type/player/add_or_remove), not a plain enum, confirmed a real crash against
    the generic brute-force enum fallback before this was added. Real usage confirmed in RCC
    Onslaught v13.bin is always one of these 4 bare-identifier forms."""
    rvt, variant = juggernaut
    source = f"current_object.set_waypoint_visibility({who})\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert f"current_object.set_waypoint_visibility({who})" in reloaded.decompile_script()


def test_player_set_argument_with_a_specific_player_is_supported(juggernaut) -> None:
    """PlayerSetType.specific_player decompiles as "mod_player, <player>, <0-or-1>" -- 3 call
    values, not 1 -- confirmed a real case in RCC Onslaught v13.bin (note "mod_player" is RVT's own
    decompiled keyword, not the official reference's "player")."""
    rvt, variant = juggernaut
    source = "current_object.set_waypoint_visibility(mod_player, current_player, 1)\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "current_object.set_waypoint_visibility(mod_player, current_player, 1)" in reloaded.decompile_script()


def test_player_set_argument_with_an_unknown_keyword_raises(juggernaut) -> None:
    rvt, variant = juggernaut
    with pytest.raises(megalo_compiler.UnsupportedConstruct):
        megalo_compiler.compile_script(
            rvt, variant, "current_object.set_waypoint_visibility(some_made_up_keyword)\r\n"
        )


def test_bare_call_with_no_context_is_supported(juggernaut) -> None:
    rvt, variant = juggernaut
    source = "send_incident(juggernaut_game_start, current_player, no_player)\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "send_incident(juggernaut_game_start, current_player, no_player)" in reloaded.decompile_script()


def test_property_get_is_supported(juggernaut) -> None:
    """"current_player.biped.health" looks like a plain property read but is really its own
    dedicated action ("Get Object Health", mapping.type == "property_get", confirmed a real case in
    RCC Onslaught v13.bin) -- not a stored variable at all. script_option[0] (not global.number[0])
    as the assignment target here -- juggernaut.bin's own script has no existing example of a bare
    (non-AnyVariable-wrapped) "number"-typeinfo global.number[] reference to source a template from,
    only script_option[]/an integer literal, see module docstring's "Constructing variable
    references" section."""
    rvt, variant = juggernaut
    source = "script_option[0] = current_player.biped.health\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "script_option[0] = current_player.biped.health" in reloaded.decompile_script()


def test_property_set_is_supported(juggernaut) -> None:
    """"current_player.biped.shields = 200" looks like a plain assignment but is really its own
    dedicated action ("Modify Object Shields", mapping.type == "property_set"), not the generic
    "Modify Variable" -- confirmed a real case in RCC Onslaught v13.bin."""
    rvt, variant = juggernaut
    source = "current_player.biped.shields = 200\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "current_player.biped.shields = 200" in reloaded.decompile_script()


def test_property_set_with_compound_operator_is_supported(juggernaut) -> None:
    rvt, variant = juggernaut
    source = "current_player.biped.shields += 50\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "current_player.biped.shields += 50" in reloaded.decompile_script()


def test_assigning_a_call_result_into_a_property_raises(juggernaut) -> None:
    rvt, variant = juggernaut
    with pytest.raises(megalo_compiler.UnsupportedConstruct):
        megalo_compiler.compile_script(
            rvt, variant, "current_player.biped.shields = current_object.get_carrier()\r\n"
        )


def test_format_string_argument_with_no_tokens_is_supported(juggernaut) -> None:
    """A format string (e.g. set_objective_text's own argument) is a real, persistent entry added
    to the variant's own string table (mp.script_strings.add_new()) -- confirmed constructible,
    unlike most argument types touched by this module which have no constructor at all."""
    rvt, variant = juggernaut
    source = 'current_player.set_objective_text("You are the Juggernaut")\r\n'

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert 'current_player.set_objective_text("You are the Juggernaut")' in reloaded.decompile_script()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("plain text", "plain text"),
        ("a\\rb\\nc", "a\rb\nc"),
        ("a\\\\b", "a\\b"),
        ('a\\"b', 'a"b'),
        ("a\\tb\\vb\\fb\\ab\\bb", "a\tb\vb\fb\ab\bb"),
        ("a\\x41b", "aAb"),  # \x41 = 'A'
        ("a\\u0041b", "aAb"),  # A = 'A'
        ("a\\qb", "aqb"),  # unrecognized escape: backslash dropped, letter kept
        ("trailing\\", "trailing\\"),  # dangling backslash at end-of-string: left as-is
        ("a\\xZZb", "a\\xZZb"),  # \x with non-hex digits: left as-is (both chars kept)
    ],
)
def test_unescape_string_literal_matches_the_native_compilers_own_escape_table(raw: str, expected: str) -> None:
    """Matches ``string_scanner::unescape()`` (``helpers/string_scanner.cpp``) exactly -- see
    megalo_compiler's own module docstring ("Fixed: format-string content was stored un-unescaped")
    for why this exists: megalo_ast's own StringLiteral.value is deliberately raw, unescaped text,
    but the real Megalo bytecode needs the interpreted bytes."""
    assert megalo_compiler._unescape_string_literal(raw) == expected


def test_format_string_argument_with_a_number_token_is_supported(juggernaut) -> None:
    """"...%n points to win." (a real case in RCC Onslaught v13.bin) embeds a replacement token --
    lives as separate metadata (token_count/token(i).type/.value) alongside the string's own literal
    text, not derived from parsing the text itself (confirmed directly: setting the string content
    alone doesn't auto-populate token_count). "game.score_to_win" itself is a game-state value, not
    a stored variable -- resolved the same way as current_player.biped.health elsewhere in this
    module, via the opaque literal-text match (a real example already exists in juggernaut.bin's own
    script: "game.score_to_win != 0")."""
    rvt, variant = juggernaut
    # Deliberately the literal 4 characters \, r, \, n (not an actual CR+LF) -- confirmed directly
    # that's how decompile_script() itself represents an embedded newline inside a quoted string
    # (matching this grammar's own "escapes NOT interpreted" string-literal semantics, see
    # nodes.py's StringLiteral docstring).
    source = (
        'current_player.set_objective_text("Kill the Juggernaut.\\r\\n%n points to win.", '
        "game.score_to_win)\r\n"
    )

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert (
        'current_player.set_objective_text("Kill the Juggernaut.\\r\\n%n points to win.", '
        "game.score_to_win)" in reloaded.decompile_script()
    )


def test_format_string_argument_with_two_tokens_is_supported(juggernaut) -> None:
    rvt, variant = juggernaut
    source = 'current_player.set_objective_text("%n and %n", global.number[0], global.number[1])\r\n'

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert (
        'current_player.set_objective_text("%n and %n", global.number[0], global.number[1])'
        in reloaded.decompile_script()
    )


def test_format_string_argument_with_an_unsupported_token_character_raises(juggernaut) -> None:
    rvt, variant = juggernaut
    with pytest.raises(megalo_compiler.UnsupportedConstruct):
        megalo_compiler.compile_script(
            rvt, variant, 'current_player.set_objective_text("%t wins", team[0])\r\n'
        )


def test_format_string_argument_with_too_few_token_values_raises(juggernaut) -> None:
    rvt, variant = juggernaut
    with pytest.raises(megalo_compiler.UnsupportedConstruct):
        megalo_compiler.compile_script(
            rvt, variant, 'current_player.set_objective_text("%n and %n", global.number[0])\r\n'
        )


def test_format_string_argument_reuses_an_existing_matching_string(juggernaut) -> None:
    """The string table has a fixed capacity (confirmed 112 entries) -- add_new()-ing a fresh entry
    for every format-string call, even one whose text already exists in the variant somewhere,
    would exhaust it needlessly (confirmed a real case recompiling RCC Onslaught v13.bin's own
    script completely unedited). "Kill the Juggernaut." is juggernaut.bin's own real, existing
    string (used without its own %n-token variant elsewhere in the same script)."""
    rvt, variant = juggernaut
    mp = variant.multiplayer
    source = (
        'current_player.set_objective_text("Kill the Juggernaut.")\r\n'
        'current_player.set_objective_text("Kill the Juggernaut.")\r\n'
    )

    megalo_compiler.compile_script(rvt, variant, source)

    top = mp.trigger(mp.trigger_count - 1)
    strings = [top.opcode(i).argument(1).string for i in range(top.opcode_count)]
    assert len(strings) == 2
    assert strings[0] is strings[1]


def test_forge_label_call_argument_by_string_name_is_supported(juggernaut) -> None:
    rvt, variant = juggernaut
    source = (
        'global.object[0] = global.object[0].place_at_me(particle_emitter_fire, "juggernaut", '
        "never_garbage_collect, 0, 0, 0, none)\r\n"
    )

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    text = reloaded.decompile_script()
    assert (
        'global.object[0] = global.object[0].place_at_me(particle_emitter_fire, "juggernaut", '
        "never_garbage_collect, 0, 0, 0, none)" in text
    )


def test_forge_label_call_argument_of_none_is_supported(juggernaut) -> None:
    rvt, variant = juggernaut
    source = (
        "global.object[0] = global.object[0].place_at_me(particle_emitter_fire, none, "
        "never_garbage_collect, 0, 0, 0, none)\r\n"
    )

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert (
        "global.object[0] = global.object[0].place_at_me(particle_emitter_fire, none, "
        "never_garbage_collect, 0, 0, 0, none)" in reloaded.decompile_script()
    )


def test_call_argument_order_override_is_supported(juggernaut) -> None:
    """"Get Random Object With Label"'s real call syntax -- "get_random_object(<label>,
    <exclude>)" -- puts its forge-label argument BEFORE its object argument, but its own native
    metadata `arguments` array order is the reverse (exclude, result, label) -- confirmed directly
    against a real opcode in RCC Onslaught v13.bin (raw argument order matches metadata order
    exactly, so the mismatch is specifically call-syntax-vs-metadata, not a raw-argument bug). See
    _CALL_ARGUMENT_ORDER_OVERRIDES."""
    rvt, variant = juggernaut
    source = 'global.object[0] = get_random_object("juggernaut", global.object[0])\r\n'

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert 'global.object[0] = get_random_object("juggernaut", global.object[0])' in reloaded.decompile_script()


def test_second_call_argument_order_override_is_supported(juggernaut) -> None:
    """"Play Sound"'s own metadata order is [sound, immediate, who], but its real call syntax --
    "play_sound_for(<who>, <sound>, <immediate>)", confirmed a real case in RCC Onslaught v13.bin --
    puts "who" first. A second, independent real case (not just the one _CALL_ARGUMENT_ORDER_
    OVERRIDES entry already had) confirming this is a genuine, if uncommon, pattern worth a lookup
    table rather than a one-off special case."""
    rvt, variant = juggernaut
    source = "game.play_sound_for(all_players, announce_slayer, true)\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "game.play_sound_for(all_players, announce_slayer, true)" in reloaded.decompile_script()


def test_unknown_enum_name_raises_cleanly_not_a_raw_type_error(juggernaut) -> None:
    """The generic brute-force enum search (see _build_enum_arg) tries increasing integer values
    until decompile() confirms a text match or the family's own range is exhausted -- confirmed a
    real crash before this was guarded: SoundArgument.value's own setter raises TypeError once the
    search runs past 127 (its real underlying type is a signed 8-bit int, confirmed in the vendored
    engine source), not just .decompile() failing once out of range as every other enum family does.
    An unrecognized sound name -- one that doesn't exist anywhere in the family's real range -- must
    still raise UnsupportedConstruct, not propagate that raw TypeError."""
    rvt, variant = juggernaut
    with pytest.raises(megalo_compiler.UnsupportedConstruct):
        megalo_compiler.compile_script(
            rvt, variant, "game.play_sound_for(all_players, not_a_real_sound_name, true)\r\n"
        )


def test_function_overload_disambiguated_by_biped_context_and_two_args(juggernaut) -> None:
    """"add_weapon" is genuinely shared by two different real functions -- "Add Weapon to Player"
    (1 non-context argument, player context) and "Add Weapon To Biped" (2, object context) --
    confirmed a real case in RCC Onslaught v13.bin: matching by name alone, first-found, silently
    picked the wrong one (its own argument's typeinfo didn't even match the call's own context
    shape). See _find_function's own call_arg_count disambiguation."""
    rvt, variant = juggernaut
    source = "current_player.biped.add_weapon(dmr, force)\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "current_player.biped.add_weapon(dmr, force)" in reloaded.decompile_script()


def test_function_overload_disambiguated_by_player_context_and_one_arg(juggernaut) -> None:
    """The other half of the same overload pair -- "Add Weapon to Player", 1 non-context argument,
    still resolves correctly (not broken by adding disambiguation for the 2-argument case)."""
    rvt, variant = juggernaut
    source = "current_player.add_weapon(global.object[0])\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "current_player.add_weapon(global.object[0])" in reloaded.decompile_script()


def test_vector3_collapsed_call_argument_is_supported(juggernaut) -> None:
    """attach_to's 'offset' is a single Vector3 opcode argument written as three plain call-syntax
    values -- confirmed directly against Vector3Argument.x/y/z (module docstring's "Argument values
    that are themselves multi-value types" section)."""
    rvt, variant = juggernaut
    # current_object (a bare constant, no retarget needed) as the target -- attach_to's "subject"/
    # "target" argument class is a bare, unwrapped ObjectVariable, one of the classes confirmed
    # unable to safely retarget to a different index (see megalo_compiler module docstring's
    # "Constructing variable references").
    source = "global.object[0].attach_to(current_object, 0, 0, 5, absolute)\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "global.object[0].attach_to(current_object, 0, 0, 5, absolute)" in reloaded.decompile_script()


def test_shape_argument_sphere_is_supported(juggernaut) -> None:
    """A Shape (set_shape's own argument) is one opcode argument but a *variable* number of
    call-syntax values depending on its own first value -- confirmed against the official
    reference's "set_boundary" syntax and real set_shape(...) calls in RCC Onslaught v13.bin (see
    megalo_compiler module docstring's "Argument values that are themselves multi-value types"
    section). sphere takes just 1 more value (radius)."""
    rvt, variant = juggernaut
    source = "current_object.set_shape(sphere, 15)\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "current_object.set_shape(sphere, 15)" in reloaded.decompile_script()


def test_shape_argument_cylinder_is_supported(juggernaut) -> None:
    """cylinder takes 3 more values (radius, bottom, top) -- exercises the variable-arity dispatch
    differently than sphere's 1, both against the exact same Shape argument type."""
    rvt, variant = juggernaut
    source = "current_object.set_shape(cylinder, 360, 1000, 1000)\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "current_object.set_shape(cylinder, 360, 1000, 1000)" in reloaded.decompile_script()


def test_shape_argument_with_too_few_dimension_values_raises(juggernaut) -> None:
    rvt, variant = juggernaut
    with pytest.raises(megalo_compiler.UnsupportedConstruct):
        megalo_compiler.compile_script(rvt, variant, "current_object.set_shape(cylinder, 360, 1000)\r\n")


def test_shape_argument_with_unknown_shape_type_raises(juggernaut) -> None:
    rvt, variant = juggernaut
    with pytest.raises(megalo_compiler.UnsupportedConstruct):
        megalo_compiler.compile_script(rvt, variant, "current_object.set_shape(pyramid, 15)\r\n")


# -- for each --------------------------------------------------------------------------------------


def test_for_each_object_loop_is_supported(juggernaut) -> None:
    rvt, variant = juggernaut
    source = "for each object do\r\n   current_object.delete()\r\nend\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    text = reloaded.decompile_script()
    assert "for each object do" in text
    assert "current_object.delete()" in text


def test_for_each_player_loop_is_supported(juggernaut) -> None:
    rvt, variant = juggernaut
    source = "for each player do\r\n   current_player.number[0] = 1\r\nend\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    text = reloaded.decompile_script()
    assert "for each player do" in text
    assert "current_player.number[0] = 1" in text


def test_for_each_player_randomly_is_supported(juggernaut) -> None:
    rvt, variant = juggernaut
    source = "for each player randomly do\r\n   current_player.number[0] = 1\r\nend\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "for each player randomly do" in reloaded.decompile_script()


def test_for_each_object_with_int_label_is_supported(juggernaut) -> None:
    rvt, variant = juggernaut
    # juggernaut.bin's own label 0 -- named "juggernaut" -- see its own real usage decompiled
    # elsewhere in this file as 'for each object with label "juggernaut" do'.
    source = "for each object with label 0 do\r\n   current_object.delete()\r\nend\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    text = reloaded.decompile_script()
    assert 'for each object with label "juggernaut" do' in text
    assert "current_object.delete()" in text


def test_for_each_object_with_string_label_is_supported(juggernaut) -> None:
    rvt, variant = juggernaut
    source = 'for each object with label "juggernaut" do\r\n   current_object.delete()\r\nend\r\n'

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert 'for each object with label "juggernaut" do' in reloaded.decompile_script()


def test_for_each_object_with_out_of_range_label_index_raises(juggernaut) -> None:
    rvt, variant = juggernaut
    with pytest.raises(megalo_compiler.UnsupportedConstruct):
        megalo_compiler.compile_script(
            rvt, variant, "for each object with label 99 do\r\n   current_object.delete()\r\nend\r\n"
        )


def test_for_each_player_with_label_is_not_supported(juggernaut) -> None:
    rvt, variant = juggernaut
    with pytest.raises(megalo_compiler.UnsupportedConstruct):
        megalo_compiler.compile_script(
            rvt, variant, "for each player with label 0 do\r\n   current_player.number[0] = 1\r\nend\r\n"
        )


# -- scan-copy isolation (see megalo_compiler's own "Fixed: an intermittent native crash" section) --


def test_compiler_scans_templates_from_a_separate_copy_not_the_target_variant(juggernaut) -> None:
    """``_Compiler._scan_copy()`` must return a genuinely different ``GameVariant`` object than the
    one being compiled into -- see megalo_compiler's own module docstring for why: clear_triggers()
    later destroys triggers on the target variant, and _scan_templates() must never have exposed
    those exact objects to Python (via a reference_internal binding) for that to be safe. A future
    "simplification" back to scanning `variant` directly would silently reintroduce a real,
    previously-confirmed intermittent native crash -- this test exists to catch exactly that."""
    rvt, variant = juggernaut
    scan_variant, scan_mp = megalo_compiler._Compiler._scan_copy(rvt, variant)
    assert scan_variant is not variant
    assert scan_mp is not variant.multiplayer


# -- declare (validated, no-op) --------------------------------------------------------------------


def test_declare_is_accepted_as_a_no_op(juggernaut) -> None:
    rvt, variant = juggernaut
    mp = variant.multiplayer
    source = "declare global.number[0] with network priority local\r\nglobal.number[0] = 1\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    # compile() clears and rebuilds the variant's own trigger list from scratch (see its own
    # docstring) -- juggernaut.bin's own pre-existing 25 triggers are gone, replaced by just the one
    # top-level trigger for the assignment -- declare itself emits nothing.
    assert mp.trigger_count == 1
    reloaded = _save_and_reload(rvt, variant)
    assert "global.number[0] = 1" in reloaded.decompile_script()


def test_declare_with_out_of_range_index_raises(juggernaut) -> None:
    rvt, variant = juggernaut
    with pytest.raises(megalo_compiler.UnsupportedConstruct):
        megalo_compiler.compile_script(rvt, variant, "declare global.number[99] with network priority local\r\n")


# -- do block ---------------------------------------------------------------------------------------


def test_do_block_is_supported(juggernaut) -> None:
    rvt, variant = juggernaut
    source = "do\r\n   global.number[0] = 1\r\n   game.end_round()\r\nend\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    text = reloaded.decompile_script()
    assert "global.number[0] = 1" in text
    assert "game.end_round()" in text


# -- on <event>: ---------------------------------------------------------------------------------


def test_on_init_event_trigger_is_supported(juggernaut) -> None:
    rvt, variant = juggernaut
    mp = variant.multiplayer
    source = "on init:\r\n   global.number[0] = 1\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    text = reloaded.decompile_script()
    assert "on init: do\r\n   global.number[0] = 1\r\nend" in text
    assert mp.entry_points.get_index_of_event(rvt.TriggerEntryType.on_init) != -1


def test_unsupported_event_name_raises(juggernaut) -> None:
    rvt, variant = juggernaut
    with pytest.raises(megalo_compiler.UnsupportedConstruct):
        megalo_compiler.compile_script(rvt, variant, "on some_made_up_event:\r\n   game.end_round()\r\n")


# -- named, top-level, multi-caller functions ------------------------------------------------------


def test_function_declaration_and_call_are_supported(juggernaut) -> None:
    rvt, variant = juggernaut
    source = (
        "function my_func()\r\n"
        "   game.end_round()\r\n"
        "end\r\n"
        "my_func()\r\n"
    )

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    text = reloaded.decompile_script()
    assert "game.end_round()" in text


def test_function_called_before_its_own_declaration_is_supported(juggernaut) -> None:
    """The two-pass allocation (see megalo_compiler's own module docstring) -- a call appearing
    textually before the function it names is declared must still resolve."""
    rvt, variant = juggernaut
    source = (
        "my_func()\r\n"
        "function my_func()\r\n"
        "   game.end_round()\r\n"
        "end\r\n"
    )

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "game.end_round()" in reloaded.decompile_script()


def test_one_function_calling_another_is_supported(juggernaut) -> None:
    rvt, variant = juggernaut
    source = (
        "function inner()\r\n"
        "   game.end_round()\r\n"
        "end\r\n"
        "function outer()\r\n"
        "   inner()\r\n"
        "end\r\n"
        "outer()\r\n"
    )

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "game.end_round()" in reloaded.decompile_script()


def test_calling_an_undeclared_function_raises(juggernaut) -> None:
    rvt, variant = juggernaut
    with pytest.raises(megalo_compiler.UnsupportedConstruct):
        megalo_compiler.compile_script(rvt, variant, "not_a_real_function_or_action()\r\n")


def test_running_out_of_triggers_raises_unsupported_construct_not_a_raw_runtime_error(juggernaut) -> None:
    """An if/do body is inline now (no trigger cost), but a for-each loop still needs a real,
    separate trigger (block_type only exists on one -- see megalo_compiler module docstring's
    "Constructing nested triggers" section), so a script with enough of them can still hit the
    engine's own Limits::max_triggers (320) even in a script compile() itself builds entirely from
    scratch (compile() clears any pre-existing triggers first -- see its own docstring -- so this
    exhausts the limit via the compiler's own construction, not by pre-seeding the variant).
    MultiplayerData.add_trigger() itself raises a plain RuntimeError at that point -- this compiler
    converts it to UnsupportedConstruct so the caller's own native-compiler fallback still kicks in
    cleanly."""
    rvt, variant = juggernaut
    # 1 (top-level trigger) + 320 for-each loops (each needing its own real trigger) == 321 > 320.
    source = "for each object do\r\n   current_object.delete()\r\nend\r\n" * 320
    with pytest.raises(megalo_compiler.UnsupportedConstruct):
        megalo_compiler.compile_script(rvt, variant, source)


def test_exceeding_the_action_cap_raises_unsupported_construct_not_a_broken_bin(juggernaut) -> None:
    """Unlike Limits::max_triggers (320, guarded directly at every add_trigger() call -- see the
    previous test), nothing in the native save() path itself checks Limits::max_actions (1024) or
    Limits::max_conditions (512) before writing -- confirmed a real, previously-blocking case: RCC
    Onslaught v13.bin's own full script compiles to 1026 actions once every if/do body is inlined,
    just past the cap, and the resulting variant used to save() without any error yet fail to load()
    back at all (its own read()-side "too_many_opcodes" check firing deterministically). compile()'s
    own post-build check (see _MAX_CONDITIONS/_MAX_ACTIONS's own docstring) catches this the same way
    _add_trigger() catches the trigger cap -- a clean UnsupportedConstruct, not a silently-broken
    build. A single trigger with enough trivial assignments (no for-each loops, so trigger_count
    barely moves) is enough to trip only the action cap, in isolation from the trigger one."""
    rvt, variant = juggernaut
    source = "global.number[0] = 1\r\n" * (megalo_compiler._MAX_ACTIONS + 1)
    with pytest.raises(megalo_compiler.UnsupportedConstruct, match="1024"):
        megalo_compiler.compile_script(rvt, variant, source)


def test_duplicate_function_declaration_raises(juggernaut) -> None:
    rvt, variant = juggernaut
    source = (
        "function my_func()\r\n   game.end_round()\r\nend\r\n"
        "function my_func()\r\n   game.end_round()\r\nend\r\n"
    )
    with pytest.raises(megalo_compiler.UnsupportedConstruct):
        megalo_compiler.compile_script(rvt, variant, source)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("declare foo = global.number[0]\r\n", id="declare"),
        pytest.param(
            "global.player[0] += current_object.get_carrier()\r\n", id="call result compound-assigned"
        ),
        pytest.param("global.number[99] = 1\r\n", id="out-of-range index"),
        pytest.param(
            "if global.number[0] == 1 then\r\n"
            "   game.end_round()\r\n"
            "elseif global.number[0] == 2 then\r\n"
            "   game.end_round()\r\n"
            "end\r\n",
            id="altif clause",
        ),
        pytest.param(
            # A second level of and/or nesting -- one level deep (the CNF distribution
            # _compile_condition() does) is supported, see test_and_inside_or_condition_is_supported.
            "if (global.number[0] == 1 or global.number[1] == 2) and global.number[0] == 3 or "
            "global.number[1] == 4 then\r\n"
            "   game.end_round()\r\n"
            "end\r\n",
            id="two levels of and/or nesting",
        ),
        pytest.param(
            # send_incident takes exactly 3 call arguments -- 2 given is a plain arity mismatch,
            # not the Vector3-collapsing case (see the dedicated Vector3 test for that).
            "send_incident(juggernaut_game_start, current_player)\r\n",
            id="call argument count mismatch",
        ),
        pytest.param("this is not valid megalo @#$%\r\n", id="parse error"),
    ],
)
def test_raises_unsupported_construct(juggernaut, source: str) -> None:
    rvt, variant = juggernaut
    with pytest.raises(megalo_compiler.UnsupportedConstruct):
        megalo_compiler.compile_script(rvt, variant, source)


def test_raises_when_the_variant_has_no_existing_templates_to_source_from() -> None:
    from in_reach.app.blank_variant import resolve_blank_variant

    rvt = rvt_bridge.get_rvt()
    variant = rvt.load(str(resolve_blank_variant(firefight=False)))
    with pytest.raises(megalo_compiler.UnsupportedConstruct):
        megalo_compiler.compile_script(rvt, variant, "global.number[0] = 1\r\n")


# -- integration through compile.run_compile() -----------------------------------------------------


def test_run_compile_uses_megalo_compiler_for_a_supported_edited_script(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, source_variant=_JUGGERNAUT_BIN)
    (folder / "script" / "output.txt").write_text(
        "global.number[0] = 1\r\nif global.number[0] == 1 then\r\n   game.end_round()\r\nend\r\n",
        encoding="utf-8",
    )

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is True, compile_module.format_build_result(result)
    rvt = rvt_bridge.get_rvt()
    compiled = rvt.load(str(result.output_path))
    text = compiled.decompile_script()
    assert "global.number[0] = 1" in text
    assert "if global.number[0] == 1 then" in text
    assert "game.end_round()" in text
    # Structural proof our own construction ran, not compile_script()'s own text parsing -- exactly
    # one trigger (the trailing "if" is in tail position -- the script's own last statement -- so it
    # compiles directly into the same top-level trigger, no wrapper needed; see megalo_compiler's own
    # _compile_if docstring). compile_script() clears and rebuilds the trigger list from scratch
    # (see its own docstring), so this is also proof the base variant's own pre-existing triggers
    # (juggernaut.bin ships with several) were replaced, not appended onto.
    assert compiled.multiplayer.trigger_count == 1


def test_run_compile_falls_back_to_native_for_an_unsupported_edited_script(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, source_variant=_JUGGERNAUT_BIN)
    # A player-scoped variable is outside megalo_compiler's supported subset -- global.number[N]
    # only, see its own module docstring -- but is perfectly valid, ordinary Megalo the native
    # compiler handles fine.
    (folder / "script" / "output.txt").write_text("current_player.number[0] = 1\r\n", encoding="utf-8")

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is True, compile_module.format_build_result(result)
    rvt = rvt_bridge.get_rvt()
    compiled = rvt.load(str(result.output_path))
    assert "current_player.number[0] = 1" in compiled.decompile_script()
