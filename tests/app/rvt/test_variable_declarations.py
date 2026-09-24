"""``declare`` and implied variable declarations, as :mod:`in_reach.app.rvt.variable_declarations`
writes them into a variant.

The in-house compiler used to validate a ``declare`` line and then discard it: a script written from
scratch lost every initial value and network priority, and in a project made from a real ``.bin``
*editing* a ``declare`` line did nothing (the variant's own declarations survived untouched). It also
never declared a variable a script merely used, which native ``compile_script()`` does. The first half
of this file needs no native extension; the second checks the result against a real variant and
against native's own compiler.
"""
import tempfile
from pathlib import Path

import pytest

from in_reach.app.blank_variant import resolve_blank_variant
from in_reach.app.rvt import megalo_compiler, rvt_bridge, template_source
from in_reach.app.rvt.decompile import normalize_script_text
from in_reach.app.rvt.megalo_ast import parse
from in_reach.app.rvt.variable_declarations import UnsupportedDeclaration, collect_declarations

_JUGGERNAUT_BIN = Path(__file__).parent / "resources" / "juggernaut" / "juggernaut.bin"
_NEEDS_NATIVE = pytest.mark.skipif(
    not rvt_bridge.is_available(), reason="native _reachvarianttool extension not available on this platform"
)
_NEEDS_JUGGERNAUT = pytest.mark.skipif(not _JUGGERNAUT_BIN.is_file(), reason="juggernaut fixture .bin not present")


def _plan(source: str):
    return collect_declarations(parse(source), megalo_compiler._POOL_SIZES)


# -- collect_declarations(): pure AST -> plan --------------------------------------------------------


def test_a_declare_line_is_recorded_with_its_priority_and_initial_value() -> None:
    plan = _plan("declare global.number[2] with network priority high = -7\n")

    slot = plan.explicit[("global", "number", 2)]
    assert slot.priority == "high"
    assert (slot.initial.scope_format, slot.initial.index) == ("%i", -7)
    assert plan.counts == {("global", "number"): 3}


def test_using_a_variable_implies_it_and_every_slot_below_it() -> None:
    plan = _plan("global.number[0] = current_player.number[3]\n")

    assert plan.counts == {("global", "number"): 1, ("player", "number"): 4}
    assert plan.explicit == {}


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("current_player.timer[1]", {("player", "timer"): 2}),
        ("hud_player.number[0]", {("player", "number"): 1}),
        ("current_object.number[2]", {("object", "number"): 3}),
        ("killed_object.number[4]", {("object", "number"): 5}),
        ("current_team.number[0]", {("team", "number"): 1}),
        ("neutral_team.object[1]", {("team", "object"): 2}),
        ("team[0].object[0]", {("team", "object"): 1}),
        # A nested variable implies both the owner's own slot and the slot inside the owner's scope.
        ("global.player[2].timer[1]", {("global", "player"): 3, ("player", "timer"): 2}),
        ("global.object[3].number[1]", {("global", "object"): 4, ("object", "number"): 2}),
        ("global.team[1].object[0]", {("global", "team"): 2, ("team", "object"): 1}),
    ],
)
def test_a_reference_implies_the_slots_it_names(reference: str, expected: dict) -> None:
    assert _plan(f"global.number[9] = {reference}\n").counts == {("global", "number"): 10, **expected}


def test_a_temporary_is_never_declared() -> None:
    assert _plan("temporaries.number[3] = 1\n").counts == {}


def test_a_reference_inside_a_function_or_an_event_body_is_found() -> None:
    plan = _plan("function f()\n   global.number[1] = 1\nend\non init: do\n   global.timer[2] = 5\nend\n")

    assert plan.counts == {("global", "number"): 2, ("global", "timer"): 3}


def test_an_implied_slot_keeps_a_later_explicit_declaration() -> None:
    plan = _plan("global.number[1] = 1\ndeclare global.number[1] with network priority local\n")

    assert plan.explicit[("global", "number", 1)].priority == "local"
    assert plan.counts == {("global", "number"): 2}


@pytest.mark.parametrize(
    ("value", "team_code"),
    [("team[0]", 0), ("team[7]", 7), ("neutral_team", 8), ("no_team", -1)],
)
def test_a_team_initial_value_is_one_of_the_constant_teams(value: str, team_code: int) -> None:
    plan = _plan(f"declare global.team[0] with network priority low = {value}\n")

    assert plan.explicit[("global", "team", 0)].initial.team_code == team_code


@pytest.mark.parametrize(
    ("value", "scope_format", "index"),
    [("5", "%i", 5), ("script_option[2]", "script_option[%i]", 2), ("game.loadout_cam_time", "game.loadout_cam_time", 0)],
)
def test_a_timer_initial_value_can_be_a_constant_an_option_or_a_built_in(
    value: str, scope_format: str, index: int
) -> None:
    initial = _plan(f"declare global.timer[0] = {value}\n").explicit[("global", "timer", 0)].initial

    assert (initial.scope_format, initial.index) == (scope_format, index)


