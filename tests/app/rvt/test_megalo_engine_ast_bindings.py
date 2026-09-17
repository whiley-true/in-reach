"""Coverage for the native ``_reachvarianttool`` binding surface -- the real, compiled Megalo
Trigger/Opcode/Condition/Action/OpcodeArgValue object graph
(``MultiplayerData.trigger()``/``trigger_count`` and everything reachable from there). Ported from
a prior prototype's own test suite
(``D:\\whileyRepos\\sort\\mega-ide\\tests\\test_megalo_engine_ast_bindings.py``, PROMPT.md: "we want
a fromm scratch compiler then") -- see :mod:`in_reach.app.rvt.megalo_ast.engine`'s own module
docstring for the full port note.

Spot-check values below are pinned to known content in the ``juggernaut`` fixture -- e.g. trigger 1
is the "if current_player.is_elite() then current_player.set_loadout_palette(elite_tier_1) end"
subroutine, called from trigger 0's "for each player do ... end" loop via two "Run Nested Trigger"
actions.

This module tests the native binding directly (not through
:func:`in_reach.app.rvt.megalo_ast.extract_triggers` -- see ``test_megalo_ast_engine.py`` for that
Python-side layer) so a native-binding regression shows up here specifically, independent of the
Python extraction/pydantic layer built on top of it. **This is also the direct evidence
:mod:`in_reach.app.rvt.megalo_compiler` relies on**: every construction primitive it uses
(``add_trigger()``, ``Condition()``/``Action()``, ``.function =``, ``add_argument()``,
``add_opcode()``) is exercised and confirmed to persist correctly through a real save/reload here,
in ``ConstructionTests``/``TriggerConstructionTests``.
"""
import os
import tempfile
from pathlib import Path

import pytest

from in_reach.app.rvt import rvt_bridge

_FIXTURES_DIR = Path(__file__).parent / "resources"
_FIXTURE_BINS = {
    "juggernaut": _FIXTURES_DIR / "juggernaut" / "juggernaut.bin",
    "infection": _FIXTURES_DIR / "infection" / "infection.bin",
    "invasion": _FIXTURES_DIR / "invasion" / "invasion.bin",
}

pytestmark = pytest.mark.skipif(
    not rvt_bridge.is_available(), reason="native _reachvarianttool extension not available on this platform"
)

_NEW_ENUM_NAMES = ["VariableType", "VariableScope", "OpcodeMappingType", "TriggerBlockType", "TriggerEntryType"]
_NEW_CLASS_NAMES = [
    "VariableScopeIndicatorValue", "OpcodeArgTypeinfo", "OpcodeArgBase", "OpcodeFuncToScriptMapping",
    "OpcodeBase", "OpcodeArgValue", "Variable", "ScalarVariable", "ObjectVariable", "PlayerVariable",
    "TeamVariable", "TimerVariable", "PlayerOrGroupVariable", "AnyVariable", "Opcode", "Condition",
    "Action", "CodeBlock", "Trigger",
]


def _save_and_reload(rvt, variant):
    fd, path = tempfile.mkstemp(suffix=".bin")
    os.close(fd)
    try:
        variant.save(path)
        return rvt.load(path)
    finally:
        os.remove(path)


def _find_action_function(rvt, name: str):
    for i in range(rvt.action_function_count()):
        f = rvt.action_function(i)
        if f.name == name:
            return f
    raise AssertionError(f"no ActionFunction named {name!r}")


def _find_condition_function(rvt, name: str):
    for i in range(rvt.condition_function_count()):
        f = rvt.condition_function(i)
        if f.name == name:
            return f
    raise AssertionError(f"no ConditionFunction named {name!r}")


# -- binding surface ----------------------------------------------------------------------------


@pytest.mark.parametrize("name", _NEW_ENUM_NAMES)
def test_every_new_enum_is_registered(name: str) -> None:
    rvt = rvt_bridge.get_rvt()
    assert hasattr(rvt, name), f"_reachvarianttool has no enum named {name!r}"


@pytest.mark.parametrize("name", _NEW_CLASS_NAMES)
def test_every_new_class_is_registered(name: str) -> None:
    rvt = rvt_bridge.get_rvt()
    assert hasattr(rvt, name), f"_reachvarianttool has no class named {name!r}"


def test_multiplayer_data_has_trigger_accessors() -> None:
    rvt = rvt_bridge.get_rvt()
    variant = rvt.load(str(_FIXTURE_BINS["juggernaut"]))
    mp = variant.multiplayer
    assert mp.trigger_count > 0
    assert isinstance(mp.trigger(0), rvt.Trigger)


def test_trigger_index_out_of_range_raises() -> None:
    rvt = rvt_bridge.get_rvt()
    variant = rvt.load(str(_FIXTURE_BINS["juggernaut"]))
    mp = variant.multiplayer
    with pytest.raises(IndexError):
        mp.trigger(mp.trigger_count)


