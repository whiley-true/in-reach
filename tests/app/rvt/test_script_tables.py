"""Script-defined tables -- HUD widgets, trait sets, stats, options -- and timer rates.

Before the native extension gained the bindings these need, a variant could only ever use the entries
it was loaded with: ``WidgetArgument``/``PlayerTraitsArgument`` had no way to be pointed at an entry,
nothing could append one (native ``compile_script()`` fails with "Index N is out of bounds", unlike
forge labels, which it creates on first mention), and ``TimerRateArgument.value`` had no setter. So a
project started from a blank variant couldn't use a widget, a trait set, a stat, an option or an
arbitrary timer rate at all.

Four layers, tested in order:

- the native bindings themselves (``add_scripted_*``, ``set_value``, a writable ``TimerRateArgument.
  value``) -- including that a variant with entries created this way survives a save and reload;
- :mod:`~in_reach.app.rvt.megalo_compiler` making sure the entries a script refers to exist;
- :func:`~in_reach.app.rvt.settings_writer.reconcile_script_tables` keeping ``settings/`` and the
  variant in step *from either side*; and
- :func:`~in_reach.app.rvt.compile.run_compile` writing the result back.
"""
import json
import tempfile
from pathlib import Path

import pytest

from in_reach.app import apply_settings, new_project, project
from in_reach.app.blank_variant import resolve_blank_variant
from in_reach.app.rvt import compile as compile_module
from in_reach.app.rvt import megalo_compiler, rvt_bridge, settings_writer, template_source
from in_reach.app.rvt.decompile import normalize_script_text
from in_reach.app.rvt.models.script_settings import ScriptedHUDWidget, ScriptSettings

pytestmark = pytest.mark.skipif(
    not rvt_bridge.is_available(), reason="native _reachvarianttool extension not available on this platform"
)

#: name -> (count attribute, add method, accessor, the engine's cap)
_TABLES = {
    "option": ("scripted_option_count", "add_scripted_option", "scripted_option", 16),
    "traits": ("scripted_player_trait_count", "add_scripted_player_traits", "scripted_player_trait", 16),
    "stat": ("scripted_stat_count", "add_scripted_stat", "scripted_stat", 4),
    "widget": ("scripted_hud_widget_count", "add_scripted_hud_widget", "scripted_hud_widget", 4),
}


@pytest.fixture(scope="module")
def rvt():
    return rvt_bridge.get_rvt()


@pytest.fixture
def blank(rvt):
    return rvt.load(str(resolve_blank_variant(firefight=False)))


def _counts(mp) -> dict[str, int]:
    return {name: getattr(mp, attrs[0]) for name, attrs in _TABLES.items()}


def _reload(rvt, variant):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "out.bin"
        variant.save(str(path))
        return rvt.load(str(path))


def _timer_rate_arg(rvt):
    function = megalo_compiler._find_function(rvt, name="Set Timer Rate", condition=False)
    typeinfo = next(a.typeinfo for a in function.arguments if a.typeinfo.internal_name == "_timer_rate")
    return typeinfo.create()


def _compile(rvt, variant, source: str) -> str:
    """Compiles in-house (with the pool, as a project would) and returns the decompiled result after a
    real save and reload."""
    megalo_compiler.compile_script(rvt, variant, source, template_pool=lambda: template_source.build_variants(rvt))
    return normalize_script_text(_reload(rvt, variant).decompile_script())


# -- the native bindings ---------------------------------------------------------------------------


def test_a_blank_variant_has_none_of_them(blank) -> None:
    assert _counts(blank.multiplayer) == {"option": 0, "traits": 0, "stat": 0, "widget": 0}


@pytest.mark.parametrize("table", list(_TABLES))
def test_each_add_method_appends_one_and_returns_it(blank, table) -> None:
    count_attr, add_method, accessor, _ = _TABLES[table]
    mp = blank.multiplayer
    first = getattr(mp, add_method)()
    getattr(mp, add_method)()
    assert getattr(mp, count_attr) == 2
    assert getattr(mp, accessor)(0) is not None and first is not None


