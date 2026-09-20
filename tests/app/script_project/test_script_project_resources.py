"""Engine resources declared in code (``@trait``/``@option``/``@widget``/``@label``) and how they reach
``settings/script_settings.json`` -- next_steps decision 2: modules write their own, hand-made entries are never
moved, and the user's edits win."""
import pytest

from in_reach.app.rvt.megalo_ast import parse_annotations
from in_reach.app.rvt.models.script_settings import (
    ScriptedHUDWidget, ScriptedOption, ScriptedOptionValue, ScriptedPlayerTraits, ScriptSettings,
)
from in_reach.app.script_project.model import Declared
from in_reach.app.script_project.resources import ResourceInfo, digest, plan_resources


def _declared(text: str, owner: str = "module m") -> list[Declared]:
    result = parse_annotations(text)
    assert result.diagnostics == [], [d.message for d in result.diagnostics]
    return [Declared(a, "modules/m/m.mgl", owner) for a in result.items]


def _plan(text: str, current: ScriptSettings | None = None, previous: dict | None = None):
    return plan_resources(_declared(text), current or ScriptSettings(), previous or {})


def _previous(plan) -> dict:
    """What link_map.json records after ``plan``: kind, index and digest per name."""
    return {n: {"kind": r.kind, "index": r.index, "digest": r.digest} for n, r in plan.resources.items()}


# -- building entries -----------------------------------------------------------------------------------


def test_a_trait_becomes_a_settings_entry_and_an_alias_target() -> None:
    plan = _plan('-- @trait t_freeze { movement_speed = "value_000", jump_height = 0 }\n')

    [entry] = plan.settings.scripted_player_traits
    assert entry.name == "t_freeze" and entry.traits.movement.speed == "value_000" and entry.traits.movement.jump_height == 0
    assert plan.resources["t_freeze"] == ResourceInfo("trait", 0, "module m", plan.resources["t_freeze"].digest)
    assert plan.resources["t_freeze"].alias_value == "script_traits[0]"
    assert plan.changed and plan.diagnostics == []


def test_a_trait_can_carry_its_own_display_name_and_description() -> None:
    entry = _plan('-- @trait t_a { name = "Frozen", desc = "cannot move", speed = "value_000" }\n').settings.scripted_player_traits[0]

    assert (entry.name, entry.desc) == ("Frozen", "cannot move")


def test_a_toggle_option() -> None:
    plan = _plan('-- @option o_dev { type = "toggle", default = 1, name = "DEV disableWin" }\n')

    [option] = plan.settings.scripted_options
    assert (option.name, option.is_range, option.default_value_index) == ("DEV disableWin", False, 1)
    assert [(v.name, v.value) for v in option.values] == [("Off", 0), ("On", 1)]
    assert plan.resources["o_dev"].alias_value == "script_option[0]"


def test_a_range_option() -> None:
    [option] = _plan('-- @option o_mins { type = "range", min = 1, max = 30, default = 10, name = "Round minutes" }\n').settings.scripted_options

    assert option.is_range and option.name == "Round minutes"
    assert (option.range_min.value, option.range_max.value, option.range_default.value, option.range_current) == (1, 30, 10, 10)


def test_a_widget() -> None:
    plan = _plan("-- @widget w_hud { position = 3 }\n")

    assert plan.settings.scripted_hud_widgets == [ScriptedHUDWidget(position=3)]
    assert plan.resources["w_hud"].alias_value == "script_widget[0]"


def test_a_label_is_recorded_for_substitution_and_writes_nothing() -> None:
    plan = _plan('-- @label L_hill = "hill"\n')

    assert plan.labels == {"L_hill": "hill"} and not plan.changed and plan.resources == {}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("-- @trait t { nonsense = 1 }\n", "isn't a trait field"),
        ('-- @trait t { movement_speed = "warp" }\n', "movement.speed"),
        ("-- @trait t { jump_height = 999 }\n", "less than or equal to 400"),
        ('-- @option o { type = "enum" }\n', "toggle or range"),
        ("-- @option o { default = 1 }\n", "toggle or range"),
        ('-- @option o { type = "toggle", default = 2 }\n', "0 or 1"),
        ('-- @option o { type = "toggle", extra = 1 }\n', "unknown field 'extra'"),
        ('-- @option o { type = "range", min = 1, max = 5 }\n', "missing default"),
        ('-- @option o { type = "range", min = 9, max = 5, default = 7 }\n', "isn't between"),
        ('-- @option o { type = "range", min = 1, max = 5000, default = 7 }\n', "invalid option value"),
        ('-- @widget w { position = "top_left" }\n', "number from 0 to 11"),
        ("-- @widget w { position = 12 }\n", "number from 0 to 11"),
        ("-- @widget w { color = 1 }\n", "unknown field 'color'"),
    ],
)
def test_invalid_declarations_are_reported_at_their_line_and_write_nothing(text: str, message: str) -> None:
    plan = _plan("-- @number ignored\n" + text)

    [problem] = plan.diagnostics
    assert (problem.code, problem.severity, problem.line) == ("resource-invalid", "error", 2)
    assert message in problem.message
    assert plan.resources == {} and not plan.changed


# -- stability, and decision 2 ----------------------------------------------------------------------------