# -- juggernaut.bin trigger graph spot checks -----------------------------------------------------


@pytest.fixture
def juggernaut():
    rvt = rvt_bridge.get_rvt()
    variant = rvt.load(str(_FIXTURE_BINS["juggernaut"]))
    return rvt, variant, variant.multiplayer


def test_trigger_0_is_a_for_each_player_loop_calling_two_subroutines(juggernaut) -> None:
    rvt, variant, mp = juggernaut
    t0 = mp.trigger(0)
    assert t0.block_type == rvt.TriggerBlockType.for_each_player
    assert t0.entry_type == rvt.TriggerEntryType.normal
    assert t0.opcode_count == 2
    for i in range(2):
        op = t0.opcode(i)
        assert isinstance(op, rvt.Action)
        assert op.function.mapping.type == rvt.OpcodeMappingType.none
        # "Run Nested Trigger"/"Run Inline Trigger" opcodes decompile to the literal "nop" in
        # isolation -- their real "for each ... do ... end" text only exists as a special case in
        # the full CodeBlock/Trigger decompile walk, not per-opcode.
        assert op.decompile(variant) == "nop"


def test_trigger_1_is_the_is_elite_subroutine(juggernaut) -> None:
    rvt, variant, mp = juggernaut
    t1 = mp.trigger(1)
    assert t1.block_type == rvt.TriggerBlockType.normal
    assert t1.entry_type == rvt.TriggerEntryType.subroutine
    assert t1.opcode_count == 2

    cond = t1.opcode(0)
    assert isinstance(cond, rvt.Condition)
    assert cond.inverted is False
    assert cond.decompile(variant) == "current_player.is_elite()"
    assert cond.function.name == "Species Is Elite"

    action = t1.opcode(1)
    assert isinstance(action, rvt.Action)
    assert action.decompile(variant) == "current_player.set_loadout_palette(elite_tier_1)"


def test_trigger_2_condition_is_inverted(juggernaut) -> None:
    # "if not current_player.is_elite() then ... end"
    rvt, variant, mp = juggernaut
    cond = mp.trigger(2).opcode(0)
    assert cond.inverted is True
    assert cond.decompile(variant) == "not current_player.is_elite()"


def test_compare_and_assign_mapping_types_decompile_to_operator_syntax(juggernaut) -> None:
    rvt, variant, mp = juggernaut
    # trigger 4: "if current_player.number[0] == 0 then ... current_player.number[0] = 1 end"
    t4 = mp.trigger(4)
    compare = t4.opcode(0)
    assert compare.function.mapping.type == rvt.OpcodeMappingType.compare
    assert compare.decompile(variant) == "current_player.number[0] == 0"

    assign = t4.opcode(4)
    assert assign.function.mapping.type == rvt.OpcodeMappingType.assign
    assert assign.decompile(variant) == "current_player.number[0] = 1"


def test_variable_argument_resolves_through_any_variable_wrapper(juggernaut) -> None:
    rvt, variant, mp = juggernaut
    # current_player.number[0] in trigger 4's Compare condition -- a real script argument is
    # almost always wrapped in AnyVariable/PlayerOrGroupVariable, not a bare Variable.
    arg = mp.trigger(4).opcode(0).argument(0)
    assert arg.decompile(variant) == "current_player.number[0]"
    assert not isinstance(arg, rvt.Variable)  # the wrapper itself isn't a Variable...
    resolved = arg.variable
    assert isinstance(resolved, rvt.Variable)  # ...but what it wraps is
    assert isinstance(resolved, rvt.ScalarVariable)
    assert resolved.index == 0
    assert resolved.scope.format == "%w.number[%i]"


def test_get_variable_type_works_without_unwrapping(juggernaut) -> None:
    rvt, variant, mp = juggernaut
    arg = mp.trigger(4).opcode(0).argument(0)
    assert arg.get_variable_type() == rvt.VariableType.scalar


def test_non_variable_argument_reports_not_a_variable(juggernaut) -> None:
    rvt, variant, mp = juggernaut
    # trigger 1's "elite_tier_1" loadout-palette argument is a bare enum-like identifier, not a
    # variable reference at all.
    arg = mp.trigger(1).opcode(1).argument(1)
    assert arg.decompile(variant) == "elite_tier_1"
    assert arg.get_variable_type() == rvt.VariableType.not_a_variable
    assert getattr(arg, "variable", None) is None


def test_or_group_and_action_index_on_a_condition(juggernaut) -> None:
    _rvt, _variant, mp = juggernaut
    cond = mp.trigger(1).opcode(0)
    assert cond.or_group == 0
    assert cond.action == 0  # gates the action at index 0 in this trigger's action list


def test_to_string_is_a_human_description_not_script_syntax(juggernaut) -> None:
    _rvt, variant, mp = juggernaut
    cond = mp.trigger(1).opcode(0)
    assert cond.to_string() == "current_player is an Elite."
    assert cond.to_string() != cond.decompile(variant)


