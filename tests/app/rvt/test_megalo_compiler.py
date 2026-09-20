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


def test_an_if_with_a_genuinely_empty_body_compiles_to_nothing(juggernaut) -> None:
    """"if X then end" (no body statements at all) is a true no-op -- Megalo conditions have no side
    effect beyond gating, so there's nothing for it to do either way -- and this compiler skips it
    entirely rather than emitting the condition plus an empty wrapper. Also sidesteps a real,
    reproducible native crash found this session: an empty body compiled in non-tail position (via
    "Run Inline Nested Trigger") segfaults the native module during save() -- root cause not pinned
    down, but not relevant to why this is skipped (which is a correctness call, not a workaround)."""
    rvt, variant = juggernaut
    mp = variant.multiplayer
    source = "if global.number[0] == 1 then\r\nend\r\nglobal.number[1] = 2\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    top = mp.trigger(mp.trigger_count - 1)
    assert not any(isinstance(top.opcode(i), rvt.Condition) for i in range(top.opcode_count))
    reloaded = _save_and_reload(rvt, variant)
    text = reloaded.decompile_script()
    assert "global.number[1] = 2" in text
    assert "global.number[0] == 1" not in text


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
    that trailing code too -- so the conditions *and* the body go in a "Run Inline Nested Trigger"
    wrapper (embedded directly in the parent's own opcode list, zero extra trigger slots), same as
    before tail-position flattening (see test_a_trailing_if_body_is_compiled_directly_with_no_wrapper_
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
    # The condition is the wrapper's own first opcode, not the enclosing trigger's: a condition gates
    # everything after it in its block, so one left outside would gate `global.number[1] = 2` as well
    # (see test_megalo_if_gating.py).
    scope = wrapper_actions[0].argument(0).data
    assert isinstance(scope.opcode(0), rvt.Condition)
    assert scope.opcode(1).decompile(variant) == "game.end_round()"
    assert not any(isinstance(top.opcode(i), rvt.Condition) for i in range(top.opcode_count))
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
    """``a and b or c`` is ``a and (b or c)`` -- in Megalo ``or`` binds *tighter* than ``and`` (the
    opposite of most languages), because that's simply how the engine stores a condition list: ``or``
    puts a condition in the previous one's ``or_group``, ``and`` starts a new group. Confirmed by
    compiling this same text with the native compiler and reading each condition's ``or_group``
    (0, 1, 1) -- see ``test_megalo_condition_groups.py``, which checks in-house against native
    directly. Read the other way, as ``(a and b) or c``, it would need CNF distribution -- four
    conditions, ``(a or c) and (b or c)`` -- and would also mean something different (this compiler
    used to do exactly that, silently changing a real script's logic *and* its size)."""
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
    assert len(conditions) == 3  # no distribution: `or` just shares the previous condition's group
    groups = {}
    for c in conditions:
        groups.setdefault(c.or_group, []).append(c.decompile(variant))
    assert len(groups) == 2
    (group_a, group_b) = sorted(groups.values(), key=len)
    assert group_a == ["global.number[0] == 1"]
    assert group_b == ["global.number[1] == 2", "global.number[0] == 3"]

    # And it reads back as the very text it was written as, since decompiling a condition list is
    # exactly this flat `and`/`or` chain.
    reloaded = _save_and_reload(rvt, variant)
    assert "if global.number[0] == 1 and global.number[1] == 2 or global.number[0] == 3 then" in reloaded.decompile_script()


def test_a_parenthesized_or_group_inside_an_and_is_supported(juggernaut) -> None:
    """``(A or B) and C or D``. Native Megalo can't express parentheses in a condition at all (it
    rejects them), so this is an in-house extension -- and under Megalo's precedence (``or`` tighter
    than ``and``) it means ``(A or B) and (C or D)``: two groups, ``{A, B}`` and ``{C, D}``, no
    distribution needed. (Under the *other* precedence this compiler used to assume it was
    ``((A or B) and C) or D``, five conditions across ``{A, B, D}`` and ``{C, D}``.)"""
    rvt, variant = juggernaut
    mp = variant.multiplayer
    source = (
        "if (global.number[0] == 1 or global.number[1] == 2) and global.number[0] == 3 or "
        "global.number[1] == 4 then\r\n"
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
    assert sorted(groups.values()) == [
        ["global.number[0] == 1", "global.number[1] == 2"],
        ["global.number[0] == 3", "global.number[1] == 4"],
    ]


def test_an_and_inside_a_parenthesized_or_needs_real_cnf_distribution(juggernaut) -> None:
    """``(a and b) or c`` -- parentheses are the only way to write it, since flat ``and``/``or`` can't
    say "and inside or". It genuinely needs distribution: ``(a or c) and (b or c)``, two groups
    ``{a, c}`` and ``{b, c}``."""
    rvt, variant = juggernaut
    mp = variant.multiplayer
    source = (
        "if (global.number[0] == 1 and global.number[1] == 2) or global.number[0] == 3 then\r\n"
        "   game.end_round()\r\n"
        "end\r\n"
    )

    megalo_compiler.compile_script(rvt, variant, source)

    top = mp.trigger(mp.trigger_count - 1)
    conditions = [top.opcode(i) for i in range(top.opcode_count) if isinstance(top.opcode(i), rvt.Condition)]
    groups = {}
    for c in conditions:
        groups.setdefault(c.or_group, []).append(c.decompile(variant))
    assert sorted(groups.values()) == [
        ["global.number[0] == 1", "global.number[0] == 3"],
        ["global.number[1] == 2", "global.number[0] == 3"],
    ]


def test_not_wrapping_a_compound_condition_pushes_the_negation_inward(juggernaut) -> None:
    """``not (A or B) and C`` -- a leading ``not`` wrapping a parenthesized compound expression,
    not just a single comparison/call -- must be pushed inward via De Morgan
    (``NOT(A or B) == NOT(A) and NOT(B)``) before CNF conversion, giving 3 independent AND-groups
    (``NOT(A)``, ``NOT(B)``, ``C``), each a single term with no ``or`` at all -- not, as an earlier
    version of this compiler's own ``_to_cnf_clauses`` briefly mis-implemented it (re-negating the
    already-``not``-wrapped node instead of its inner operand, which cancelled back out to the
    un-negated ``(A or B) and C`` via double negation -- confirmed via a direct check of the actual
    compiled or_group/inverted structure, not just that no exception was raised, exactly the kind
    of silent-wrong-semantics bug that wouldn't show up as a test failure without checking the
    real opcode structure)."""
    rvt, variant = juggernaut
    mp = variant.multiplayer
    source = (
        "if not (global.number[0] == 1 or global.number[1] == 2) and global.number[0] == 3 then\r\n"
        "   game.end_round()\r\n"
        "end\r\n"
    )

    megalo_compiler.compile_script(rvt, variant, source)

    top = mp.trigger(mp.trigger_count - 1)
    conditions = [top.opcode(i) for i in range(top.opcode_count) if isinstance(top.opcode(i), rvt.Condition)]
    assert len(conditions) == 3
    groups = {}
    for c in conditions:
        groups.setdefault(c.or_group, []).append((c.decompile(variant), c.inverted))
    assert len(groups) == 3
    all_terms = [term for group in groups.values() for term in group]
    assert ("not global.number[0] == 1", True) in all_terms
    assert ("not global.number[1] == 2", True) in all_terms
    assert ("global.number[0] == 3", False) in all_terms

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


def test_plain_variable_property_is_preferred_over_a_dedicated_property_set_action(juggernaut) -> None:
    """Some properties (e.g. a player's own "score") are ALSO directly addressable as a plain
    Variable scope ("%w.score", has_which, no derivable formula -- the same opaque literal-text
    match _build_opaque_variable_arg already uses for "biped"/"team"), not exclusively through a
    dedicated property_set action. Real MCC-shipped built-in game/hopper variants are genuinely
    inconsistent about which encoding they use for the exact same-looking source text -- confirmed
    directly: juggernaut.bin's own real "global.player[2].score += script_option[0]" compiles as
    "Modify Score" (a real property_set action, primary_name "score", context typeinfo
    "_player_or_group"), while slayer_team_hotshot_054.bin's own real "global.player[0].score += 1"
    compiles as plain "Modify Variable" instead -- found via a full sweep of every real MCC-shipped
    built-in game/hopper variant (slayer_team_hotshot_054.bin's own case previously fell back
    entirely, since this compiler had no template to build "Modify Score"'s own "_player_or_group"-
    typed context argument from). juggernaut.bin's own script has no existing "_any_variable"-typed
    reference to "global.player[2].score" (only the "Modify Score" action's own "_player_or_group"-
    typed one) to demonstrate the preference through a fully natural round trip here -- this
    injects one directly (a control-flow proof: confirms _compile_assign tries and prefers the
    plain path once a matching template exists, not a claim that this specific donor value is
    semantically meaningful) and confirms both that "Modify Variable" (not "Modify Score") gets
    used AND that the resulting opcode still saves/reloads cleanly. The existing shields tests
    above are the control for the opposite case: juggernaut has no plain-Variable template for
    "current_player.biped.shields" either, so that probe still correctly falls through to
    property_set, unaffected by this preference."""
    rvt, variant = juggernaut
    compiler = megalo_compiler._Compiler(rvt, variant)
    donor = compiler._templates.variables[("_any_variable", "current_player")]
    compiler._templates.literal_variables[("_any_variable", "global.player[2].score")] = donor.clone()

    script = megalo_compiler.parse("global.player[2].score += 1\r\n")
    compiler.compile(script)

    mp = variant.multiplayer
    top = mp.trigger(mp.trigger_count - 1)
    actions = [top.opcode(i) for i in range(top.opcode_count) if isinstance(top.opcode(i), rvt.Action)]
    assert len(actions) == 1
    assert actions[0].function.name == "Modify Variable"

    reloaded = _save_and_reload(rvt, variant)
    assert reloaded is not None


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


def test_decompiled_key_does_not_crash_on_an_unset_composite_sub_fields_none_scope(juggernaut) -> None:
    """A MeterParametersArgument's own embedded numerator/denominator/timer sub-field starts with
    scope=None until populated (same "no constructor for an embedded Variable member" gap
    Variable.copy_from()'s own native docstring documents elsewhere) -- confirmed a real crash here,
    not hypothetical: found via a full sweep of every real MCC-shipped built-in game/hopper variant,
    7 of which use a real "Set Meter Parameters" call whose own unused sub-field(s)
    _scan_templates()'s own composite-argument walk still visits unconditionally, and
    _decompiled_key's own "is this a literal-scope scalar" check used to dereference
    inner.scope.format with no None guard."""
    rvt, variant = juggernaut
    function = megalo_compiler._find_function(rvt, name="Set Meter Parameters", condition=False)
    arg = function.arguments[1].typeinfo.create()
    assert arg.timer.scope is None
    assert megalo_compiler._decompiled_key(rvt, arg.timer, "whatever") == "whatever"


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


def test_scan_templates_finds_templates_inside_format_string_tokens(juggernaut) -> None:
    """A format string's own %n/%p token value(s) are otherwise invisible to _scan_templates()'s
    flat, top-level-arguments-only walk -- confirmed a real, previously-blocking case (found via a
    full sweep of every real MCC-shipped built-in game/hopper variant): a scalar reference used ONLY
    as a token's own value, never elsewhere in a script, had no template for the compiler to source
    a fresh use of it from at all. Verified directly here (not just "the sweep now finds fewer
    gaps"): compile a script whose only use of a scalar is as a %n token's own value, save/reload,
    then confirm _scan_templates() on the resulting variant actually finds it -- clear_triggers()'s
    own "replace the whole script" semantics (see compile()'s own docstring) mean this one statement
    really is the reloaded variant's *entire* script, so there's no other occurrence this could be
    sourced from by coincidence."""
    rvt, variant = juggernaut
    source = 'current_player.set_objective_text("%n", global.number[2])\r\n'

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    templates = megalo_compiler._scan_templates(rvt, reloaded, reloaded.multiplayer)
    assert (megalo_compiler._ANY_VARIABLE_TYPEINFO_NAME, "global.number[]") in templates.variables


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


def test_third_call_argument_order_override_is_supported(juggernaut) -> None:
    """"Set Object Progress Bar"'s own metadata order is [object(context), who(_player_set),
    timer(_object_timer_variable)], but its real call syntax -- "set_progress_bar(<timer>, <who>)",
    confirmed a real case found via a full sweep of every real MCC-shipped built-in game/hopper
    variant -- puts the timer value before "who". Without this override, the _player_set builder was
    handed the timer's own remaining call values too (["0", "no_one"]) and failed on the timer value
    not being a recognized player-set identifier."""
    rvt, variant = juggernaut
    source = "current_object.set_progress_bar(3, allies)\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "current_object.set_progress_bar(3, allies)" in reloaded.decompile_script()


def test_object_timer_variable_literal_is_supported(juggernaut) -> None:
    """``_object_timer_variable`` (e.g. "Set Object Progress Bar"'s own "timer" argument) is a
    composite, non-Variable type with no confirmed real example of anything but a bare literal-
    constant shape -- checked across every real set_progress_bar(...) call in every MCC-shipped
    built-in game/hopper variant, every one decompiles as a plain integer with base_scope/base_type
    fixed at global/scalar. Unlike most embedded-composite gaps this module works around,
    base_scope/base_type both have real setters, so a fresh typeinfo.create() is enough -- no
    clone-from-a-real-example template needed. See _build_object_timer_literal_arg."""
    rvt, variant = juggernaut
    source = "current_object.set_progress_bar(0, no_one)\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "current_object.set_progress_bar(0, no_one)" in reloaded.decompile_script()


def test_fireteam_list_argument_with_a_single_index_is_supported(juggernaut) -> None:
    """``_fireteam_list`` (e.g. "set_spawn_location_fireteams"'s own argument, confirmed real cases
    found via a full sweep of every real MCC-shipped built-in game/hopper variant) has a ``.value``
    field, but unlike a plain enum ordinal, it's a *bitmask* -- a bare call value ``N`` (a single
    fireteam index) needs ``.value = 1 << N``, not ``.value = N`` directly. See
    _build_fireteam_list_arg's own docstring."""
    rvt, variant = juggernaut
    source = "current_object.set_spawn_location_fireteams(0)\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "current_object.set_spawn_location_fireteams(0)" in reloaded.decompile_script()


def test_fireteam_list_argument_with_all_is_supported(juggernaut) -> None:
    """"all" (every fireteam) resolves via the same brute-force-and-compare-decompiled-text approach
    as any other named enum value, not the bit-shift math the bare-int case needs."""
    rvt, variant = juggernaut
    source = "current_object.set_spawn_location_fireteams(all)\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "current_object.set_spawn_location_fireteams(all)" in reloaded.decompile_script()


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


def test_waypoint_icon_argument_with_no_number_is_supported(juggernaut) -> None:
    """A WaypointIconArgument (set_waypoint_icon's own argument, found via a full sweep of every
    real MCC-shipped built-in game/hopper variant) is a composite type whose own "icon" field is a
    plain int, not an enum wrapper -- the generic _build_enum_arg brute force doesn't apply (no
    .value to set). See _build_waypoint_icon_argument's own docstring, including why RVT's own
    decompiled icon names are a completely unrelated vocabulary from the official reference's own
    hud_widget_icons.txt list."""
    rvt, variant = juggernaut
    source = "current_player.biped.set_waypoint_icon(vip)\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "current_player.biped.set_waypoint_icon(vip)" in reloaded.decompile_script()


def test_waypoint_icon_none_sentinel_is_supported(juggernaut) -> None:
    """"none" is icon value -1, outside the brute-force loop's own 0..N range -- .icon is a plain
    signed int8_t-width field, not a scoped enum with its own "no value" member the generic search
    would ever reach starting from 0."""
    rvt, variant = juggernaut
    source = "current_player.biped.set_waypoint_icon(none)\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "current_player.biped.set_waypoint_icon(none)" in reloaded.decompile_script()


def test_waypoint_icon_argument_with_a_number_is_supported(juggernaut) -> None:
    """Some icons (e.g. "territory_a") always need a .number value, and decompile a bare, unset
    .number as a trailing ", " -- confirmed directly (real case: icon 11 decompiles as
    "territory_a, " with .number left untouched, vs. icon 12 "territory_b" with no trailing comma
    at all) -- so matching against just the icon-name portion (before any comma) is required, not
    an exact full-text match. juggernaut.bin's own script has no existing 'number'-typed template
    for 'current_player.number[0]' specifically to source one from, so this still falls back here --
    but the failure message itself is this test's own regression target: it's now trying to resolve
    the *number* value specifically (proving the icon itself -- "territory_a" -- was already
    resolved correctly, past the comma-matching fix), not raising "unknown waypoint icon name"."""
    rvt, variant = juggernaut
    source = "current_player.biped.set_waypoint_icon(territory_a, current_player.number[0])\r\n"
    with pytest.raises(megalo_compiler.UnsupportedConstruct, match="current_player.number"):
        megalo_compiler.compile_script(rvt, variant, source)


def test_waypoint_icon_argument_with_a_literal_number_is_supported(juggernaut) -> None:
    """The full "icon needs a .number value" path, end to end, not just the icon-name resolution --
    a literal int works the same way it does for Shape's own dimensions (a real "number"-typed
    INT_LITERAL template already exists in juggernaut.bin's own script from other constructs)."""
    rvt, variant = juggernaut
    source = "current_object.set_waypoint_icon(territory_a, 7)\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "current_object.set_waypoint_icon(territory_a, 7)" in reloaded.decompile_script()


def test_scan_templates_finds_templates_inside_waypoint_icon_number_field(juggernaut) -> None:
    """A WaypointIconArgument's own "number" sub-field (only populated for icons that need one, e.g.
    "territory_a") is otherwise invisible to _scan_templates()'s flat, top-level-arguments-only walk
    -- confirmed a real, previously-blocking case (found via a full sweep of every real MCC-shipped
    built-in game/hopper variant): "current_object.spawn_sequence" is used as a waypoint icon's own
    number value in some scripts, never as a plain top-level argument anywhere else in those same
    scripts. Verified directly here (not just "the sweep now finds fewer gaps"), the same way as the
    analogous format-string-token test: compile a script whose only use of a scalar is as a waypoint
    icon's own number value, save/reload, then confirm _scan_templates() on the resulting variant
    actually finds it."""
    rvt, variant = juggernaut
    source = "current_object.set_waypoint_icon(territory_a, 7)\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    templates = megalo_compiler._scan_templates(rvt, reloaded, reloaded.multiplayer)
    assert ("number", "INT_LITERAL") in templates.variables


def test_format_string_timer_token_is_supported(juggernaut) -> None:
    """"%s" is a real format-string token placeholder mapping to OpcodeStringTokenType.timer, not
    just %n (number)/%p (player) -- confirmed a real case found via a full sweep of every real
    MCC-shipped built-in game/hopper variant ("New Weapon In %s" with a real hud_player.timer[N]
    token value). juggernaut.bin's own script has no existing '_any_variable'-typed reference to
    'player.timer[0]' to source a template from, so this still falls back here -- but the failure
    message itself is this test's own regression target: it's now trying to resolve the token's own
    value (proving "%s" is a recognized placeholder at all), not raising "format-string token '%s'
    is not supported yet"."""
    rvt, variant = juggernaut
    source = 'current_player.set_objective_text("%s", player.timer[0])\r\n'
    with pytest.raises(megalo_compiler.UnsupportedConstruct, match="player.timer"):
        megalo_compiler.compile_script(rvt, variant, source)


def test_object_player_variable_composite_context_is_supported(juggernaut) -> None:
    """"Set Shape Owner" (real primary_name "apply_shape_color_from_player_member") is the one
    confirmed real function whose own CONTEXT argument is a composite type
    (ObjectPlayerVariableArgument, typeinfo "_object_player_variable"): it packs both the usual
    receiver ("object", from the call's own dot-prefix) AND a "player_index" that's the call's own
    first (and only) positional value -- confirmed a real case found via a full sweep of every real
    MCC-shipped built-in game/hopper variant: "current_object.
    apply_shape_color_from_player_member(0)" decompiles its own context argument's whole text as
    just "0" (the player_index alone), with .object holding "current_object" separately, not
    rendered as part of the call syntax at all."""
    rvt, variant = juggernaut
    source = "current_object.apply_shape_color_from_player_member(0)\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "current_object.apply_shape_color_from_player_member(0)" in reloaded.decompile_script()


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


def test_function_overload_disambiguated_by_context_type_not_just_arity(juggernaut) -> None:
    """"set_primary_respawn_object" is shared by two real functions with the *same* non-context
    argument count (1) but different context typeinfo -- "...for Team" (team) vs "...for Player"
    (player) -- so call_arg_count alone can't disambiguate them. Confirmed a real case, found via a
    full sweep of every real MCC-shipped built-in game/hopper variant: 2nvasion_slayer_054.bin's own
    current_player.set_primary_respawn_object(global.object[2]) was silently resolving to the "for
    Team" overload (whichever the engine's own function table happened to list first) and then
    failing outright, since current_player isn't a team reference at all. See _find_function's own
    context_expr/can_build_context disambiguation tier."""
    rvt, variant = juggernaut
    source = "current_player.set_primary_respawn_object(global.object[0])\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "current_player.set_primary_respawn_object(global.object[0])" in reloaded.decompile_script()


def test_a_bare_call_discarding_an_out_variable_result_resolves_to_the_null_constant(juggernaut) -> None:
    """A bare statement call (no "X = ") to a function with an out-variable slot -- e.g. a real
    place_at_me()/"Create Object" call whose own result is deliberately unused -- is real, common
    Megalo, not a missing assignment: confirmed directly against a real compiled opcode (found via a
    full sweep of every real MCC-shipped built-in game/hopper variant) that the engine's own "result
    discarded" convention is the literal null constant matching the out-variable's own family
    ("no_object" for an object result), not an unset/omitted argument. See _DISCARD_CONSTANTS's own
    docstring.

    juggernaut.bin's own script has no existing 'object'-typed 'no_object' reference to source a
    template from (this compiler can only clone-and-retarget from a real example already present in
    the target script -- see module docstring), so this specific call still falls back here -- but
    the failure message itself is the proof the fix works: it's now trying to build 'no_object'
    specifically (this test's own regression target), not raising the old, unconditional "requires a
    result to assign" for every bare call regardless of whether the engine itself supports
    discarding one."""
    rvt, variant = juggernaut
    source = "current_player.biped.place_at_me(skull, none, never_garbage_collect, 0, 0, 5, none)\r\n"
    with pytest.raises(megalo_compiler.UnsupportedConstruct, match="no_object"):
        megalo_compiler.compile_script(rvt, variant, source)


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


def test_shape_argument_dimension_from_script_option_is_supported(juggernaut) -> None:
    """The last genuine gap from the 475-file MCC validation sweep, now closed: a Shape's own
    dimension argument (``number``-typeinfo) sourced from ``script_option[N]`` -- confirmed a real
    case: ctf_054.bin's own ``set_shape(cylinder, script_option[6], 10, 10)``. Every OTHER
    ``script_option[]`` reference in that same script is typed ``_any_variable`` (plain condition
    compares, see test_script_option_reference_is_supported above) or ``timer`` (a declare
    initializer) -- no ``number``-typeinfo one anywhere to clone-and-retarget from, even though the
    engine obviously supports it the same way for every other typeinfo. Unlike every other indexed
    pool reference this compiler resolves, this needs NO existing loaded example at all: fixed via
    a new native binding, ``Variable.set_scope_by_format()``, that looks up a concrete Variable
    type's own known ``"script_option[%i]"`` scope directly (see
    :meth:`_Compiler._build_script_option_arg`'s own docstring) rather than requiring a real,
    already-compiled example to clone. juggernaut.bin's own script has no ``set_shape(...,
    script_option[N], ...)`` of its own, but the engine's function table itself doesn't require one
    -- this compiles and round-trips cleanly regardless."""
    rvt, variant = juggernaut
    source = "current_object.set_shape(cylinder, script_option[6], 10, 10)\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "current_object.set_shape(cylinder, script_option[6], 10, 10)" in reloaded.decompile_script()


def test_shape_argument_dimension_accepts_a_variable_reference_not_just_a_literal(juggernaut) -> None:
    """A Shape's own dimension fields accept any ordinary variable/literal expression, not just a
    bare int literal -- confirmed a real case found via a full sweep of every real MCC-shipped
    built-in game/hopper variant: ctf_054.bin's own set_shape(cylinder, script_option[6], 10, 10)
    uses a scripted-option reference for its radius. juggernaut.bin's own script has no existing
    'number'-typed template for 'global.number[0]' specifically to source one from, so this still
    falls back here -- but the failure message itself is this test's own regression target: it's now
    trying to resolve a real variable reference (proving the generalization ran), not raising the
    old, unconditional "must be plain integer literals" for any non-literal dimension. See
    _build_shape_argument's own docstring."""
    rvt, variant = juggernaut
    source = "current_object.set_shape(sphere, global.number[0])\r\n"
    with pytest.raises(megalo_compiler.UnsupportedConstruct, match="global.number"):
        megalo_compiler.compile_script(rvt, variant, source)


def test_script_option_reference_is_supported(juggernaut) -> None:
    """``script_option[N]`` -- a scripted (Forge-configurable) option's own current value -- is a
    real, first-class indexed variable scope the engine supports (confirmed directly against a real
    compiled opcode: its own scope.format is "script_option[%i]", the same indexed clone-and-
    retarget shape every other pool reference uses, just with a different fixed prefix and pool size
    -- Megalo::Limits::max_script_options is 16). Found via a full sweep of every real MCC-shipped
    built-in game/hopper variant (ctf_054.bin's own "set_shape(cylinder, script_option[6], 10, 10)").

    juggernaut.bin's own script has no existing '_any_variable'-typed reference to 'script_option[]'
    to copy (only its own declare statements mention one, which this module's own declare handling
    is a pure no-op over, so nothing gets scanned from it) -- this used to fall back to the native
    compiler for exactly that reason. It no longer needs one: an ``_any_variable`` slot is just a
    wrapper, so the compiler builds the wrapped ``number`` reference directly (see
    ``_build_script_option_arg``)."""
    rvt, variant = juggernaut
    source = "global.number[0] = script_option[0]\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    assert "global.number[0] = script_option[0]" in reloaded.decompile_script()


def test_script_option_retarget_to_a_different_index_round_trips_correctly(juggernaut) -> None:
    """Regression test for a real native bug (found via bit-level ASAN/trace debugging of the 475-
    file MCC validation sweep's remaining round-trip failures): ``Variable::copy()`` (native) copies
    an ``indexed_data``-scoped Variable's ``.object`` pointer verbatim from whatever it was cloned
    from. ``.object`` is only ever (re)computed from ``.index`` during the native ``read()`` path --
    a clone made via ``_retarget()`` (set ``.index`` directly in Python, never round-tripped through
    ``read()``) kept the ORIGINAL template's stale ``.object``, and ``Variable::write()`` preferred
    that stale ``.object``'s own ``->index`` over the freshly retargeted ``.index``, so the SAVED file
    silently kept referencing the template's original slot instead of the one actually requested.
    juggernaut.bin's own script has a "declare global.timer[0] = script_option[2]" (see
    test_property_get_is_supported's own docstring for why juggernaut's only usable template for this
    shape is the assignment-target ("number"-typeinfo) one, not an ``_any_variable``-typed one) --
    retargeting to script_option[5] here (a different index than the template's own [2]) is exactly
    the clone-and-retarget shape the bug required. Fixed via a new native binding,
    ``Variable.clear_object()``, called from ``_retarget()`` right after setting ``.index``."""
    rvt, variant = juggernaut
    source = "script_option[5] = current_player.biped.health\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    text = reloaded.decompile_script()
    assert "script_option[5] = current_player.biped.health" in text
    assert "script_option[2] = current_player.biped.health" not in text


def test_any_variable_argument_from_a_raw_unwrapped_template_is_wrapped_before_use(juggernaut) -> None:
    """Regression test for the actual root cause of the cascading "Failed to parse game variant"
    round-trip failures found via the 475-file MCC validation sweep (distinct from, and far more
    serious than, the ``.object``-staleness value mismatch the previous test covers): confirmed via
    native bit-level tracing (comparing a save's own write-side opcode trace against the immediate
    reload's read-side trace, ordinally) that the actual desync originates at a "Modify Variable"
    action whose value ("b") operand ends up a bare, unwrapped ``Variable`` (e.g. a
    ``ScalarVariable``) instead of a proper ``AnyVariable`` wrapper.

    ``_scan_templates()`` deliberately registers some templates *raw* -- a ``_format_string``
    token's own value, or a ``_waypoint_icon``'s own ``.number`` sub-field, are genuinely just a bare
    ``Variable``, never wrapped in an ``AnyVariable`` to begin with -- under the very same
    ``("_any_variable", key)`` template-dict namespace that a genuinely ``_any_variable``-typed
    top-level slot (e.g. "Modify Variable"'s own "a"/"b" operands) also queries via
    ``_build_variable_arg``. ``Opcode.add_argument()`` (native) stores whatever concrete C++ type
    it's handed verbatim, with no check against the slot's own declared typeinfo -- so when the only
    available template for a shape happens to be one of these raw ones, the old code silently handed
    a bare Variable to a "_any_variable" slot. That argument's own polymorphic ``write()`` then skips
    the leading 3-bit type-tag ``AnyVariable::write()`` always emits, desyncing the bitstream for
    every opcode written after it -- with no crash and no ASan report (not memory corruption, just
    the wrong concrete C++ type in that slot).

    juggernaut.bin's own script has no existing ``_any_variable``-typed reference to
    ``script_option[]`` at all (only a "number"-typeinfo one, see test_property_get_is_supported's
    own docstring) -- this test injects a raw clone of that "number"-typeinfo template directly into
    the ``_any_variable`` family, simulating exactly what ``_scan_templates()`` would produce if the
    *only* real-world source for this shape were a format-string token/waypoint-icon field (the
    actual shape of every one of the sweep's 57 crashing files), and confirms building
    "global.number[0] = script_option[3]" (whose value slot is genuinely ``_any_variable``-typed)
    both succeeds AND round-trips correctly through a real save/reload -- proof the bitstream isn't
    desynced, not just that no exception was raised. Fixed via a new native binding,
    ``AnyVariable.wrap()``, called from ``_Compiler._ensure_any_variable_wrapper()`` for every
    ``_any_variable``-typed argument this compiler builds.
    """
    rvt, variant = juggernaut
    compiler = megalo_compiler._Compiler(rvt, variant)
    raw_template = compiler._templates.variables[("number", "script_option[]")]
    assert not hasattr(raw_template, "variable")
    compiler._templates.variables[("_any_variable", "script_option[]")] = raw_template.clone()

    script = megalo_compiler.parse("global.number[0] = script_option[3]\r\n")
    compiler.compile(script)

    reloaded = _save_and_reload(rvt, variant)
    assert "global.number[0] = script_option[3]" in reloaded.decompile_script()


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


# -- declare (emits no opcode; see test_variable_declarations.py for what it does write) ------------


def test_declare_emits_no_opcode(juggernaut) -> None:
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


def test_on_double_host_migration_event_trigger_is_supported(juggernaut) -> None:
    """"double host migration" (the second consecutive host migration in one match) has no
    ``TriggerEntryType`` member of its own -- confirmed directly against the vendored engine's own
    ``trigger.h`` (``entry_type::on_host_migration``'s own comment: "host migrations and double
    host migrations"): a trigger bound to either event carries the exact same ``entry_type``, told
    apart purely by which of the engine's own two separate ``TriggerEntryPoints`` index fields
    (``indices.hostMigrate`` vs. ``indices.doubleHostMigrate``) points at it. Found via a full
    sweep of every real MCC-shipped built-in game/hopper variant (a real case: race_054.bin's own
    "on double host migration:" trigger) -- previously fell back to the native compiler entirely
    since ``TriggerEntryType`` genuinely has no matching member to look up. Fixed via a dedicated
    native binding, ``bind_trigger_as_double_host_migration_handler()``, that sets
    ``indices.doubleHostMigrate`` directly rather than going through the generic (and, for this one
    event, structurally incapable) ``bind_trigger_as_event()`` path -- see
    ``_EVENT_ENTRY_TYPES``'s own docstring for why this event is handled separately from every
    other one in ``_compile_event_trigger``."""
    rvt, variant = juggernaut
    mp = variant.multiplayer
    source = "on double host migration:\r\n   global.number[0] = 1\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    text = reloaded.decompile_script()
    assert "on double host migration: do\r\n   global.number[0] = 1\r\nend" in text
    # A double-host-migration-bound trigger must NOT also register as the plain "host migration"
    # handler -- they're mutually exclusive index fields, not two names for the same slot.
    assert mp.entry_points.get_index_of_event(rvt.TriggerEntryType.on_host_migration) == -1


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
    # Each top-level for-each is one trigger of its own (nothing shares it, and there's no wrapper), so
    # 321 of them is one more than the engine allows.
    source = "for each object do\r\n   current_object.delete()\r\nend\r\n" * 321
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
            # "elseif" (unlike the real, working "altif" -- see test_altif_alt_chain_compiles_*
            # below) is a reserved word that doesn't actually parse, same as "else" -- see
            # megalo_ast's own module docstring for how that was confirmed against the native
            # text compiler directly. This is a parse error, not an UnsupportedConstruct from
            # this compiler's own altif/alt handling.
            "if global.number[0] == 1 then\r\n"
            "   game.end_round()\r\n"
            "elseif global.number[0] == 2 then\r\n"
            "   game.end_round()\r\n"
            "end\r\n",
            id="elseif is still a reserved, non-working keyword",
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


def test_if_alt_chain_compiles_with_a_negated_gate(juggernaut) -> None:
    """The simplest ``altif``/``alt`` case: a bare ``if ... alt ... end`` (real Megalo "else",
    see :class:`IfStatement`'s own docstring for why not the reserved ``else``). Compiled as two
    independent, self-contained synthetic ``if``s (see ``_compile_if``'s own docstring) -- the
    ``alt`` branch's own gate is just the negation of the main branch's condition, with no
    ``and`` needed (only one prior branch to exclude)."""
    rvt, variant = juggernaut
    source = (
        "if global.number[0] == 0 then\r\n"
        "   global.number[1] = 1\r\n"
        "alt\r\n"
        "   global.number[1] = 2\r\n"
        "end\r\n"
    )

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    text = reloaded.decompile_script()
    assert "if global.number[0] == 0 then" in text
    assert "global.number[1] = 1" in text
    assert "if not global.number[0] == 0 then" in text
    assert "global.number[1] = 2" in text


def test_altif_alt_chain_compiles_with_correct_negation_accumulated_gates(juggernaut) -> None:
    """A full ``if``/``altif``/``altif``/``alt`` chain -- each branch becomes its own independent,
    self-contained synthetic ``if`` (see ``_compile_if``'s own docstring), gated by its own
    condition AND'd with the negation of every earlier branch's own condition (``altif`` #2's own
    gate is ``NOT(main) AND NOT(altif #1) AND (altif #2's own condition)``, etc.) -- exactly
    reproducing ordinary if/elseif/else "exactly one branch runs" semantics using only real Megalo
    constructs (no native "else" support at all). Confirmed directly against the real decompiled
    structure after a save/reload, not just that no exception was raised -- the accumulated
    negation is exactly what makes this differ from 4 independent, unconditional ``if``s."""
    rvt, variant = juggernaut
    source = (
        "if global.number[0] == 0 then\r\n"
        "   global.number[1] = 1\r\n"
        "altif global.number[0] == 1 then\r\n"
        "   global.number[1] = 2\r\n"
        "altif global.number[0] == 2 then\r\n"
        "   global.number[1] = 3\r\n"
        "alt\r\n"
        "   global.number[1] = 4\r\n"
        "end\r\n"
    )

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    text = reloaded.decompile_script()
    assert "if global.number[0] == 0 then" in text
    assert "global.number[1] = 1" in text
    assert "if not global.number[0] == 0 and global.number[0] == 1 then" in text
    assert "global.number[1] = 2" in text
    assert "if not global.number[0] == 0 and not global.number[0] == 1 and global.number[0] == 2 then" in text
    assert "global.number[1] = 3" in text
    assert (
        "if not global.number[0] == 0 and not global.number[0] == 1 and not global.number[0] == 2 then"
        in text
    )
    assert "global.number[1] = 4" in text


def test_altif_with_an_empty_leading_branch_still_folds_its_condition_into_later_gates(
    juggernaut,
) -> None:
    """An empty branch body (e.g. the main ``if`` here) compiles no opcodes of its own at all
    (see ``_compile_if``'s own docstring for why, and the native crash this also sidesteps) --
    but its own condition must still be excluded by every later branch's own gate, purely as a
    fact about the source, independent of whether this compiler bothered emitting anything for
    it. Regression target: before this was handled, the accumulator was only updated alongside
    actually compiling a branch's body, which would have let a later branch's gate wrongly omit
    an earlier, empty branch's own exclusion."""
    rvt, variant = juggernaut
    source = (
        "if global.number[0] == 0 then\r\n"
        "altif global.number[0] == 1 then\r\n"
        "   global.number[1] = 2\r\n"
        "end\r\n"
    )

    megalo_compiler.compile_script(rvt, variant, source)

    reloaded = _save_and_reload(rvt, variant)
    text = reloaded.decompile_script()
    assert "if not global.number[0] == 0 and global.number[0] == 1 then" in text
    assert "global.number[1] = 2" in text


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


# -- shape dimension order ---------------------------------------------------------------------------
# The existing shape tests use equal top/bottom heights, which is how the two being swapped went unseen:
# a cylinder is (radius, top, bottom) and a box (radius, length, top, bottom), the order the engine's own
# decompiler prints them in.


@pytest.mark.parametrize(
    "shape",
    ["cylinder, 50, 20, 30", "cylinder, 360, 1000, 10", "box, 40, 50, 20, 30"],
    ids=["cylinder", "cylinder wide", "box"],
)
def test_a_shapes_dimensions_keep_their_order(juggernaut, shape: str) -> None:
    rvt, variant = juggernaut
    source = f"current_object.set_shape({shape})\r\n"

    megalo_compiler.compile_script(rvt, variant, source)

    assert f"current_object.set_shape({shape})" in _save_and_reload(rvt, variant).decompile_script()


def test_a_shape_compiles_to_what_the_native_compiler_produces(juggernaut) -> None:
    rvt, variant = juggernaut
    source = "current_object.set_shape(cylinder, 50, 20, 30)\r\ncurrent_object.set_shape(box, 40, 50, 20, 30)\r\n"
    native = rvt.load(str(_JUGGERNAUT_BIN))
    assert native.multiplayer.compile_script(source).success

    megalo_compiler.compile_script(rvt, variant, source)

    assert variant.decompile_script() == native.decompile_script()