@pytest.mark.parametrize("table", list(_TABLES))
def test_each_table_stops_at_the_engines_cap_with_a_clear_error(blank, table) -> None:
    count_attr, add_method, _, cap = _TABLES[table]
    mp = blank.multiplayer
    for _ in range(cap):
        getattr(mp, add_method)()
    with pytest.raises(RuntimeError, match=r"Cannot add .*reached"):
        getattr(mp, add_method)()
    assert getattr(mp, count_attr) == cap


def test_a_variant_with_every_table_full_saves_and_loads_back_intact(rvt, blank) -> None:
    mp = blank.multiplayer
    for _, (_, add_method, _, cap) in _TABLES.items():
        for _ in range(cap):
            getattr(mp, add_method)()
    reloaded = _reload(rvt, blank)
    assert _counts(reloaded.multiplayer) == {"option": 16, "traits": 16, "stat": 4, "widget": 4}


def test_a_created_option_is_a_valid_enum_option_with_its_one_required_value(blank) -> None:
    option = blank.multiplayer.add_scripted_option()
    assert option.value_count == 1  # "enum-options must have at least one value" -- the engine's own default


def test_created_entries_are_editable_through_the_returned_reference(rvt, blank) -> None:
    widget = blank.multiplayer.add_scripted_hud_widget()
    widget.position = 7
    assert _reload(rvt, blank).multiplayer.scripted_hud_widget(0).position == 7


def test_a_timer_rate_can_be_set_by_its_table_index(rvt) -> None:
    arg = _timer_rate_arg(rvt)
    variant = rvt.load(str(resolve_blank_variant(firefight=False)))
    for index, text in ((0, "0%"), (1, "-10%"), (5, "-100%"), (14, "10%"), (26, "1000%")):
        arg.value = index
        assert arg.decompile(variant) == text


def test_the_widget_and_traits_arguments_can_be_pointed_at_an_entry(rvt, blank) -> None:
    mp = blank.multiplayer
    mp.add_scripted_hud_widget()
    mp.add_scripted_hud_widget()
    mp.add_scripted_player_traits()
    widget_ti = next(a.typeinfo for a in megalo_compiler._find_function(rvt, name="Set Widget Text", condition=False).arguments if a.typeinfo.internal_name == "script_widget")
    traits_ti = next(a.typeinfo for a in megalo_compiler._find_function(rvt, name="Apply Player Traits", condition=False).arguments if a.typeinfo.internal_name == "script_traits")
    widget, traits = widget_ti.create(), traits_ti.create()
    assert widget.value is None and traits.value is None

    widget.set_value(mp, 1)
    traits.set_value(mp, 0)

    assert widget.decompile(blank) == "script_widget[1]"
    assert traits.decompile(blank) == "script_traits[0]"
    assert widget.value is not None and traits.value is not None


def test_pointing_an_argument_past_the_end_of_its_table_is_an_index_error_not_a_crash(rvt, blank) -> None:
    widget_ti = next(a.typeinfo for a in megalo_compiler._find_function(rvt, name="Set Widget Text", condition=False).arguments if a.typeinfo.internal_name == "script_widget")
    with pytest.raises(IndexError):
        widget_ti.create().set_value(blank.multiplayer, 0)


# -- the compiler makes sure what a script refers to exists ----------------------------------------------


def test_a_trait_set_the_script_applies_is_created_up_to_the_index_it_names(rvt, blank) -> None:
    text = _compile(rvt, blank, "for each player do\n   current_player.apply_traits(script_traits[2])\nend\n")
    assert "current_player.apply_traits(script_traits[2])" in text
    assert blank.multiplayer.scripted_player_trait_count == 3