def test_opcode_argument_out_of_range_raises(juggernaut) -> None:
    _rvt, _variant, mp = juggernaut
    op = mp.trigger(1).opcode(0)
    with pytest.raises(IndexError):
        op.argument(op.argument_count)


def test_codeblock_opcode_out_of_range_raises(juggernaut) -> None:
    _rvt, _variant, mp = juggernaut
    t1 = mp.trigger(1)
    with pytest.raises(IndexError):
        t1.opcode(t1.opcode_count)


def test_trigger_argument_value_is_the_referenced_triggers_index(juggernaut) -> None:
    # trigger 0's two "Run Nested Trigger" actions -- confirms .value resolves through
    # mp.trigger(value) to the actual target Trigger (matches decompile()'s "1"/"2" text).
    rvt, variant, mp = juggernaut
    t0 = mp.trigger(0)
    first = t0.opcode(0).argument(0)
    assert isinstance(first, rvt.TriggerArgument)
    assert first.value == 1
    assert first.decompile(variant) == str(first.value)
    assert type(mp.trigger(first.value)) is rvt.Trigger


# -- mutation of already-loaded opcodes ------------------------------------------------------------


def test_condition_inverted_mutation_persists_through_save_reload(juggernaut) -> None:
    # trigger 1: "if current_player.is_elite() then ..." (not inverted)
    rvt, variant, mp = juggernaut
    cond = mp.trigger(1).opcode(0)
    assert cond.inverted is False
    cond.inverted = True
    assert cond.decompile(variant) == "not current_player.is_elite()"

    reloaded = _save_and_reload(rvt, variant)
    text = reloaded.decompile_script()
    assert "if not current_player.is_elite() then" in text


def test_const_bool_argument_mutation_persists_through_save_reload(juggernaut) -> None:
    rvt, variant, mp = juggernaut
    # trigger 10 ("Remove Weapon From ..., false" -- "do not delete it")
    arg = mp.trigger(10).opcode(17).argument(2)
    assert isinstance(arg, rvt.ConstBoolArgument)
    assert arg.value is False
    arg.value = True
    assert arg.decompile(variant) == "true"

    reloaded = _save_and_reload(rvt, variant)
    reloaded_arg = reloaded.multiplayer.trigger(10).opcode(17).argument(2)
    assert reloaded_arg.value is True


# -- argument-type family spot checks --------------------------------------------------------------

_ALL_NEW_TYPE_NAMES = [
    "ConstBoolArgument", "ConstSInt8Argument", "TimerRateArgument", "FireteamListArgument",
    "IncidentArgument", "ObjectTypeArgument", "SoundArgument", "VariantStringIDArgument",
    "Vector3Argument", "IndexQuirk", "BaseIndexArgument", "TriggerArgument",
    "RequisitionPaletteArgument", "EnumArgument", "AddWeaponEnumArgument",
    "AttachPositionEnumArgument", "CHUDDestinationEnumArgument", "CompareOperatorEnumArgument",
    "DropWeaponEnumArgument", "GrenadeTypeEnumArgument", "MathOperatorEnumArgument",
    "PickupPriorityEnumArgument", "TeamAllianceStatusArgument", "WaypointPriorityEnumArgument",
    "WeaponSlotEnumArgument", "LoadoutPaletteArgument", "MappedControlArgument",
    "FlagsArgument", "CreateObjectFlagsArgument", "KillerTypeFlagsArgument",
    "PlayerReqPurchaseModesArgument", "IconArgument", "EngineIconArgument",
    "HUDWidgetIconArgument", "ForgeLabelArgument", "PlayerTraitsArgument", "WidgetArgument",
    "PlayerSetArgument", "PlayerSetType", "ShapeType", "ShapeArgument", "WaypointIconArgument",
    "MeterType", "MeterParametersArgument", "ObjectTimerVariableArgument",
    "ObjectPlayerVariableArgument",
]


@pytest.mark.parametrize("name", _ALL_NEW_TYPE_NAMES)
def test_every_new_type_is_registered(name: str) -> None:
    rvt = rvt_bridge.get_rvt()
    assert hasattr(rvt, name), f"_reachvarianttool has no type named {name!r}"


def _find_argument(class_name: str):
    rvt = rvt_bridge.get_rvt()
    wanted = getattr(rvt, class_name)
    for fixture_name in ["juggernaut", "infection", "invasion"]:
        variant = rvt.load(str(_FIXTURE_BINS[fixture_name]))
        mp = variant.multiplayer
        for i in range(mp.trigger_count):
            t = mp.trigger(i)
            for j in range(t.opcode_count):
                op = t.opcode(j)
                for k in range(op.argument_count):
                    arg = op.argument(k)
                    if type(arg) is wanted:
                        return rvt, variant, op, arg
    raise AssertionError(f"no real {class_name} found across juggernaut/infection/invasion")


