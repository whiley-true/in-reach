"""How a script's top-level statements become triggers -- in particular a top-level ``for each``.

Each top-level statement is its own always-ticking trigger in real Megalo, and the native compiler
builds a top-level ``for each`` as a trigger whose *loop type is set directly* -- no wrapper, no call.
This compiler used to pack every top-level statement into one shared trigger, which forced each loop
into a separate subroutine reached by a "Run Nested Trigger" action: one wasted action per loop. In a
script already at the engine's 1024-action cap (RCC Onslaught v13 sits at 1013) that was enough to
push the in-house build over it. Now a loop gets its own trigger with the type set on it, and plain
statements between loops are packed together, in source order.
"""
import pytest

from in_reach.app.blank_variant import resolve_blank_variant
from in_reach.app.rvt import megalo_compiler, rvt_bridge, template_source
from in_reach.app.rvt.decompile import normalize_script_text

pytestmark = pytest.mark.skipif(
    not rvt_bridge.is_available(), reason="native _reachvarianttool extension not available on this platform"
)


@pytest.fixture(scope="module")
def rvt():
    return rvt_bridge.get_rvt()


def _blank(rvt):
    return rvt.load(str(resolve_blank_variant(firefight=False)))


def _compile_in_house(rvt, source: str):
    variant = _blank(rvt)
    megalo_compiler.compile_script(rvt, variant, source, template_pool=lambda: template_source.build_variants(rvt))
    return variant


def _compile_native(rvt, source: str):
    variant = _blank(rvt)
    result = variant.multiplayer.compile_script(source)
    assert result.success, [m.text for m in list(result.fatal_errors) + list(result.errors)]
    return variant


def _actions(variant) -> int:
    return variant.multiplayer.get_full_size_data().counts["actions"]


def _shape(variant):
    """Per trigger, in order: (loop type, forge label name or None, opcode count) -- a compiler-neutral
    description of the trigger layout."""
    english = rvt_bridge.get_rvt().Language.english
    mp = variant.multiplayer
    out = []
    for i in range(mp.trigger_count):
        trigger = mp.trigger(i)
        label = trigger.forge_label.name.get_content(english) if trigger.forge_label is not None else None
        out.append((str(trigger.block_type), label, trigger.opcode_count))
    return out


_LOOP = "for each player do\n   current_player.number[0] += 1\nend\n"


# -- one loop, one trigger ---------------------------------------------------------------------------------------


def test_a_top_level_loop_is_a_single_trigger_with_the_loop_type_on_it(rvt) -> None:
    variant = _compile_in_house(rvt, _LOOP)
    assert variant.multiplayer.trigger_count == 1
    assert variant.multiplayer.trigger(0).block_type == rvt.TriggerBlockType.for_each_player


def test_and_that_trigger_calls_nothing(rvt) -> None:
    """No "Run Nested Trigger" anywhere: the loop's own body is the whole trigger."""
    variant = _compile_in_house(rvt, _LOOP)
    trigger = variant.multiplayer.trigger(0)
    assert trigger.opcode_count == 1  # just `current_player.number[0] += 1`
    assert "trigger_" not in normalize_script_text(variant.decompile_script())


@pytest.mark.parametrize(
    "loop",
    [
        "for each player do\n   current_player.number[0] += 1\nend\n",
        "for each object do\n   current_object.number[0] += 1\nend\n",
        "for each team do\n   current_team.number[0] += 1\nend\n",
        "for each player randomly do\n   current_player.number[0] += 1\nend\n",
    ],
)
def test_each_loop_kind_gets_its_own_loop_type_matching_native(rvt, loop: str) -> None:
    assert _shape(_compile_in_house(rvt, loop)) == _shape(_compile_native(rvt, loop))


def test_a_labelled_loop_carries_its_label_on_the_trigger_matching_native(rvt) -> None:
    loop = 'for each object with label "hill" do\n   current_object.number[0] += 1\nend\n'
    in_house, native = _compile_in_house(rvt, loop), _compile_native(rvt, loop)
    assert _shape(in_house) == _shape(native)
    assert _shape(in_house)[0][1] == "hill"  # the label the script created


def test_a_loop_with_an_if_in_its_body_still_matches_native(rvt) -> None:
    loop = (
        "for each player do\n"
        "   if current_player.number[0] == 1 then\n"
        "      current_player.number[1] += 1\n"
        "   end\n"
        "end\n"
    )
    assert _shape(_compile_in_house(rvt, loop)) == _shape(_compile_native(rvt, loop))


# -- the saving that motivated it ---------------------------------------------------------------------------------