def test_the_script_options_an_initial_value_names_are_counted() -> None:
    assert _plan("declare global.timer[0] = script_option[4]\ndeclare global.number[0] = 1\n").script_option_count == 5
    assert _plan("declare global.number[0] = 1\n").script_option_count == 0


@pytest.mark.parametrize(
    "source",
    [
        "declare global.number[12]\n",  # past the pool (0-11)
        "global.number[12] = 1\n",
        "declare temporaries.number[0]\n",
        "declare global.number[0]\ndeclare global.number[0] with network priority low\n",
        "declare global.timer[0] with network priority low\n",  # a timer has no network priority
        "declare global.number[0] with network priority default\n",  # native rejects "default" too
        "declare global.player[0] = 1\n",  # a player has no initial value
        "declare global.team[0] = 3\n",
        "declare global.team[0] = team[8]\n",
        "declare global.number[0] = global.number[1]\n",  # another variable isn't a constant
        "current_player.biped.number[1] = 1\n",  # an owner this doesn't know how to classify
    ],
)
def test_anything_it_cannot_represent_is_unsupported_rather_than_guessed_at(source: str) -> None:
    with pytest.raises(UnsupportedDeclaration):
        _plan(source)


# -- through the native extension ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rvt():
    return rvt_bridge.get_rvt()


@pytest.fixture
def blank(rvt):
    return rvt.load(str(resolve_blank_variant(firefight=False)))


@pytest.fixture
def juggernaut(rvt):
    return rvt.load(str(_JUGGERNAUT_BIN))


def _pool(rvt):
    return lambda: template_source.build_variants(rvt)


def _declares(variant) -> list[str]:
    return [line for line in normalize_script_text(variant.decompile_script()).splitlines() if line.startswith("declare ")]


def _saved_and_reloaded(rvt, variant):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "out.bin"
        variant.save(str(path))
        return rvt.load(str(path))


@_NEEDS_NATIVE
def test_a_declare_line_reaches_the_saved_variant(rvt, blank) -> None:
    source = (
        "declare global.number[0] with network priority high = 7\n"
        "declare global.number[1] with network priority local = -3\n"
        "declare global.timer[0] = 30\n"
        "declare global.team[0] with network priority low = team[3]\n"
        "declare object.team[1] = neutral_team\n"
        "declare global.player[0] with network priority local\n"
        "declare global.object[0] with network priority high\n"
    )

    megalo_compiler.compile_script(rvt, blank, source, template_pool=_pool(rvt))

    assert _declares(_saved_and_reloaded(rvt, blank)) == [
        "declare global.number[0] with network priority high = 7",
        "declare global.number[1] with network priority local = -3",
        "declare global.object[0] with network priority high",
        "declare global.player[0] with network priority local",
        "declare global.team[0] with network priority low = team[3]",
        "declare global.timer[0] = 30",
        "declare object.team[0] with network priority low",  # implied: a list grows to index + 1
        "declare object.team[1] with network priority low = neutral_team",
    ]


@_NEEDS_NATIVE
def test_an_initial_value_can_name_a_script_option_or_a_built_in(rvt, blank) -> None:
    source = "declare global.timer[0] = script_option[2]\ndeclare global.timer[1] = game.loadout_cam_time\n"

    megalo_compiler.compile_script(rvt, blank, source, template_pool=_pool(rvt))

    reloaded = _saved_and_reloaded(rvt, blank)
    assert _declares(reloaded) == [
        "declare global.timer[0] = script_option[2]",
        "declare global.timer[1] = game.loadout_cam_time",
    ]
    assert reloaded.multiplayer.scripted_option_count == 3  # option 2 had to exist for the timer to name it


_SCRIPTS_NATIVE_MUST_AGREE_ON = {
    "an initial value and a priority": "declare global.number[0] with network priority high = 7\nglobal.number[0] += 1\n",
    "a used variable is declared": "global.number[2] = 1\nglobal.timer[1] = 5\n",
    "a loop over players": (
        "for each player do\n   if current_player.number[0] == 1 then\n      current_player.number[1] += 1\n   end\nend\n"
    ),
    "a slot below the one declared is implied": "declare object.team[1] = neutral_team\nglobal.number[0] = 1\n",
    "a declared timer and a team": (
        "declare global.timer[0] = 30\ndeclare global.team[1] with network priority low = team[2]\nglobal.number[0] = 1\n"
    ),
}


@_NEEDS_NATIVE
@pytest.mark.parametrize("source", _SCRIPTS_NATIVE_MUST_AGREE_ON.values(), ids=_SCRIPTS_NATIVE_MUST_AGREE_ON.keys())
def test_the_declarations_equal_what_the_native_compiler_produces(rvt, blank, source: str) -> None:
    native = rvt.load(str(resolve_blank_variant(firefight=False)))
    assert native.multiplayer.compile_script(source).success

    megalo_compiler.compile_script(rvt, blank, source, template_pool=_pool(rvt))

    assert _declares(blank) == _declares(native)
    assert _declares(blank), "the script should declare something, or this proves nothing"