def test_const_bool_argument() -> None:
    _rvt, variant, _op, arg = _find_argument("ConstBoolArgument")
    assert arg.value in (True, False)
    assert arg.decompile(variant) == ("true" if arg.value else "false")


def test_trigger_index_and_quirk() -> None:
    rvt, variant, _op, arg = _find_argument("TriggerArgument")
    assert arg.name == "Trigger"
    assert arg.quirk == rvt.IndexQuirk.reference
    assert str(arg.value) == arg.decompile(variant)


def test_compare_operator_enum_invert() -> None:
    _rvt, variant, _op, arg = _find_argument("CompareOperatorEnumArgument")
    before = arg.decompile(variant)
    arg.invert()
    after = arg.decompile(variant)
    assert before != after


def test_killer_type_flags() -> None:
    _rvt, variant, _op, arg = _find_argument("KillerTypeFlagsArgument")
    assert arg.value > 0
    assert "|" in arg.decompile(variant)


def test_engine_icon() -> None:
    _rvt, _variant, _op, arg = _find_argument("EngineIconArgument")
    assert arg.value >= 0


def test_widget_reference_resolves_to_the_real_widget() -> None:
    rvt, _variant, _op, arg = _find_argument("WidgetArgument")
    assert isinstance(arg.value, rvt.HUDWidgetDeclaration)


def test_shape_embeds_real_scalar_sub_arguments() -> None:
    rvt, variant, _op, arg = _find_argument("ShapeArgument")
    assert arg.shape_type in (rvt.ShapeType.sphere, rvt.ShapeType.cylinder, rvt.ShapeType.box)
    assert isinstance(arg.radius, rvt.ScalarVariable)
    # axis_count depends on shape_type (a sphere only has a radius; a cylinder/box have more) --
    # not a fixed 4, but axis(0) is always meaningful and always resolves into one of the 4 named
    # sub-arguments.
    assert arg.axis_count >= 1
    axis0_text = arg.axis(0).decompile(variant)
    named_texts = {
        arg.radius.decompile(variant), arg.length.decompile(variant),
        arg.top.decompile(variant), arg.bottom.decompile(variant),
    }
    assert axis0_text in named_texts


def test_player_set_embeds_a_real_player_variable() -> None:
    rvt, _variant, _op, arg = _find_argument("PlayerSetArgument")
    assert isinstance(arg.player, rvt.Variable)
    assert isinstance(arg.set_type, rvt.PlayerSetType)


def test_object_timer_variable_scope_and_type_are_real_enums() -> None:
    rvt, _variant, _op, arg = _find_argument("ObjectTimerVariableArgument")
    assert isinstance(arg.base_scope, rvt.VariableScope)
    assert isinstance(arg.base_type, rvt.VariableType)
    assert arg.is_none() == (arg.index == -1)


# -- constructing brand-new opcodes from nothing ---------------------------------------------------


def test_zero_argument_action_construction_persists_through_save_reload(juggernaut) -> None:
    rvt, variant, mp = juggernaut
    end_round = _find_action_function(rvt, "End Round")
    t = mp.trigger(0)
    before = t.opcode_count

    new_action = rvt.Action()
    new_action.function = end_round
    t.add_opcode(new_action)
    assert t.opcode_count == before + 1
    assert t.opcode(before).decompile(variant) == "game.end_round()"

    reloaded = _save_and_reload(rvt, variant)
    assert "game.end_round()" in reloaded.decompile_script()


def test_using_the_python_variable_after_add_opcode_raises(juggernaut) -> None:
    """add_opcode()/add_argument() transfer ownership away from the Python object (the C++
    CodeBlock/Opcode now owns and will delete it) -- pybind11's smart_holder marks the original
    Python handle "disowned" rather than leaving a dangling pointer. Always re-fetch through the
    owner (e.g. trigger.opcode(i)) after adding, never keep using the original reference."""
    rvt, variant, mp = juggernaut
    end_round = _find_action_function(rvt, "End Round")
    t = mp.trigger(0)
    new_action = rvt.Action()
    new_action.function = end_round
    t.add_opcode(new_action)
    with pytest.raises(ValueError):
        new_action.decompile(variant)


def test_argument_construction_via_typeinfo_create(juggernaut) -> None:
    rvt, variant, mp = juggernaut
    func = _find_action_function(rvt, "Debugging: Enable Tracing")
    t = mp.trigger(0)

    new_action = rvt.Action()
    new_action.function = func
    arg = func.arguments[0].typeinfo.create()
    assert isinstance(arg, rvt.ConstBoolArgument)
    arg.value = True
    new_action.add_argument(arg)
    t.add_opcode(new_action)

    new_op = t.opcode(t.opcode_count - 1)
    assert new_op.argument_count == 1
    assert new_op.decompile(variant) == "debug_set_tracing_enabled(true)"

    reloaded = _save_and_reload(rvt, variant)
    assert "debug_set_tracing_enabled(true)" in reloaded.decompile_script()