def test_a_loop_costs_only_its_body_not_a_call_as_well(rvt) -> None:
    """Thirty loops of one action each: thirty actions. As nested subroutines behind one shared trigger
    it was sixty -- a "Run Nested Trigger" per loop on top of the body."""
    variant = _compile_in_house(rvt, _LOOP * 30)
    assert _actions(variant) == 30
    assert variant.multiplayer.trigger_count == 30


def test_the_action_count_is_never_more_than_natives_for_the_same_loops(rvt) -> None:
    script = _LOOP * 12
    assert _actions(_compile_in_house(rvt, script)) <= _actions(_compile_native(rvt, script))


# -- source order is kept ------------------------------------------------------------------------------------------------


def test_plain_statements_and_loops_stay_in_the_order_they_were_written(rvt) -> None:
    """Triggers tick in order, so splitting the top level into pieces must not reorder it."""
    source = (
        "global.number[0] = 1\n"  # plain run 1
        "for each player do\n   current_player.number[0] = 2\nend\n"  # loop
        "global.number[1] = 3\n"  # plain run 2 -- a trigger of its own, after the loop
        "global.number[2] = 4\n"
        "for each object do\n   current_object.number[0] = 5\nend\n"  # loop
        "global.number[3] = 6\n"  # plain run 3
    )
    variant = _compile_in_house(rvt, source)
    text = normalize_script_text(variant.decompile_script())
    positions = [text.index(marker) for marker in ("number[0] = 1", "number[0] = 2", "number[1] = 3", "number[2] = 4", "number[0] = 5", "number[3] = 6")]
    assert positions == sorted(positions)


def test_a_run_of_plain_statements_between_two_loops_shares_one_trigger(rvt) -> None:
    source = _LOOP + "global.number[0] = 1\nglobal.number[1] = 2\nglobal.number[2] = 3\n" + _LOOP
    variant = _compile_in_house(rvt, source)
    shape = _shape(variant)
    assert len(shape) == 3  # loop, the three plain statements together, loop
    assert shape[1][2] == 3


def test_plain_statements_alone_still_share_a_single_trigger(rvt) -> None:
    variant = _compile_in_house(rvt, "global.number[0] = 1\nglobal.number[1] = 2\nglobal.number[2] = 3\n")
    assert variant.multiplayer.trigger_count == 1


# -- what is deliberately unchanged --------------------------------------------------------------------------------


def test_a_loop_inside_an_if_is_still_a_nested_subroutine(rvt) -> None:
    """Only a *top-level* loop can take the loop type directly; one inside a body is reached by a call."""
    source = "if global.number[0] == 1 then\n   for each player do\n      current_player.number[0] += 1\n   end\nend\n"
    variant = _compile_in_house(rvt, source)
    assert variant.multiplayer.trigger_count == 2  # the shared trigger and the loop's subroutine
    assert variant.multiplayer.trigger(1).block_type == rvt.TriggerBlockType.for_each_player


def test_a_loop_inside_a_function_is_still_a_nested_subroutine(rvt) -> None:
    source = "function sweep()\n   for each player do\n      current_player.number[0] += 1\n   end\nend\nsweep()\n"
    variant = _compile_in_house(rvt, source)
    assert variant.multiplayer.trigger_count == 3  # the function, its loop, and the top-level call


def test_a_loop_bound_to_an_event_is_unchanged(rvt) -> None:
    source = "on init: for each player do\n   current_player.number[0] += 1\nend\n"
    variant = _compile_in_house(rvt, source)
    assert "on init:" in normalize_script_text(variant.decompile_script())


# -- and a script with nothing at the top level ----------------------------------------------------------------------


def test_a_script_with_no_top_level_statements_gets_no_trigger_for_them(rvt) -> None:
    """It used to get an empty one, which decompiled as a stray `do` / `end` pair."""
    variant = _compile_in_house(rvt, "")
    assert variant.multiplayer.trigger_count == 0
    assert normalize_script_text(variant.decompile_script()).strip() == ""


def test_a_script_of_only_an_event_gets_just_the_event_trigger(rvt) -> None:
    variant = _compile_in_house(rvt, "on init: global.number[0] = 1\n")
    assert variant.multiplayer.trigger_count == 1


# -- a top-level loop is validated exactly as before ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "for each player with label \"x\" do\n   current_player.number[0] = 1\nend\n",  # a label is only for objects
        "for each object randomly do\n   current_object.number[0] = 1\nend\n",  # randomly is only for players
    ],
)
def test_an_unsupported_loop_form_is_still_unsupported_at_the_top_level(rvt, source: str) -> None:
    with pytest.raises(megalo_compiler.UnsupportedConstruct):
        _compile_in_house(rvt, source)
