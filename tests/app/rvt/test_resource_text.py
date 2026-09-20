"""Names for declared trait sets and options: the native bindings they need, :mod:`in_reach.app.rvt.resource_text`, the
strings.json ownership in ``strings_writer.own_text`` and the option growth in ``settings_writer``."""
from pathlib import Path

import pytest

from in_reach.app.rvt import resource_text, rvt_bridge, settings_writer, strings_writer
from in_reach.app.rvt.models.script_settings import ScriptedOption, ScriptedOptionValue, ScriptSettings
from in_reach.app.rvt.resource_text import ResourceText, assign_resource_text, texts_from_link_map

_JUGGERNAUT_BIN = Path(__file__).parent / "resources" / "juggernaut" / "juggernaut.bin"

needs_native = pytest.mark.skipif(
    not (_JUGGERNAUT_BIN.is_file() and rvt_bridge.is_available()),
    reason="fixture .bin not present, or native _reachvarianttool extension not available on this platform",
)


@pytest.fixture
def mp():
    return rvt_bridge.get_rvt().load(str(_JUGGERNAUT_BIN)).multiplayer


# -- the native bindings -------------------------------------------------------------------------------------


@needs_native
def test_a_new_trait_set_shares_the_empty_string_and_can_be_given_one_of_its_own(mp) -> None:
    first, second = mp.add_scripted_player_traits(), mp.add_scripted_player_traits()
    assert first.name.empty() and second.name.empty()
    table = mp.script_strings
    before = len(table)

    own = table.add_new()
    own.text = "Fast"
    first.name = own

    assert first.name.text == "Fast" and second.name.empty()  # naming one did not name the other
    assert len(table) == before + 1


@needs_native
def test_the_description_of_a_trait_set_is_settable_too(mp) -> None:
    traits = mp.add_scripted_player_traits()
    string = mp.script_strings.add_new()
    string.text = "Runs faster"

    traits.desc = string

    assert traits.desc.text == "Runs faster"


@needs_native
def test_an_options_name_desc_and_value_names_are_settable(mp) -> None:
    option = mp.add_scripted_option()
    table = mp.script_strings
    for target, text in ((option, "Dev"), (option.value(0), "Off")):
        string = table.add_new()
        string.text = text
        target.name = string

    assert (option.name.text, option.value(0).name.text) == ("Dev", "Off")


@needs_native
def test_an_option_can_be_given_more_values(mp) -> None:
    option = mp.add_scripted_option()
    assert option.value_count == 1

    added = option.add_value()

    assert option.value_count == 2 and added.value == 0


@needs_native
def test_a_range_option_is_made_by_make_range_and_takes_no_values(mp) -> None:
    option = mp.add_scripted_option()
    assert option.range_default is None

    option.make_range()
    option.is_range = True

    assert option.range_default is not None and option.range_min is not None and option.range_max is not None
    with pytest.raises(RuntimeError, match="range option"):
        option.add_value()


@needs_native
def test_add_value_stops_at_the_engines_limit(mp) -> None:
    option = mp.add_scripted_option()
    with pytest.raises(RuntimeError):
        for _ in range(200):
            option.add_value()
    assert 2 <= option.value_count < 200


# -- giving declared entries their text ------------------------------------------------------------------------


@needs_native
def test_a_trait_set_is_named_by_its_alias_unless_it_says_otherwise(mp) -> None:
    mp.add_scripted_player_traits()
    mp.add_scripted_player_traits()
    base = mp.scripted_player_trait_count - 2

    result = assign_resource_text(mp, [
        ResourceText("trait", base, "t_fast"),
        ResourceText("trait", base + 1, "t_slow", name="Slow Down", desc="Half speed"),
    ])

    assert mp.scripted_player_trait(base).name.text == "t_fast" and mp.scripted_player_trait(base).desc.empty()
    assert (mp.scripted_player_trait(base + 1).name.text, mp.scripted_player_trait(base + 1).desc.text) == ("Slow Down", "Half speed")
    assert sorted(result.owned.values()) == ["Half speed", "Slow Down", "t_fast"]


