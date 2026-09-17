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


def test_the_if_body_is_built_as_a_real_subroutine_trigger_not_inline(juggernaut) -> None:
    """The whole point of building nested ifs this way (see megalo_compiler's own module docstring)
    -- a genuinely separate, entry_type=subroutine child Trigger, never delegated to the native
    compiler's own non-configurable inlining choice."""
    rvt, variant = juggernaut
    mp = variant.multiplayer
    before = mp.trigger_count
    source = "if global.number[0] == 1 then\r\n   game.end_round()\r\nend\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    # +2: one top-level trigger for the whole script, one subroutine trigger for the if's body.
    assert mp.trigger_count == before + 2
    child = mp.trigger(mp.trigger_count - 1)
    assert child.entry_type == rvt.TriggerEntryType.subroutine


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

    top = mp.trigger(mp.trigger_count - 2)  # the top-level trigger, just before the if-body subroutine
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

    top = mp.trigger(mp.trigger_count - 2)
    conditions = [top.opcode(i) for i in range(top.opcode_count) if isinstance(top.opcode(i), rvt.Condition)]
    assert len(conditions) == 2
    assert conditions[0].or_group != conditions[1].or_group


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


def test_bare_call_with_no_context_is_supported(juggernaut) -> None:
    rvt, variant = juggernaut
    source = "send_incident(juggernaut_game_start, current_player, no_player)\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "send_incident(juggernaut_game_start, current_player, no_player)" in reloaded.decompile_script()


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


# -- declare (validated, no-op) --------------------------------------------------------------------


def test_declare_is_accepted_as_a_no_op(juggernaut) -> None:
    rvt, variant = juggernaut
    mp = variant.multiplayer
    before_triggers = mp.trigger_count
    source = "declare global.number[0] with network priority local\r\nglobal.number[0] = 1\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    # +1: only the one top-level trigger for the assignment -- declare itself emits nothing.
    assert mp.trigger_count == before_triggers + 1
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
            "if global.number[0] == 1 and global.number[1] == 2 or global.number[0] == 3 then\r\n"
            "   game.end_round()\r\n"
            "end\r\n",
            id="and nested inside or",
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
    # Structural proof our own construction ran, not compile_script()'s own text parsing -- a
    # subroutine Trigger for the if's body, built the same deterministic way regardless of caller
    # count (see megalo_compiler's own module docstring for why this specifically closes the
    # bInlineIfs gap).
    subroutine_triggers = [
        i
        for i in range(compiled.multiplayer.trigger_count)
        if compiled.multiplayer.trigger(i).entry_type == rvt.TriggerEntryType.subroutine
    ]
    assert subroutine_triggers


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