def test_a_widget_the_script_drives_is_created(rvt, blank) -> None:
    text = _compile(rvt, blank, "for each player do\n   script_widget[1].set_visibility(current_player, true)\nend\n")
    assert "script_widget[1].set_visibility(current_player, true)" in text
    assert blank.multiplayer.scripted_hud_widget_count == 2


def test_a_per_player_stat_the_script_writes_is_created(rvt, blank) -> None:
    text = _compile(rvt, blank, "for each player do\n   current_player.script_stat[1] = current_player.number[0]\nend\n")
    assert "current_player.script_stat[1] = current_player.number[0]" in text
    assert blank.multiplayer.scripted_stat_count == 2


def test_an_option_the_script_reads_is_created(rvt, blank) -> None:
    text = _compile(rvt, blank, "global.number[0] = script_option[3]\n")
    assert "global.number[0] = script_option[3]" in text
    assert blank.multiplayer.scripted_option_count == 4


def test_the_highest_index_referenced_sets_how_many_are_made(rvt, blank) -> None:
    source = (
        "for each player do\n"
        "   script_widget[0].set_visibility(current_player, true)\n"
        "   script_widget[3].set_visibility(current_player, false)\n"
        "end\n"
    )
    _compile(rvt, blank, source)
    assert blank.multiplayer.scripted_hud_widget_count == 4


def test_referring_to_an_entry_the_variant_already_has_creates_nothing_more(rvt) -> None:
    variant = rvt.load(str(resolve_blank_variant(firefight=False)))
    for _ in range(3):
        variant.multiplayer.add_scripted_hud_widget()
    _compile(rvt, variant, "for each player do\n   script_widget[1].set_visibility(current_player, true)\nend\n")
    assert variant.multiplayer.scripted_hud_widget_count == 3


@pytest.mark.parametrize(
    "source, message",
    [
        ("for each player do\n   script_widget[4].set_visibility(current_player, true)\nend\n", r"script_widget\[4\] is out of range \(a variant can have at most 4\)"),
        ("for each player do\n   current_player.apply_traits(script_traits[16])\nend\n", r"script_traits\[16\] is out of range"),
        ("for each player do\n   current_player.script_stat[4] = 1\nend\n", r"script_stat\[4\] is out of range"),
        ("global.number[0] = script_option[16]\n", "out of range"),
    ],
)
def test_an_index_past_the_engines_cap_is_unsupported_with_a_clear_message(rvt, blank, source, message) -> None:
    with pytest.raises(megalo_compiler.UnsupportedConstruct, match=message):
        megalo_compiler.compile_script(rvt, blank, source, template_pool=lambda: template_source.build_variants(rvt))


def test_a_negative_table_index_is_unsupported(rvt, blank) -> None:
    source = "for each player do\n   script_widget[-1].set_visibility(current_player, true)\nend\n"
    with pytest.raises(megalo_compiler.UnsupportedConstruct):
        megalo_compiler.compile_script(rvt, blank, source, template_pool=lambda: template_source.build_variants(rvt))


def test_only_the_current_players_stats_can_be_built_directly(rvt, blank) -> None:
    """A team's stat is a different scope with the *same* format string, so it can't be told apart
    from a player's; any other owner's ``which`` isn't derivable. Both still need a base example."""
    source = "for each team do\n   current_team.script_stat[0] = 1\nend\n"
    with pytest.raises(megalo_compiler.UnsupportedConstruct):
        megalo_compiler.compile_script(rvt, blank, source, template_pool=lambda: template_source.build_variants(rvt))


def test_the_widget_needs_a_variable_template_only_for_what_it_takes_not_for_itself(rvt, blank) -> None:
    """No base example of a widget exists in a blank variant -- the reference is built, not copied."""
    own = megalo_compiler._scan_templates(rvt, blank, blank.multiplayer)
    assert not any(t in ("script_widget", "script_traits") for t, _ in own.variables)
    _compile(rvt, blank, "for each player do\n   script_widget[0].set_visibility(current_player, true)\nend\n")