@needs_native
def test_every_string_it_makes_is_its_own_and_recorded_by_index(mp) -> None:
    mp.add_scripted_player_traits()
    base = mp.scripted_player_trait_count - 1
    before = len(mp.script_strings)

    result = assign_resource_text(mp, [ResourceText("trait", base, "t_a", name="A", desc="B")])

    assert list(result.owned) == [before, before + 1]
    assert [mp.script_strings[i].text for i in result.owned] == ["A", "B"]


@needs_native
def test_a_toggle_gets_names_for_the_option_and_both_values(mp) -> None:
    option = mp.add_scripted_option()
    option.add_value()
    index = mp.scripted_option_count - 1

    assign_resource_text(mp, [ResourceText("option", index, "o_dev", values=("Off", "On"))])

    assert option.name.text == "o_dev" and [option.value(i).name.text for i in range(2)] == ["Off", "On"]


@needs_native
def test_a_name_the_variant_already_has_is_never_replaced(mp) -> None:
    existing = mp.scripted_player_trait(0)
    keep = existing.name.text
    assert keep  # the juggernaut base's own trait sets are named

    result = assign_resource_text(mp, [ResourceText("trait", 0, "t_a", name="Renamed")])

    assert existing.name.text == keep and result.owned == {}


@needs_native
def test_an_entry_the_variant_does_not_have_is_skipped(mp) -> None:
    assert assign_resource_text(mp, [ResourceText("trait", 99, "t_a"), ResourceText("option", 99, "o_a")]).owned == {}


@needs_native
def test_a_full_strings_table_is_reported_not_ignored(mp) -> None:
    traits = mp.add_scripted_player_traits()
    table = mp.script_strings
    while table.add_new() is not None:
        pass
    index = mp.scripted_player_trait_count - 1
    assert traits.name.empty()

    with pytest.raises(ValueError, match="strings table is full"):
        assign_resource_text(mp, [ResourceText("trait", index, "t_a")])


def test_texts_are_read_back_out_of_a_link_map() -> None:
    resources = {
        "t_fast": {"kind": "trait", "index": 2, "owner": "module m", "digest": "x"},
        "t_slow": {"kind": "trait", "index": 3, "owner": "module m", "digest": "x", "text": {"name": "Slow", "desc": "d"}},
        "o_dev": {"kind": "option", "index": 0, "owner": "module m", "digest": "x", "text": {"values": ["Off", "On"]}},
        "w_hud": {"kind": "widget", "index": 0, "owner": "module m", "digest": "x"},
    }

    assert texts_from_link_map(resources) == [
        ResourceText("trait", 2, "t_fast"),
        ResourceText("trait", 3, "t_slow", name="Slow", desc="d"),
        ResourceText("option", 0, "o_dev", values=("Off", "On")),
    ]  # a widget has no text


# -- strings.json ownership --------------------------------------------------------------------------------------


def _strings(*texts: str) -> dict:
    return {
        "meta": {"name": [], "description": [], "category": []}, "teams": [],
        "script_strings": [{"index": i, "text": {"english": t, "french": None}} for i, t in enumerate(texts)],
    }


def test_owned_text_replaces_what_strings_json_had_for_that_index() -> None:
    reconciled = strings_writer.StringReconciliation(_strings("a", "old", "c"))

    result = strings_writer.own_text(reconciled, {1: "new"})

    assert [e["text"]["english"] for e in result.strings["script_strings"]] == ["a", "new", "c"]
    assert result.updated == [1] and result.changed


def test_owned_text_leaves_other_languages_alone() -> None:
    strings = _strings("a")
    strings["script_strings"][0]["text"]["french"] = "un"

    result = strings_writer.own_text(strings_writer.StringReconciliation(strings), {0: "b"})

    assert result.strings["script_strings"][0]["text"] == {"english": "b", "french": "un"}


