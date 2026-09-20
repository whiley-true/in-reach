"""Storage allocation: which slot each declared name gets, and what each slot is declared as."""
import pytest

from in_reach.app.rvt.megalo_ast import parse_annotations
from in_reach.app.rvt.megalo_ast.annotations import BitfieldAnnotation, StorageAnnotation
from in_reach.app.script_project.allocation import POOL_SIZES, Slot, allocate
from in_reach.app.script_project.model import Declared


def _declared(text: str, owner: str = "module m", file: str = "modules/m/m.mgl") -> tuple[list[Declared], list[Declared]]:
    result = parse_annotations(text)
    assert result.diagnostics == [], [d.message for d in result.diagnostics]
    storage = [Declared(a, file, owner) for a in result.items if isinstance(a, StorageAnnotation)]
    bitfields = [Declared(a, file, owner) for a in result.items if isinstance(a, BitfieldAnnotation)]
    return storage, bitfields


def _allocate(text: str, pins: dict | None = None, reserved: set | None = None):
    storage, bitfields = _declared(text)
    return allocate(storage, bitfields, pins or {}, reserved or set())


def _slots(result) -> dict[str, str]:
    return {name: slot.concrete for name, slot in result.slots.items()}


def test_names_take_the_lowest_free_slot_in_declaration_order() -> None:
    result = _allocate("-- @number a\n-- @number b\n-- @timer t\n-- @number c\n")

    assert _slots(result) == {"a": "global.number[0]", "b": "global.number[1]", "t": "global.timer[0]", "c": "global.number[2]"}
    assert result.ok and result.used == {("global", "number"): 3, ("global", "timer"): 1}


def test_each_scope_and_type_is_its_own_pool() -> None:
    result = _allocate("-- @number g\n-- @pnumber p\n-- @pobject po\n-- @oobject thing.o\n")

    assert {n: (s.scope, s.type, s.index) for n, s in result.slots.items()} == {
        "g": ("global", "number", 0), "p": ("player", "number", 0),
        "po": ("player", "object", 0), "o": ("object", "object", 0),
    }


def test_the_same_declarations_always_give_the_same_slots() -> None:
    text = "-- @number a\n-- @pnumber b\n-- @onumber k.c\n-- @timer d\n"

    assert _slots(_allocate(text)) == _slots(_allocate(text))


def test_a_full_pool_names_the_pool_and_what_tipped_it() -> None:
    text = "".join(f"-- @number n{i}\n" for i in range(POOL_SIZES["global"]["number"] + 1))

    result = _allocate(text)

    assert not result.ok
    [problem] = result.diagnostics
    assert "global.number is full (12 slots)" in problem.message and "n12 (module m)" in problem.message
    assert problem.line == 13 and problem.file == "modules/m/m.mgl"
    assert len(result.slots) == 12  # the rest are still placed


def test_slots_the_code_already_uses_are_left_alone() -> None:
    result = _allocate("-- @number a\n-- @number b\n", reserved={("global", "number", 0), ("global", "number", 2)})

    assert _slots(result) == {"a": "global.number[1]", "b": "global.number[3]"}
    assert result.used[("global", "number")] == 4


def test_a_reserved_slot_of_a_pool_nothing_declares_still_counts_as_used() -> None:
    result = _allocate("-- @number a\n", reserved={("player", "timer", 1)})

    assert result.used[("player", "timer")] == 2


def test_kinds_share_object_slots() -> None:
    result = _allocate("-- @onumber carrier.c_role\n-- @onumber carrier.c_flags\n-- @onumber weapon.w_level\n-- @onumber mine.m_armed\n")

    assert _slots(result) == {
        "c_role": "object.number[0]", "c_flags": "object.number[1]",
        "w_level": "object.number[0]", "m_armed": "object.number[0]",
    }
    assert result.used[("object", "number")] == 2  # two slots serve three kinds


def test_teams_share_team_slots_and_name_their_team() -> None:
    result = _allocate("-- @tnumber team3.mines\n-- @tnumber team3.kills\n-- @tnumber team5.mines2\n")

    assert _slots(result) == {"mines": "team[3].number[0]", "kills": "team[3].number[1]", "mines2": "team[5].number[0]"}


def test_a_pin_fixes_a_name_to_a_slot() -> None:
    result = _allocate("-- @pnumber a\n-- @pnumber p_hud\n", pins={"p_hud": "player.number[5]"})

    assert _slots(result) == {"a": "player.number[0]", "p_hud": "player.number[5]"}
    assert result.ok


@pytest.mark.parametrize(
    ("pins", "code"),
    [
        ({"p_hud": "nonsense"}, "pin-invalid"),
        ({"p_hud": "player.number[99]"}, "pin-invalid"),
        ({"p_hud": "global.number[0]"}, "pin-mismatch"),
        ({"p_hud": "player.timer[0]"}, "pin-mismatch"),
        ({"p_hud": "player.number[0]", "p_two": "player.number[0]"}, "pin-conflict"),
    ],
)
def test_bad_pins_are_reported(pins: dict, code: str) -> None:
    result = _allocate("-- @pnumber p_hud\n-- @pnumber p_two\n", pins=pins)

    assert code in [d.code for d in result.diagnostics] and not result.ok