# -- timer rates: found by search now, not cloned ----------------------------------------------------------


@pytest.mark.parametrize("rate", [-1000, -500, -150, -100, -10, 0, 10, 50, 100, 175, 1000])
def test_every_supported_rate_compiles_from_a_blank_base(rvt, blank, rate) -> None:
    text = _compile(rvt, blank, f"for each player do\n   current_player.timer[0].set_rate({rate}%)\nend\n")
    assert f"set_rate({rate}%)" in text


@pytest.mark.parametrize("rate", [-1001, -200 - 1, 1, 20, 99, 101, 1001, 5000])
def test_a_rate_the_engine_has_no_slot_for_is_unsupported(rvt, blank, rate) -> None:
    source = f"for each player do\n   current_player.timer[0].set_rate({rate}%)\nend\n"
    with pytest.raises(megalo_compiler.UnsupportedConstruct):
        megalo_compiler.compile_script(rvt, blank, source, template_pool=lambda: template_source.build_variants(rvt))


def test_zero_percent_resolves_to_its_real_index_not_a_wrapped_one(rvt, blank) -> None:
    """Indexes 27-31 read past the end of the engine's 27-entry table and can decompile as ``0%`` by
    luck; the search must stop at 27 so the real slot (0) is what gets used."""
    assert megalo_compiler._ENUM_VALUE_LIMITS["_timer_rate"] == 27
    compiler = megalo_compiler._Compiler(rvt, blank)
    arg = _timer_rate_arg(rvt)
    assert compiler._enum_value_of(arg.__class__ and _timer_rate_typeinfo(rvt), arg, "0%") == 0


def _timer_rate_typeinfo(rvt):
    function = megalo_compiler._find_function(rvt, name="Set Timer Rate", condition=False)
    return next(a.typeinfo for a in function.arguments if a.typeinfo.internal_name == "_timer_rate")


# -- settings/script_settings.json and the variant, from either side --------------------------------------


def _settings(**lists) -> ScriptSettings:
    return ScriptSettings(**lists)


def test_entries_the_script_created_are_added_to_settings_with_their_real_defaults(rvt, blank) -> None:
    _compile(rvt, blank, "for each player do\n   script_widget[1].set_visibility(current_player, true)\nend\n")
    result = settings_writer.reconcile_script_tables(rvt, blank.multiplayer, _settings())
    assert result.added == {"scripted_hud_widgets": 2}
    assert result.script_settings.scripted_hud_widgets == [ScriptedHUDWidget(), ScriptedHUDWidget()]
    assert result.changed is True and result.created == {}


def test_every_table_reconciles_at_once(rvt, blank) -> None:
    source = (
        "for each player do\n"
        "   current_player.apply_traits(script_traits[0])\n"
        "   script_widget[0].set_visibility(current_player, true)\n"
        "   current_player.script_stat[0] = script_option[1]\n"
        "end\n"
    )
    _compile(rvt, blank, source)
    result = settings_writer.reconcile_script_tables(rvt, blank.multiplayer, _settings())
    assert result.added == {
        "scripted_options": 2, "scripted_player_traits": 1, "scripted_stats": 1, "scripted_hud_widgets": 1,
    }


def test_entries_settings_defines_are_created_in_the_variant(rvt, blank) -> None:
    settings = _settings(scripted_hud_widgets=[ScriptedHUDWidget(position=3), ScriptedHUDWidget(position=5)])
    result = settings_writer.reconcile_script_tables(rvt, blank.multiplayer, settings)
    assert blank.multiplayer.scripted_hud_widget_count == 2
    assert result.created == {"scripted_hud_widgets": 2}
    assert result.added == {} and result.changed is False
    assert result.script_settings is settings  # nothing to write back: settings already had them