def test_declared_resources_are_appended_after_the_entries_already_there() -> None:
    current = ScriptSettings(scripted_player_traits=[ScriptedPlayerTraits(name="hand made")])

    plan = _plan('-- @trait t_a { speed = "value_120" }\n', current)

    assert plan.settings.scripted_player_traits[0].name == "hand made"  # never moved
    assert plan.resources["t_a"].index == 1


def test_names_are_indexed_in_declaration_order_per_kind() -> None:
    plan = _plan('-- @trait a { speed = "value_100" }\n-- @widget w { position = 1 }\n-- @trait b { speed = "value_120" }\n')

    assert {n: r.index for n, r in plan.resources.items()} == {"a": 0, "w": 0, "b": 1}


def test_relinking_an_unchanged_project_changes_nothing() -> None:
    first = _plan('-- @trait a { speed = "value_100" }\n-- @option o { type = "toggle" }\n')

    second = _plan('-- @trait a { speed = "value_100" }\n-- @option o { type = "toggle" }\n', first.settings, _previous(first))

    assert not second.changed and second.settings == first.settings
    assert {n: r.index for n, r in second.resources.items()} == {"a": 0, "o": 0}


def test_a_resource_keeps_its_index_when_something_is_declared_before_it() -> None:
    first = _plan('-- @trait a { speed = "value_100" }\n')

    second = _plan('-- @trait new { speed = "value_120" }\n-- @trait a { speed = "value_100" }\n', first.settings, _previous(first))

    assert second.resources["a"].index == 0 and second.resources["new"].index == 1


def test_an_untouched_entry_is_refreshed_when_its_declaration_changes() -> None:
    first = _plan('-- @trait a { speed = "value_100" }\n')

    second = _plan('-- @trait a { speed = "value_150" }\n', first.settings, _previous(first))

    assert second.settings.scripted_player_traits[0].traits.movement.speed == "value_150" and second.changed


def test_an_entry_the_user_edited_is_left_alone_and_their_edit_wins() -> None:
    first = _plan('-- @trait a { name = "From code", speed = "value_100" }\n')
    edited = first.settings.model_copy(update={
        "scripted_player_traits": [first.settings.scripted_player_traits[0].model_copy(update={"name": "Renamed in RVT"})]
    })

    second = _plan('-- @trait a { name = "From code", speed = "value_150" }\n', edited, _previous(first))

    entry = second.settings.scripted_player_traits[0]
    assert entry.name == "Renamed in RVT" and entry.traits.movement.speed == "value_100"  # the module's change didn't land
    assert not second.changed
    assert second.resources["a"].digest == first.resources["a"].digest  # still what the linker wrote, so it stays an edit


def test_an_edit_that_stays_edited_is_still_left_alone_on_the_next_relink() -> None:
    first = _plan('-- @trait a { speed = "value_100" }\n')
    edited = first.settings.model_copy(update={
        "scripted_player_traits": [first.settings.scripted_player_traits[0].model_copy(update={"name": "mine"})]
    })
    second = _plan('-- @trait a { speed = "value_150" }\n', edited, _previous(first))

    third = _plan('-- @trait a { speed = "value_150" }\n', second.settings, _previous(second))

    assert third.settings.scripted_player_traits[0].name == "mine" and not third.changed


def test_a_removed_declaration_never_removes_its_entry() -> None:
    first = _plan('-- @trait a { speed = "value_100" }\n-- @trait b { speed = "value_120" }\n')

    second = _plan('-- @trait b { speed = "value_120" }\n', first.settings, _previous(first))

    assert len(second.settings.scripted_player_traits) == 2 and second.resources["b"].index == 1


def test_a_recorded_index_past_the_end_of_the_list_is_treated_as_new() -> None:
    plan = _plan('-- @trait a { speed = "value_100" }\n', ScriptSettings(), {"a": {"kind": "trait", "index": 5, "digest": "x"}})

    assert plan.resources["a"].index == 0


def test_a_recorded_entry_of_another_kind_is_treated_as_new() -> None:
    plan = _plan("-- @widget a { position = 2 }\n", ScriptSettings(), {"a": {"kind": "trait", "index": 0, "digest": "x"}})

    assert plan.resources["a"].kind == "widget"


@pytest.mark.parametrize(("kind", "capacity", "declaration"), [
    ("trait", 16, '-- @trait n{i} {{ speed = "value_100" }}\n'),
    ("option", 16, '-- @option n{i} {{ type = "toggle" }}\n'),
    ("widget", 4, "-- @widget n{i} {{ position = 1 }}\n"),
])
def test_a_table_that_is_full_is_reported_at_the_declaration_that_overflows_it(kind: str, capacity: int, declaration: str) -> None:
    text = "".join(declaration.format(i=i) for i in range(capacity + 1))

    plan = _plan(text)

    [problem] = plan.diagnostics
    assert (problem.code, problem.line) == ("resource-full", capacity + 1)
    assert f"at most {capacity}" in problem.message and len(plan.resources) == capacity


def test_a_duplicate_name_is_left_to_the_linter_and_the_first_wins() -> None:
    plan = _plan('-- @trait a { speed = "value_100" }\n-- @trait a { speed = "value_120" }\n')

    assert len(plan.settings.scripted_player_traits) == 1 and plan.diagnostics == []


def test_the_digest_depends_on_the_content_only() -> None:
    a = ScriptedHUDWidget(position=2)

    assert digest(a) == digest(ScriptedHUDWidget(position=2)) != digest(ScriptedHUDWidget(position=3))