def test_condition_construction_gates_the_action_that_follows_it(juggernaut) -> None:
    """A new Condition's .action (which action it gates) is fully auto-computed by the engine from
    opcode position on save -- confirmed by testing, not assumed. or_group is the one field that IS
    the caller's responsibility -- it's never touched by the engine's own save-time regeneration."""
    rvt, variant, mp = juggernaut
    cond_func = _find_condition_function(rvt, "In Forge")
    action_func = _find_action_function(rvt, "End Round")
    t = mp.trigger(0)

    existing_or_groups = [
        t.opcode(i).or_group for i in range(t.opcode_count) if isinstance(t.opcode(i), rvt.Condition)
    ]
    next_or_group = (max(existing_or_groups) + 1) if existing_or_groups else 0

    new_cond = rvt.Condition()
    new_cond.function = cond_func
    new_cond.or_group = next_or_group
    t.add_opcode(new_cond)

    new_action = rvt.Action()
    new_action.function = action_func
    t.add_opcode(new_action)

    reloaded = _save_and_reload(rvt, variant)
    text = reloaded.decompile_script()
    assert "if game.is_in_forge() then" in text
    # the new action must appear directly inside the new condition's block, not floating loose
    idx = text.find("if game.is_in_forge() then")
    snippet = text[idx:idx + 200]
    assert "game.end_round()" in snippet


def test_clone_duplicates_an_existing_opcode(juggernaut) -> None:
    rvt, variant, mp = juggernaut
    original = mp.trigger(1).opcode(1)  # current_player.set_loadout_palette(elite_tier_1)
    assert original.decompile(variant) == "current_player.set_loadout_palette(elite_tier_1)"

    clone = original.clone()
    clone.argument(1).value = 5  # elite_tier_1 -> a different loadout palette index

    t = mp.trigger(1)
    before = t.opcode_count
    t.add_opcode(clone)
    assert t.opcode_count == before + 1
    # the clone is independent -- mutating it must not have changed the original
    assert mp.trigger(1).opcode(1).decompile(variant) == "current_player.set_loadout_palette(elite_tier_1)"
    # decompile() resolves the new raw index through the same name table as any loaded opcode --
    # not a raw number, confirming the mutated clone is a fully "real" argument, not a stub.
    assert t.opcode(before).decompile(variant) == "current_player.set_loadout_palette(spartan_tier_3)"


# -- OpcodeArgValueFormatString(Persistent) --------------------------------------------------------


def _find_format_string_argument(rvt, mp):
    for i in range(mp.trigger_count):
        t = mp.trigger(i)
        for j in range(t.opcode_count):
            op = t.opcode(j)
            for k in range(op.argument_count):
                arg = op.argument(k)
                if isinstance(arg, rvt.FormatStringArgument):
                    return op, arg
    raise AssertionError("no real FormatStringArgument found in juggernaut.bin")


def test_string_and_token_structure_matches_known_text(juggernaut) -> None:
    rvt, variant, mp = juggernaut
    op, arg = _find_format_string_argument(rvt, mp)
    assert op.function.name == "Set Objective Description for Player"
    assert arg.persistent is True
    assert arg.string is not None
    assert "Kill the Juggernaut." in arg.string.get_content(rvt.Language.english)
    assert arg.token_count == 1
    token = arg.token(0)
    assert token.type == rvt.OpcodeStringTokenType.number
    assert token.value is not None
    assert token.value.decompile(variant) == "game.score_to_win"


def test_token_out_of_range_raises(juggernaut) -> None:
    rvt, _variant, mp = juggernaut
    _op, arg = _find_format_string_argument(rvt, mp)
    with pytest.raises(IndexError):
        arg.token(arg.max_token_count)


def test_setting_a_token_value_transfers_ownership(juggernaut) -> None:
    rvt, variant, mp = juggernaut
    _op, arg = _find_format_string_argument(rvt, mp)
    token = arg.token(0)
    new_value = arg.token(0).value.clone()  # a fresh ScalarVariable-shaped clone, independent of the original
    token.value = new_value
    with pytest.raises(ValueError):
        new_value.decompile(variant)  # disowned, same as add_argument()/add_opcode()
    assert arg.token(0).value.decompile(variant) == "game.score_to_win"


# -- OpcodeArgValueMegaloScope ("Run Inline Nested Trigger") ---------------------------------------