def test_settings_that_lists_fewer_than_the_script_made_is_extended_and_keeps_what_it_had(rvt, blank) -> None:
    _compile(rvt, blank, "for each player do\n   script_widget[2].set_visibility(current_player, true)\nend\n")
    mine = ScriptedHUDWidget(position=9)
    result = settings_writer.reconcile_script_tables(rvt, blank.multiplayer, _settings(scripted_hud_widgets=[mine]))
    assert result.script_settings.scripted_hud_widgets[0] == mine
    assert len(result.script_settings.scripted_hud_widgets) == 3
    assert result.added == {"scripted_hud_widgets": 2}


def test_settings_lists_win_when_they_list_more_than_the_script_needs(rvt, blank) -> None:
    _compile(rvt, blank, "for each player do\n   script_widget[0].set_visibility(current_player, true)\nend\n")
    settings = _settings(scripted_hud_widgets=[ScriptedHUDWidget(), ScriptedHUDWidget(), ScriptedHUDWidget()])
    result = settings_writer.reconcile_script_tables(rvt, blank.multiplayer, settings)
    assert blank.multiplayer.scripted_hud_widget_count == 3
    assert result.created == {"scripted_hud_widgets": 2}


def test_nothing_is_ever_dropped_from_settings(rvt, blank) -> None:
    """Unlike a forge label, an entry here is either one the user listed or one a script still uses --
    so a script that stops referring to a widget leaves it in settings."""
    settings = _settings(scripted_hud_widgets=[ScriptedHUDWidget(position=4)])
    settings_writer.reconcile_script_tables(rvt, blank.multiplayer, settings)  # variant grows to 1
    fresh = rvt.load(str(resolve_blank_variant(firefight=False)))
    result = settings_writer.reconcile_script_tables(rvt, fresh.multiplayer, settings)  # script uses none
    assert result.script_settings.scripted_hud_widgets == [ScriptedHUDWidget(position=4)]
    assert fresh.multiplayer.scripted_hud_widget_count == 1


def test_a_settings_list_past_the_engines_cap_is_a_clear_error(rvt, blank) -> None:
    settings = _settings(scripted_hud_widgets=[ScriptedHUDWidget() for _ in range(5)])
    with pytest.raises(ValueError, match=r"scripted_hud_widgets lists 5 entries, but Cannot add HUD widget"):
        settings_writer.reconcile_script_tables(rvt, blank.multiplayer, settings)


def test_matching_lists_change_nothing_and_return_the_same_object(rvt, blank) -> None:
    settings = _settings()
    result = settings_writer.reconcile_script_tables(rvt, blank.multiplayer, settings)
    assert result.script_settings is settings and not result.changed and result.created == {}


def test_the_input_settings_are_never_mutated(rvt, blank) -> None:
    _compile(rvt, blank, "for each player do\n   script_widget[0].set_visibility(current_player, true)\nend\n")
    settings = _settings()
    settings_writer.reconcile_script_tables(rvt, blank.multiplayer, settings)
    assert settings.scripted_hud_widgets == []


def test_applying_the_reconciled_settings_no_longer_trips_the_length_check(rvt, blank) -> None:
    """The failure this all exists to prevent: 'script_settings.scripted_hud_widgets has 0 entries, but
    this variant has N' (see apply_script_settings)."""
    _compile(rvt, blank, "for each player do\n   script_widget[1].set_visibility(current_player, true)\nend\n")
    with pytest.raises(ValueError, match="scripted_hud_widgets has 0 entries"):
        settings_writer.apply_script_settings(blank.multiplayer, _settings())
    reconciled = settings_writer.reconcile_script_tables(rvt, blank.multiplayer, _settings())
    settings_writer.apply_script_settings(blank.multiplayer, reconciled.script_settings)


def test_edits_to_a_created_entry_in_settings_reach_the_variant(rvt, blank) -> None:
    settings = _settings(scripted_hud_widgets=[ScriptedHUDWidget(position=6)])
    reconciled = settings_writer.reconcile_script_tables(rvt, blank.multiplayer, settings)
    settings_writer.apply_script_settings(blank.multiplayer, reconciled.script_settings)
    assert blank.multiplayer.scripted_hud_widget(0).position == 6