@_NEEDS_NATIVE
@_NEEDS_JUGGERNAUT
def test_editing_a_declare_line_changes_a_variant_that_already_had_it(rvt, juggernaut) -> None:
    """The reported bug: in a project made from a real ``.bin`` the variant's own declarations
    survived, so editing (or deleting) a ``declare`` line in ``output.mgl`` silently did nothing."""
    assert "declare global.number[0] with network priority local" in _declares(juggernaut)
    source = normalize_script_text(juggernaut.decompile_script()).replace(
        "declare global.number[0] with network priority local",
        "declare global.number[0] with network priority high = 7",
    )

    megalo_compiler.compile_script(rvt, juggernaut, source)

    declares = _declares(_saved_and_reloaded(rvt, juggernaut))
    assert "declare global.number[0] with network priority high = 7" in declares
    assert "declare global.number[0] with network priority local" not in declares


@_NEEDS_NATIVE
@_NEEDS_JUGGERNAUT
def test_a_declaration_the_script_no_longer_has_is_dropped(rvt, juggernaut) -> None:
    """The script text is the whole truth, as with the native compiler: a variant's own prior
    declarations don't survive a compile whose script doesn't mention them."""
    assert "declare player.timer[0] = 1" in _declares(juggernaut)

    megalo_compiler.compile_script(rvt, juggernaut, "global.number[0] = 1\n")

    assert _declares(juggernaut) == ["declare global.number[0] with network priority low"]


@_NEEDS_NATIVE
@_NEEDS_JUGGERNAUT
def test_recompiling_a_real_variants_own_script_keeps_its_declarations(rvt, juggernaut) -> None:
    before = _declares(juggernaut)
    assert len(before) > 5, "juggernaut should have a real set of declarations"

    megalo_compiler.compile_script(rvt, juggernaut, normalize_script_text(juggernaut.decompile_script()))

    assert _declares(juggernaut) == before


@_NEEDS_NATIVE
def test_an_unclassifiable_owner_falls_back_instead_of_writing_a_wrong_declaration(rvt, blank) -> None:
    with pytest.raises(megalo_compiler.UnsupportedConstruct, match="can't tell which scope"):
        megalo_compiler.compile_script(rvt, blank, "current_player.biped.number[1] = 1\n", template_pool=_pool(rvt))


@_NEEDS_NATIVE
def test_a_declare_that_repeats_a_slot_is_left_to_the_native_compiler(rvt, blank) -> None:
    with pytest.raises(megalo_compiler.UnsupportedConstruct, match="more than once"):
        megalo_compiler.compile_script(
            rvt, blank, "declare global.number[0]\ndeclare global.number[0]\n", template_pool=_pool(rvt)
        )


# -- the native bindings themselves ----------------------------------------------------------------------


def _global_declarations(rvt, variant):
    return variant.multiplayer.variable_declarations(getattr(rvt.VariableScope, "global"))


@_NEEDS_NATIVE
@_NEEDS_JUGGERNAUT
def test_the_bindings_read_a_real_variants_declarations(rvt, juggernaut) -> None:
    declarations = _global_declarations(rvt, juggernaut)
    types = rvt.VariableType

    assert [declarations.count(t) for t in (types.scalar, types.timer, types.team, types.player, types.object)] == [
        3, 2, 0, 4, 3
    ]
    number = declarations.get(types.scalar, 0)
    assert number.networking == rvt.VariableNetworkPriority.local
    assert number.has_network_type and number.has_initial_value
    timer = declarations.get(types.timer, 1)
    assert not timer.has_network_type
    assert (timer.initial_number.scope.format, timer.initial_number.index) == ("%i", 5)
    assert declarations.get(types.player, 0).initial_number is None


@_NEEDS_NATIVE
def test_the_bindings_refuse_what_the_engine_cannot_hold(rvt, blank) -> None:
    declarations = _global_declarations(rvt, blank)
    types = rvt.VariableType

    with pytest.raises(IndexError):
        declarations.grow_to(types.scalar, 13)  # a scope holds at most 12 numbers
    with pytest.raises(IndexError):
        declarations.get(types.scalar, 0)  # nothing declared yet
    with pytest.raises(ValueError):
        declarations.count(types.not_a_variable)
    with pytest.raises(ValueError):
        blank.multiplayer.variable_declarations(rvt.VariableScope.temporary)

    declarations.grow_to(types.timer, 1)
    declarations.grow_to(types.team, 1)
    with pytest.raises(RuntimeError):
        declarations.get(types.timer, 0).networking = rvt.VariableNetworkPriority.high
    with pytest.raises(ValueError):
        declarations.get(types.team, 0).initial_team = 9
    with pytest.raises(RuntimeError):
        declarations.get(types.timer, 0).initial_team = 1


@_NEEDS_NATIVE
def test_growing_never_shrinks_and_clear_empties_every_list(rvt, blank) -> None:
    declarations = _global_declarations(rvt, blank)
    scalar = rvt.VariableType.scalar

    declarations.grow_to(scalar, 4)
    declarations.grow_to(scalar, 2)
    assert declarations.count(scalar) == 4

    declarations.clear()
    assert declarations.count(scalar) == 0