def test_construct_inline_trigger_with_a_nested_action_persists_through_save_reload(juggernaut) -> None:
    """Confirmed via a full sweep of every built-in game/hopper variant in the prior prototype this
    was ported from that this feature is never actually used by any real, shipped gametype, so this
    is tested purely by construction rather than a real-fixture spot-check."""
    rvt, variant, mp = juggernaut
    inline_func = _find_action_function(rvt, "Run Inline Nested Trigger")
    end_round = _find_action_function(rvt, "End Round")

    t = mp.trigger(0)
    outer = rvt.Action()
    outer.function = inline_func
    scope_arg = inline_func.arguments[0].typeinfo.create()
    assert isinstance(scope_arg, rvt.MegaloScopeArgument)

    inner = rvt.Action()
    inner.function = end_round
    scope_arg.data.add_opcode(inner)
    assert scope_arg.data.opcode_count == 1

    outer.add_argument(scope_arg)
    t.add_opcode(outer)

    new_op = t.opcode(t.opcode_count - 1)
    # mapping.type is "none" for this action -- decompiles as the literal "nop" in isolation, same
    # documented behavior as "Run Nested Trigger".
    assert new_op.decompile(variant) == "nop"
    assert new_op.argument(0).data.opcode(0).decompile(variant) == "game.end_round()"

    reloaded = _save_and_reload(rvt, variant)
    r_trigger = reloaded.multiplayer.trigger(0)
    r_op = r_trigger.opcode(r_trigger.opcode_count - 1)
    r_arg = r_op.argument(0)
    assert isinstance(r_arg, rvt.MegaloScopeArgument)
    assert r_arg.data.opcode_count == 1
    assert r_arg.data.opcode(0).decompile(reloaded) == "game.end_round()"


# -- MultiplayerData.add_trigger()/bind_trigger_as_event() -----------------------------------------


def test_new_trigger_defaults_to_a_normal_always_ticking_trigger(juggernaut) -> None:
    rvt, _variant, mp = juggernaut
    before = mp.trigger_count
    t = mp.add_trigger()
    assert mp.trigger_count == before + 1
    assert t.block_type == rvt.TriggerBlockType.normal
    assert t.entry_type == rvt.TriggerEntryType.normal
    assert t.opcode_count == 0


def test_new_top_level_trigger_content_persists_and_runs_automatically(juggernaut) -> None:
    """A fresh trigger needs no explicit wiring to be a top-level, always-ticking trigger --
    confirmed by compiling real "on its own" top-level script text via compile_script() and
    checking the resulting Trigger objects' own block_type/entry_type before ever writing this
    binding (both came back 'normal'/'normal', matching a freshly add_trigger()'d one)."""
    rvt, variant, mp = juggernaut
    end_round = _find_action_function(rvt, "End Round")
    t = mp.add_trigger()
    action = rvt.Action()
    action.function = end_round
    t.add_opcode(action)

    reloaded = _save_and_reload(rvt, variant)
    text = reloaded.decompile_script()
    assert text.rstrip().endswith("do\r\n   game.end_round()\r\nend")


def test_bind_trigger_as_event_sets_both_the_trigger_and_the_lookup_table(juggernaut) -> None:
    rvt, _variant, mp = juggernaut
    t = mp.add_trigger()
    index = mp.trigger_count - 1
    assert mp.entry_points.get_index_of_event(rvt.TriggerEntryType.pregame) == -1

    mp.bind_trigger_as_event(index, rvt.TriggerEntryType.pregame)
    assert t.entry_type == rvt.TriggerEntryType.pregame
    assert mp.entry_points.get_index_of_event(rvt.TriggerEntryType.pregame) == index


def test_event_bound_trigger_persists_through_save_reload(juggernaut) -> None:
    rvt, variant, mp = juggernaut
    end_round = _find_action_function(rvt, "End Round")
    t = mp.add_trigger()
    index = mp.trigger_count - 1
    mp.bind_trigger_as_event(index, rvt.TriggerEntryType.pregame)
    action = rvt.Action()
    action.function = end_round
    t.add_opcode(action)

    reloaded = _save_and_reload(rvt, variant)
    text = reloaded.decompile_script()
    assert "on pregame: do\r\n   game.end_round()\r\nend" in text
    assert reloaded.multiplayer.entry_points.get_index_of_event(rvt.TriggerEntryType.pregame) == index


def test_mark_trigger_as_subroutine_sets_entry_type(juggernaut) -> None:
    """``entry_type`` has no direct setter and ``bind_trigger_as_event()`` explicitly can't set
    'subroutine' (its own docstring: "'normal'/'subroutine' do nothing here") -- added
    ``mark_trigger_as_subroutine()`` (PROMPT.md: "we want a fromm scratch compiler then") because a
    from-scratch compiler's own nested if/do/for-each construction needs exactly this: confirmed via
    direct reading of the native compiler's own ``compiler.cpp`` (``Block::compile()``) that *every*
    block nested inside another non-root block gets ``entryType = subroutine`` unconditionally, or
    the game engine would tick it independently in addition to running it via 'Run Nested Trigger' --
    a real double-execution bug, not a cosmetic one.
    """
    rvt, _variant, mp = juggernaut
    t = mp.add_trigger()
    index = mp.trigger_count - 1
    assert t.entry_type == rvt.TriggerEntryType.normal

    mp.mark_trigger_as_subroutine(index)
    assert t.entry_type == rvt.TriggerEntryType.subroutine