# -- through compile.run_compile() -----------------------------------------------------------------------------


_SCRIPT = (
    "for each player do\n"
    "   current_player.apply_traits(script_traits[1])\n"
    "   script_widget[0].set_visibility(current_player, true)\n"
    "   current_player.script_stat[1] = script_option[2]\n"
    "   current_player.timer[0].set_rate(-150%)\n"
    "end\n"
)


def _project(tmp_path: Path, script: str) -> tuple[Path, Path]:
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir(parents=True)
    folder, warning = new_project.create_gametype_project(
        project_dir, "Tables Test", source_variant=resolve_blank_variant(firefight=False)
    )
    assert warning is None
    (folder / "script" / "output.txt").write_text(script, encoding="utf-8")
    return project_dir, folder


def _script_settings(folder: Path) -> dict:
    return json.loads((folder / "settings" / "script_settings.json").read_text(encoding="utf-8"))


def _write_script_settings(folder: Path, data: dict) -> None:
    (folder / "settings" / "script_settings.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_a_blank_project_using_every_kind_of_table_entry_now_builds_in_house(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, _SCRIPT)

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is True, compile_module.format_build_result(result)
    mp = rvt_bridge.get_rvt().load(str(result.output_path)).multiplayer
    assert _counts(mp) == {"option": 3, "traits": 2, "stat": 2, "widget": 1}
    assert "declare " not in rvt_bridge.get_rvt().load(str(result.output_path)).decompile_script()  # native would declare


def test_settings_lists_exactly_what_the_script_created(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, _SCRIPT)
    compile_module.run_compile(project_dir, folder, save=True)
    data = _script_settings(folder)
    assert {k: len(data[k]) for k in ("scripted_options", "scripted_player_traits", "scripted_stats", "scripted_hud_widgets")} == {
        "scripted_options": 3, "scripted_player_traits": 2, "scripted_stats": 2, "scripted_hud_widgets": 1,
    }


def test_apply_is_not_left_reading_unapplied(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, _SCRIPT)
    compile_module.run_compile(project_dir, folder, save=True)
    assert apply_settings.settings_have_unapplied_changes(folder) is False


def test_the_build_says_what_it_added(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, _SCRIPT)
    notices = [n.text for n in compile_module.run_compile(project_dir, folder, save=True).notices]
    assert "Added 3 scripted_options entries to script_settings.json" in notices
    assert "Added 1 scripted_hud_widgets entry to script_settings.json" in notices


def test_applying_again_is_stable(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, _SCRIPT)
    compile_module.run_compile(project_dir, folder, save=True)
    before = (folder / "settings" / "script_settings.json").read_bytes()

    second = compile_module.run_compile(project_dir, folder, save=True)

    assert second.success is True
    assert (folder / "settings" / "script_settings.json").read_bytes() == before
    assert not any("Added" in n.text for n in second.notices)


def test_an_entry_listed_only_in_settings_is_created_in_the_variant(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, _SCRIPT)
    compile_module.run_compile(project_dir, folder, save=True)
    data = _script_settings(folder)
    data["scripted_hud_widgets"].append({"position": 8})
    _write_script_settings(folder, data)

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is True, compile_module.format_build_result(result)
    mp = rvt_bridge.get_rvt().load(str(result.output_path)).multiplayer
    assert mp.scripted_hud_widget_count == 2 and mp.scripted_hud_widget(1).position == 8
    assert _script_settings(folder)["scripted_hud_widgets"][1]["position"] == 8
    assert apply_settings.settings_have_unapplied_changes(folder) is False


def test_edits_a_user_makes_to_a_created_entry_survive_every_later_apply(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, _SCRIPT)
    compile_module.run_compile(project_dir, folder, save=True)
    data = _script_settings(folder)
    data["scripted_hud_widgets"][0]["position"] = 4
    _write_script_settings(folder, data)

    compile_module.run_compile(project_dir, folder, save=True)
    compile_module.run_compile(project_dir, folder, save=True)

    assert _script_settings(folder)["scripted_hud_widgets"][0]["position"] == 4


def test_a_script_that_grows_past_the_settings_list_extends_it(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, "for each player do\n   script_widget[0].set_visibility(current_player, true)\nend\n")
    compile_module.run_compile(project_dir, folder, save=True)
    (folder / "script" / "output.txt").write_text(
        "for each player do\n   script_widget[3].set_visibility(current_player, true)\nend\n", encoding="utf-8"
    )

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is True, compile_module.format_build_result(result)
    assert len(_script_settings(folder)["scripted_hud_widgets"]) == 4


def test_a_script_that_stops_using_an_entry_leaves_it_in_settings(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, _SCRIPT)
    compile_module.run_compile(project_dir, folder, save=True)
    (folder / "script" / "output.txt").write_text("game.end_round()\n", encoding="utf-8")

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is True, compile_module.format_build_result(result)
    assert len(_script_settings(folder)["scripted_hud_widgets"]) == 1  # the user's to keep or delete
    assert apply_settings.settings_have_unapplied_changes(folder) is False


def test_a_dry_run_writes_nothing_into_settings(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, _SCRIPT)
    before = (folder / "settings" / "script_settings.json").read_bytes()
    result = compile_module.run_compile(project_dir, folder, save=False)
    assert result.success is True
    assert (folder / "settings" / "script_settings.json").read_bytes() == before


def test_too_many_entries_in_settings_fails_clearly_and_touches_nothing(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, "game.end_round()\n")
    data = _script_settings(folder)
    data["scripted_hud_widgets"] = [{"position": 0}] * 5
    _write_script_settings(folder, data)
    before = (folder / "settings" / "script_settings.json").read_bytes()

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is False
    assert "scripted_hud_widgets lists 5 entries" in compile_module.format_build_result(result)
    assert (folder / "settings" / "script_settings.json").read_bytes() == before


def test_a_timer_rate_from_the_engines_table_builds_in_a_blank_project(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, "for each player do\n   current_player.timer[0].set_rate(-175%)\nend\n")
    result = compile_module.run_compile(project_dir, folder, save=True)
    assert result.success is True, compile_module.format_build_result(result)
    assert "set_rate(-175%)" in rvt_bridge.get_rvt().load(str(result.output_path)).decompile_script()


def test_an_options_hidden_flag_in_settings_is_not_undone_by_creating_the_option(tmp_path: Path) -> None:
    """Regression: creating an option resets its own "disabled"/"hidden" visibility bits, so growing
    the variant *after* ``option_visibility`` had been applied from settings.json silently cleared the
    bit -- and the build then differed from settings forever (Apply stuck on "unapplied"). Growing
    first, before applying anything from settings/, is what keeps it."""
    project_dir, folder = _project(tmp_path, "global.number[0] = script_option[0]\n")
    compile_module.run_compile(project_dir, folder, save=True)  # creates option 0 and lists it in settings
    settings_path = folder / "settings" / "settings.json"
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    data["multiplayer"]["game_settings"]["option_visibility"]["megalo_options_hidden"] = [0]
    settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    (folder / "script" / "output.txt").write_text("game.end_round()\n", encoding="utf-8")  # no longer refers to it

    result = compile_module.run_compile(project_dir, folder, save=True)  # ...so settings alone creates it now

    assert result.success is True, compile_module.format_build_result(result)
    built = json.loads((folder / "build" / "settings.autogenerated.json").read_text(encoding="utf-8"))
    assert built["multiplayer"]["game_settings"]["option_visibility"]["megalo_options_hidden"] == [0]
    assert apply_settings.settings_have_unapplied_changes(folder) is False