def test_owned_text_that_already_matches_changes_nothing() -> None:
    reconciled = strings_writer.StringReconciliation(_strings("a", "b"))

    result = strings_writer.own_text(reconciled, {1: "b"})

    assert result is reconciled and not result.changed


def test_owned_text_does_not_mutate_its_input() -> None:
    strings = _strings("a", "old")
    strings_writer.own_text(strings_writer.StringReconciliation(strings), {1: "new"})

    assert strings["script_strings"][1]["text"]["english"] == "old"


def test_updated_entries_count_as_a_change_alongside_added_and_removed() -> None:
    assert strings_writer.StringReconciliation({}, [], [], [3]).changed
    assert not strings_writer.StringReconciliation({}).changed


# -- growing options to match settings ---------------------------------------------------------------------------


@needs_native
def test_an_option_listed_with_two_values_is_grown_to_two(mp) -> None:
    rvt = rvt_bridge.get_rvt()
    entry = ScriptedOption(
        is_range=False, values=[ScriptedOptionValue(value=0), ScriptedOptionValue(value=1)], default_value_index=0, current_value_index=0
    )
    count = mp.scripted_option_count

    settings_writer.reconcile_script_tables(rvt, mp, _settings_with_option(mp, entry, count))

    assert mp.scripted_option(count).value_count == 2


@needs_native
def test_a_range_option_is_given_its_range_entries(mp) -> None:
    rvt = rvt_bridge.get_rvt()
    entry = ScriptedOption(
        is_range=True, values=[ScriptedOptionValue(value=0)], range_min=ScriptedOptionValue(value=1),
        range_max=ScriptedOptionValue(value=30), range_default=ScriptedOptionValue(value=10), range_current=10,
    )
    count = mp.scripted_option_count

    settings_writer.reconcile_script_tables(rvt, mp, _settings_with_option(mp, entry, count))

    assert mp.scripted_option(count).range_default is not None


@needs_native
def test_a_range_option_applies_whether_or_not_settings_list_its_placeholder_value(mp) -> None:
    """A saved-and-reloaded range option has no enum values but a fresh one has a placeholder, so the two can't be compared."""
    rvt = rvt_bridge.get_rvt()
    entry = ScriptedOption(
        is_range=True, values=[], range_min=ScriptedOptionValue(value=1), range_max=ScriptedOptionValue(value=30),
        range_default=ScriptedOptionValue(value=10), range_current=10,
    )
    count = mp.scripted_option_count
    settings = _settings_with_option(mp, entry, count)
    tables = settings_writer.reconcile_script_tables(rvt, mp, settings)

    settings_writer.apply_script_settings(mp, tables.script_settings)  # would raise "value count mismatch" before

    option = mp.scripted_option(count)
    assert option.is_range and option.range_max.value == 30


@needs_native
def test_an_enum_option_whose_value_count_disagrees_is_still_an_error(mp) -> None:
    option = mp.add_scripted_option()  # one value
    entry = ScriptedOption(is_range=False, values=[ScriptedOptionValue(value=0), ScriptedOptionValue(value=1)])

    with pytest.raises(ValueError, match="value count mismatch"):
        settings_writer._apply_scripted_option(option, entry)


def _settings_with_option(mp, entry: ScriptedOption, index: int) -> ScriptSettings:
    """The base variant's own script settings with ``entry`` appended as option number ``index``."""
    from in_reach.app.rvt.extraction import extract_game_settings

    variant = rvt_bridge.get_rvt().load(str(_JUGGERNAUT_BIN))
    current = extract_game_settings(variant, _JUGGERNAUT_BIN).multiplayer.script_settings
    options = [*current.scripted_options, entry]
    assert len(options) == index + 1
    return current.model_copy(update={"scripted_options": options})


def test_resource_text_module_has_no_native_dependency_at_import() -> None:
    assert resource_text.ResourceText("trait", 0, "a").name is None