def test_subroutine_trigger_persists_through_save_reload_and_decompiles_nested(juggernaut) -> None:
    rvt, variant, mp = juggernaut
    end_round = _find_action_function(rvt, "End Round")
    run_nested = _find_action_function(rvt, "Run Nested Trigger")
    # A real existing TriggerArgument to clone-and-retarget -- TriggerArgument() has no constructor
    # of its own either (same "no constructor for a from-nothing reference" shape as Variable), so
    # this sources a template from trigger 0's own two existing "Run Nested Trigger" calls, same
    # clone()-then-mutate-the-writable-fields pattern already proven for Variable elsewhere in this
    # file.
    template_trigger_arg = mp.trigger(0).opcode(0).argument(0)
    assert isinstance(template_trigger_arg, rvt.TriggerArgument)

    child = mp.add_trigger()
    child_index = mp.trigger_count - 1
    mp.mark_trigger_as_subroutine(child_index)
    child_action = rvt.Action()
    child_action.function = end_round
    child.add_opcode(child_action)

    top = mp.add_trigger()
    call_action = rvt.Action()
    call_action.function = run_nested
    trigger_arg = template_trigger_arg.clone()
    trigger_arg.value = child_index
    call_action.add_argument(trigger_arg)
    top.add_opcode(call_action)

    reloaded = _save_and_reload(rvt, variant)
    r_child = reloaded.multiplayer.trigger(child_index)
    assert r_child.entry_type == rvt.TriggerEntryType.subroutine
    text = reloaded.decompile_script()
    # Exactly one caller -> the decompiler inlines it as a nested "do ... end" block rather than a
    # named "trigger_N()" call (see megalo_ast.engine's own is_function computation) -- this is
    # what makes a from-scratch compiler's "always build an ordinary nested trigger, never inline"
    # strategy actually close the bInlineIfs gap: our own compiler decides the structure outright.
    assert text.rstrip().endswith("do\r\n   do\r\n      game.end_round()\r\n   end\r\nend")


def test_mark_trigger_block_type_sets_block_type(juggernaut) -> None:
    """Same "no direct setter" gap as entry_type, same fix (PROMPT.md: "we want a fromm scratch
    compiler then") -- added ``mark_trigger_block_type()`` since a from-scratch compiler's own
    "for each ..." loop construction needs it."""
    rvt, _variant, mp = juggernaut
    t = mp.add_trigger()
    index = mp.trigger_count - 1
    assert t.block_type == rvt.TriggerBlockType.normal

    mp.mark_trigger_block_type(index, rvt.TriggerBlockType.for_each_object)
    assert t.block_type == rvt.TriggerBlockType.for_each_object


def test_mark_trigger_block_type_rejects_for_each_object_with_label(juggernaut) -> None:
    # for_each_object_with_label also needs a forge label wired up -- not something this plain
    # field setter can do safely, so it refuses rather than silently leaving forge_label unset.
    rvt, _variant, mp = juggernaut
    t = mp.add_trigger()
    index = mp.trigger_count - 1
    with pytest.raises(Exception):  # noqa: PT011, B017 -- pybind surfaces std::invalid_argument
        mp.mark_trigger_block_type(index, rvt.TriggerBlockType.for_each_object_with_label)
    assert t.block_type == rvt.TriggerBlockType.normal


def test_for_each_object_trigger_persists_and_decompiles(juggernaut) -> None:
    rvt, variant, mp = juggernaut
    end_round = _find_action_function(rvt, "End Round")
    t = mp.add_trigger()
    mp.mark_trigger_block_type(mp.trigger_count - 1, rvt.TriggerBlockType.for_each_object)
    action = rvt.Action()
    action.function = end_round
    t.add_opcode(action)

    reloaded = _save_and_reload(rvt, variant)
    text = reloaded.decompile_script()
    assert text.rstrip().endswith("for each object do\r\n   game.end_round()\r\nend")


def test_mark_trigger_forge_label_sets_block_type_and_forge_label(juggernaut) -> None:
    """for_each_object_with_label needs both block_type AND forge_label set together (PROMPT.md:
    "we want a fromm scratch compiler then") -- mark_trigger_block_type() deliberately refuses this
    one block_type on its own for exactly that reason (see its own docstring)."""
    rvt, _variant, mp = juggernaut
    t = mp.add_trigger()
    index = mp.trigger_count - 1
    assert t.forge_label is None

    mp.mark_trigger_forge_label(index, 0)
    assert t.block_type == rvt.TriggerBlockType.for_each_object_with_label
    assert t.forge_label is not None