def test_a_pin_for_an_undeclared_name_is_a_warning() -> None:
    result = _allocate("-- @number a\n", pins={"ghost": "global.number[0]"})

    assert [(d.code, d.severity) for d in result.diagnostics] == [("pin-unused", "warning")] and result.ok


def test_a_pin_wins_even_when_the_pinned_name_is_declared_after_others() -> None:
    """``a`` is declared first and would take slot 0, but ``p_hud`` is pinned there, so ``a`` moves."""
    result = _allocate("-- @pnumber a\n-- @pnumber p_hud\n", pins={"p_hud": "player.number[0]"})

    assert _slots(result) == {"a": "player.number[1]", "p_hud": "player.number[0]"}
    assert result.ok


# -- what a slot is declared as ---------------------------------------------------------------------------


def test_a_global_variables_priority_and_default_are_declared() -> None:
    result = _allocate("-- @number a priority=high default=7\n-- @number b\n-- @timer t default=30\n")

    assert result.declarations == {
        ("global", "number", 0): result.declarations[("global", "number", 0)],
        ("global", "timer", 0): result.declarations[("global", "timer", 0)],
    }
    a = result.declarations[("global", "number", 0)]
    assert (a.priority, a.default) == ("high", "7")
    assert result.declarations[("global", "timer", 0)].default == "30"
    assert ("global", "number", 1) not in result.declarations  # b said nothing


def test_a_timer_is_never_declared_with_a_priority() -> None:
    assert _allocate("-- @timer t default=5\n").declarations[("global", "timer", 0)].priority is None


def test_sharing_kinds_take_the_highest_priority_asked_for() -> None:
    result = _allocate("-- @onumber a.x priority=low\n-- @onumber b.y priority=high\n-- @onumber c.z\n")

    assert result.declarations[("object", "number", 0)].priority == "high"


def test_the_kind_that_owns_the_default_sets_it() -> None:
    result = _allocate("-- @otimer carrier.cap default=24 owns_default=true\n-- @otimer weapon.rate\n")

    assert _slots(result) == {"cap": "object.timer[0]", "rate": "object.timer[0]"}
    assert result.declarations[("object", "timer", 0)].default == "24"


def test_two_kinds_cannot_both_own_a_slots_default_so_the_second_moves() -> None:
    result = _allocate("-- @otimer carrier.a default=24 owns_default=true\n-- @otimer weapon.b default=5 owns_default=true\n")

    assert _slots(result) == {"a": "object.timer[0]", "b": "object.timer[1]"}
    assert result.declarations[("object", "timer", 0)].default == "24"
    assert result.declarations[("object", "timer", 1)].default == "5"


def test_a_default_that_is_not_owned_but_alone_still_applies() -> None:
    assert _allocate("-- @otimer carrier.a default=24\n").declarations[("object", "timer", 0)].default == "24"


def test_unowned_defaults_from_sharing_kinds_conflict_and_the_slot_gets_none() -> None:
    result = _allocate("-- @otimer carrier.a default=24\n-- @otimer weapon.b default=5\n")

    assert ("object", "timer", 0) not in result.declarations
    assert [(d.code, d.severity) for d in result.diagnostics] == [("default-ambiguous", "warning")]
    assert result.ok


def test_a_default_that_loses_to_the_owner_is_reported_as_ignored() -> None:
    result = _allocate("-- @otimer carrier.a default=24 owns_default=true\n-- @otimer weapon.b default=5\n")

    assert result.declarations[("object", "timer", 0)].default == "24"
    assert [d.code for d in result.diagnostics] == ["default-ignored"]


# -- bitfields ------------------------------------------------------------------------------------------


def test_a_bitfield_is_one_object_number_with_a_power_of_two_per_flag() -> None:
    result = _allocate("-- @onumber carrier.c_role\n-- @bitfield carrier.c_flags { kit_given, aa_latch, boarded }\n")

    assert result.slots["c_flags"] == Slot("object", "number", 1, "carrier")
    assert result.flags["c_flags"] == [("flag_kit_given", 1), ("flag_aa_latch", 2), ("flag_boarded", 4)]


def test_fifteen_flags_use_bits_zero_to_fourteen() -> None:
    flags = ", ".join(f"f{i}" for i in range(15))

    result = _allocate(f"-- @bitfield k.flags {{ {flags} }}\n")

    assert result.flags["flags"][-1] == ("flag_f14", 1 << 14)


def test_a_duplicate_name_keeps_its_first_slot() -> None:
    result = _allocate("-- @number a\n-- @number a\n-- @number b\n")

    assert _slots(result) == {"a": "global.number[0]", "b": "global.number[1]"}


def test_the_slot_knows_who_declared_it() -> None:
    storage, bitfields = _declared("-- @number a\n", owner="module hill_score")

    assert allocate(storage, bitfields, {}, set()).owners == {"a": "module hill_score"}
