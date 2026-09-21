"""Engine resources declared in code (``@trait``/``@option``/``@widget``/``@label``) and how they reach
``settings/script_settings.json`` -- next_steps decision 2: modules write their own, hand-made entries are never
moved, and the user's edits win."""
import pytest

from in_reach.app.rvt.megalo_ast import parse_annotations
from in_reach.app.rvt.models.enums import MovementSpeed
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


def _with_speed(plan, speed: str) -> ScriptSettings:
    """``plan``'s settings with its first trait set's movement speed changed (a real edit, unlike its display text)."""
    trait = plan.settings.scripted_player_traits[0]
    traits = trait.traits.model_copy(update={"movement": trait.traits.movement.model_copy(update={"speed": MovementSpeed(speed)})})
    return plan.settings.model_copy(update={"scripted_player_traits": [trait.model_copy(update={"traits": traits})]})


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
    first = _plan('-- @trait a { speed = "value_100" }\n')
    edited = _with_speed(first, "value_200")  # what someone did to it in RVT

    second = _plan('-- @trait a { speed = "value_150" }\n', edited, _previous(first))

    entry = second.settings.scripted_player_traits[0]
    assert entry.traits.movement.speed == "value_200"  # the module's change didn't land
    assert not second.changed
    assert second.resources["a"].digest == first.resources["a"].digest  # still what the linker wrote, so it stays an edit


def test_an_edit_that_stays_edited_is_still_left_alone_on_the_next_relink() -> None:
    first = _plan('-- @trait a { speed = "value_100" }\n')
    edited = _with_speed(first, "value_200")
    second = _plan('-- @trait a { speed = "value_150" }\n', edited, _previous(first))

    third = _plan('-- @trait a { speed = "value_150" }\n', second.settings, _previous(second))

    assert third.settings.scripted_player_traits[0].traits.movement.speed == "value_200" and not third.changed


# -- display text is not an edit (a trait edited in the module stopped landing after a round trip through the .bin) --


def test_a_blanked_display_name_does_not_stop_the_module_changing_the_entry() -> None:
    """The regression: a resync from the ``.bin`` (Launch RVT) blanks a linker-made entry's ``name`` -- the compiler never
    writes it -- which used to make the entry look hand-edited, so the module's next change was ignored for good."""
    first = _plan('-- @trait a { speed = "value_120" }\n')
    round_tripped = first.settings.model_copy(update={
        "scripted_player_traits": [first.settings.scripted_player_traits[0].model_copy(update={"name": "", "desc": ""})]
    })

    second = _plan('-- @trait a { speed = "value_200" }\n', round_tripped, _previous(first))

    entry = second.settings.scripted_player_traits[0]
    assert entry.traits.movement.speed == "value_200" and second.changed
    assert entry.name == ""  # the text stays as it was: it isn't the module's to reset


def test_display_text_changed_by_hand_survives_a_refresh_from_the_module() -> None:
    first = _plan('-- @trait a { name = "From code", speed = "value_100" }\n')
    renamed = first.settings.model_copy(update={
        "scripted_player_traits": [first.settings.scripted_player_traits[0].model_copy(update={"name": "My name"})]
    })

    second = _plan('-- @trait a { name = "From code", speed = "value_150" }\n', renamed, _previous(first))

    entry = second.settings.scripted_player_traits[0]
    assert (entry.name, entry.traits.movement.speed) == ("My name", "value_150")


def test_the_digest_ignores_names_and_descriptions_at_any_depth() -> None:
    a = _plan('-- @option o { type = "toggle", name = "One" }\n').settings.scripted_options[0]
    b = a.model_copy(update={"name": "Two", "desc": "other", "values": [v.model_copy(update={"name": "x"}) for v in a.values]})

    assert digest(a) == digest(b) and digest(a).startswith("2:")


def test_a_digest_from_before_the_versioned_form_is_adopted_once() -> None:
    first = _plan('-- @trait a { speed = "value_100" }\n')
    legacy = {"a": {"kind": "trait", "index": 0, "digest": "0123456789abcdef"}}  # what the first release wrote

    second = _plan('-- @trait a { speed = "value_150" }\n', first.settings, legacy)

    assert second.settings.scripted_player_traits[0].traits.movement.speed == "value_150"
    assert second.resources["a"].digest.startswith("2:")


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


# -- range options, and the text a declaration asks for ----------------------------------------------------------


def test_a_range_options_placeholder_enum_values_are_not_part_of_its_digest() -> None:
    """A saved-and-reloaded range option has no enum values while a freshly built one has a placeholder: not an edit."""
    built = _plan('-- @option o { type = "range", min = 1, max = 30, default = 10 }\n').settings.scripted_options[0]

    assert built.values and digest(built) == digest(built.model_copy(update={"values": []}))


def test_an_enum_options_values_are_part_of_its_digest() -> None:
    built = _plan('-- @option o { type = "toggle" }\n').settings.scripted_options[0]

    assert digest(built) != digest(built.model_copy(update={"values": built.values[:1]}))


def test_a_range_option_built_from_a_declaration_keeps_one_placeholder_value() -> None:
    [option] = _plan('-- @option o { type = "range", min = 1, max = 5, default = 3 }\n').settings.scripted_options

    assert option.is_range and len(option.values) == 1  # what the engine creates, so the two agree


def test_the_text_a_declaration_asks_for_is_recorded_for_the_compile() -> None:
    plan = _plan(
        '-- @trait t_a { name = "Fast", desc = "Runs faster", speed = "value_120" }\n'
        '-- @trait t_b { speed = "value_100" }\n'
        '-- @option o_a { type = "toggle" }\n'
        '-- @option o_r { type = "range", min = 1, max = 3, default = 2, name = "Minutes" }\n'
        "-- @widget w { position = 1 }\n"
    )

    info = plan.resources
    assert (info["t_a"].label, info["t_a"].note) == ("Fast", "Runs faster")
    assert (info["t_b"].label, info["t_b"].note, info["t_b"].values) == (None, None, ())
    assert info["o_a"].values == ("Off", "On") and info["o_a"].label is None
    assert info["o_r"].label == "Minutes" and info["o_r"].values == ()  # a range option has no enum values to name
    assert (info["w"].label, info["w"].values) == (None, ())