def test_for_each_object_with_label_trigger_persists_and_decompiles(juggernaut) -> None:
    rvt, variant, mp = juggernaut
    end_round = _find_action_function(rvt, "End Round")
    t = mp.add_trigger()
    mp.mark_trigger_forge_label(mp.trigger_count - 1, 0)  # juggernaut.bin's own label 0: "juggernaut"
    action = rvt.Action()
    action.function = end_round
    t.add_opcode(action)

    reloaded = _save_and_reload(rvt, variant)
    text = reloaded.decompile_script()
    assert text.rstrip().endswith('for each object with label "juggernaut" do\r\n   game.end_round()\r\nend')


def test_forge_label_argument_set_value_wires_a_real_label(juggernaut) -> None:
    """Same 'no setter on a refcount_ptr-backed property' gap as Trigger.forgeLabel, same fix
    (PROMPT.md: "we want a fromm scratch compiler then") -- ForgeLabelArgument.value had no setter
    at all, blocking any construction of e.g. a real 'place_at_me(..., "label", ...)' call."""
    rvt, variant, mp = juggernaut
    create_object = _find_action_function(rvt, "Create Object")
    label_arg = create_object.arguments[3].typeinfo.create()
    assert label_arg.decompile(variant) == "none"

    label_arg.set_value(mp, 0)  # juggernaut.bin's own label 0: "juggernaut"
    assert label_arg.decompile(variant) == '"juggernaut"'
    assert label_arg.value is mp.forge_label(0)


def _find_literal_scalar(rvt, variant, mp):
    for ti in range(mp.trigger_count):
        t = mp.trigger(ti)
        for oi in range(t.opcode_count):
            op = t.opcode(oi)
            for ai in range(op.argument_count):
                arg = op.argument(ai)
                inner = arg.variable if hasattr(arg, "variable") else arg
                if isinstance(inner, rvt.ScalarVariable) and inner.scope is not None and inner.scope.format == "%i":
                    return inner
    raise AssertionError("no real integer-literal ScalarVariable found in juggernaut.bin")


def test_variable_copy_from_populates_an_embedded_scope_none_variable(juggernaut) -> None:
    """ShapeArgument.radius/.length/.top/.bottom (PROMPT.md: "we want a fromm scratch compiler
    then") are each a live ScalarVariable& reference into the ShapeArgument's own storage, not a
    standalone value that could be cloned-and-reassigned -- freshly create()'d, they start
    scope=None (unusable, empty decompile) with no way to populate them: Variable.scope has no
    setter, and ShapeArgument.radius itself has no setter either (confirmed: assigning a clone to it
    raises "property has no setter"). copy_from() is the fix -- copies scope/which/index/object from
    a real Variable of the exact same concrete type directly into the live embedded member."""
    rvt, variant, mp = juggernaut
    literal = _find_literal_scalar(rvt, variant, mp)
    set_shape = _find_action_function(rvt, "Set Object Shape")
    shape = set_shape.arguments[1].typeinfo.create()
    shape.shape_type = rvt.ShapeType.sphere
    assert shape.radius.decompile(variant) == ""

    shape.radius.copy_from(literal)
    shape.radius.index = 15
    assert shape.radius.decompile(variant) == "15"


def _find_object_variable(rvt, mp):
    for ti in range(mp.trigger_count):
        t = mp.trigger(ti)
        for oi in range(t.opcode_count):
            op = t.opcode(oi)
            for ai in range(op.argument_count):
                arg = op.argument(ai)
                inner = arg.variable if hasattr(arg, "variable") else arg
                if isinstance(inner, rvt.ObjectVariable):
                    return inner
    raise AssertionError("no real ObjectVariable found in juggernaut.bin")


def test_variable_copy_from_does_not_guard_against_a_mismatched_concrete_type_in_release_builds(juggernaut) -> None:
    """The native ``Variable::copy()`` this wraps only checks its "same concrete type" invariant via
    a plain C++ ``assert()`` (see its own docstring in ``bindings.cpp``) -- compiled out entirely in
    this Release build, confirmed directly: copying a ScalarVariable's state into a live
    ObjectVariable does NOT raise. copy_from() itself is unsafe with a mismatched type in this build
    -- callers (in_reach.app.rvt.megalo_compiler in particular) must only ever pass a source of the
    exact same concrete type, never rely on this method to catch a mistake."""
    rvt, variant, mp = juggernaut
    literal = _find_literal_scalar(rvt, variant, mp)
    object_var = _find_object_variable(rvt, mp)

    object_var.copy_from(literal)  # does not raise -- see this test's own docstring


def test_max_triggers_limit_raises(juggernaut) -> None:
    # Limits::max_triggers is 320 -- juggernaut.bin already has 25, so this is well within reach
    # without needing to hardcode the exact limit here.
    _rvt, _variant, mp = juggernaut
    count_before = mp.trigger_count
    added = 0
    with pytest.raises(RuntimeError):
        for _ in range(400):
            mp.add_trigger()
            added += 1
    assert mp.trigger_count == count_before + added
