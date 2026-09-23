"""A linked project (``script/project.toml``) through the real compile: the linker runs first, the compiler builds
what it wrote, and a problem in the built script is reported at the source file and line that caused it."""
import json
import sys
from pathlib import Path

import pytest

from in_reach.app import new_project, project
from in_reach.app.rvt import compile as compile_module
from in_reach.app.rvt import rvt_bridge

_JUGGERNAUT_BIN = Path(__file__).parent / "resources" / "juggernaut" / "juggernaut.bin"
sys.path.insert(0, str(Path(__file__).parents[1] / "script_project"))
from hill_project import hill_rush  # noqa: E402  (a shared fixture that lives with the script-project tests)

pytestmark = pytest.mark.skipif(
    not (_JUGGERNAUT_BIN.is_file() and rvt_bridge.is_available()),
    reason="fixture .bin not present, or native _reachvarianttool extension not available on this platform",
)


# The design's example with fragment bodies the compiler accepts (its own are placeholders).
_PLAYABLE = {
    "modules__hill_score__hill_score_dot_mgl": (
        "-- @ptimer p_hill_timer default=${score_interval}\n-- @fragment HILL_PASS.score\n-- @loop player\n"
        "current_player.score += 1\n"
    ),
    "modules__hill_buff__hill_buff_dot_mgl": (
        '-- @trait t_hill_buff { movement_speed = "value_120" }\n-- @fragment HILL_PASS.buff\n-- @loop player\n'
        "-- @if DEV\ncurrent_player.apply_traits(t_hill_buff)\n-- @end\n"
    ),
}


def _new_project(tmp_path: Path) -> tuple[Path, Path]:
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir(parents=True)
    folder, warning = new_project.create_gametype_project(project_dir, "Linked", source_variant=_JUGGERNAUT_BIN)
    assert warning is None
    return project_dir, folder


def test_a_linked_project_builds_from_its_blocks_and_modules(tmp_path: Path) -> None:
    project_dir, folder = _new_project(tmp_path)
    hill_rush(folder, **_PLAYABLE)

    result = compile_module._run_compile_in_process(project_dir, folder, save=True)

    assert result.success, compile_module.format_build_result(result)
    assert (folder / "build" / "Compiled.txt").is_file()
    assert json.loads((folder / "build" / "link_map.json").read_text(encoding="utf-8"))["order"] == ["SETUP", "HILL_PASS", "WIN_CHECK"]
    settings = json.loads((folder / "settings" / "script_settings.json").read_text(encoding="utf-8"))
    assert "t_hill_buff" in [t["name"] for t in settings["scripted_player_traits"]]
    variant = rvt_bridge.get_rvt().load(str(result.output_path))
    assert variant.multiplayer.scripted_player_trait_count == 3  # the base's two, then the module's
    assert '"index": 2' in (folder / "build" / "link_map.json").read_text(encoding="utf-8")
    text = variant.decompile_script().replace("\r\n", "\n")
    assert "game.end_round()" in text
    # the two modules' fragments were fused: one player loop carries both
    assert "for each player do\n   current_player.score += 1\n   current_player.apply_traits(script_traits[2])\nend" in text


def test_the_script_the_project_was_linked_from_is_not_output_txt(tmp_path: Path) -> None:
    project_dir, folder = _new_project(tmp_path)
    hill_rush(folder, **_PLAYABLE)
    (folder / "script" / "output.txt").write_text("this is not even Megalo\n", encoding="utf-8")

    result = compile_module._run_compile_in_process(project_dir, folder, save=False)

    assert result.success, compile_module.format_build_result(result)


def test_a_project_that_does_not_link_fails_with_located_messages(tmp_path: Path) -> None:
    project_dir, folder = _new_project(tmp_path)
    hill_rush(folder, **_PLAYABLE, blocks__setup_dot_mgl="-- @number a\n-- @number a\n")

    result = compile_module._run_compile_in_process(project_dir, folder, save=True)

    assert not result.success and result.output_path is None
    [error] = [e for e in result.errors if "IR006" in e.text]
    assert (error.file, error.line) == ("blocks/setup.mgl", 2)
    assert "blocks/setup.mgl:2:" in compile_module.format_build_result(result)
    assert not (folder / "build" / "Compiled.txt").exists()


def test_a_compile_error_is_reported_at_the_source_line_that_caused_it(tmp_path: Path) -> None:
    project_dir, folder = _new_project(tmp_path)
    hill_rush(folder, **_PLAYABLE, blocks__win_check_dot_mgl="-- @doc ends the game\n\nif global.number[0] == 5 then\n   game.no_such_action()\nend\n")

    result = compile_module._run_compile_in_process(project_dir, folder, save=False)

    assert not result.success
    [error] = result.errors  # the trait the module declares exists by now, so nothing else is reported
    assert (error.file, error.line) == ("blocks/win_check.mgl", 4)
    assert "no_such_action" in error.text


def test_a_lines_the_linker_wrote_itself_stay_messages_about_compiled_txt() -> None:
    link_map = {"source_lines": [{"compiled": 10, "file": "blocks/a.mgl", "source": 3, "count": 2}]}
    messages = [
        compile_module.BuildMessage(line=11, col=4, text="in a run"),
        compile_module.BuildMessage(line=2, col=1, text="a declare"),
    ]

    moved = compile_module._relocate(messages, link_map)

    assert [(m.file, m.line) for m in moved] == [("blocks/a.mgl", 4), ("../build/Compiled.txt", 2)]
    assert compile_module._relocate(messages, None) is messages


def test_a_real_build_records_the_engines_counters_and_a_dry_run_does_not(tmp_path: Path) -> None:
    project_dir, folder = _new_project(tmp_path)
    hill_rush(folder, **_PLAYABLE)
    link_map_path = folder / "build" / "link_map.json"

    compile_module._run_compile_in_process(project_dir, folder, save=False)
    assert "counters" not in json.loads(link_map_path.read_text(encoding="utf-8"))["budget"]

    result = compile_module._run_compile_in_process(project_dir, folder, save=True)

    assert result.success, compile_module.format_build_result(result)
    counters = json.loads(link_map_path.read_text(encoding="utf-8"))["budget"]["counters"]
    assert counters["triggers"]["cap"] == 320 and counters["triggers"]["used"] > 0
    assert counters["actions"]["used"] >= 1 and counters["conditions"]["cap"] == 512
    compile_module._run_compile_in_process(project_dir, folder, save=True)  # a second build keeps them, unchanged
    assert json.loads(link_map_path.read_text(encoding="utf-8"))["budget"]["counters"] == counters


def _resync(project_dir: Path, folder: Path, built: Path) -> None:
    """What the IDE does when the built ``.bin`` changes under it (Launch RVT and save, or anything else that rewrites it):
    settings/ is re-extracted from it."""
    from in_reach.app.rvt import decompile

    decompile._resync_from_bin_in_process(built, folder)


def _speed(folder: Path) -> str:
    settings = json.loads((folder / "settings" / "script_settings.json").read_text(encoding="utf-8"))
    return next(t for t in settings["scripted_player_traits"] if t["name"] in ("t_hill_buff", ""))["traits"]["movement"]["speed"]


def test_a_trait_changed_in_its_module_still_lands_after_the_bin_was_resynced(tmp_path: Path) -> None:
    """The regression: after a resync (Launch RVT) blanked the trait's display name, the entry looked hand-edited and a
    later change to the module's ``@trait`` was silently ignored."""
    project_dir, folder = _new_project(tmp_path)
    hill_rush(folder, **_PLAYABLE)
    built = compile_module._run_compile_in_process(project_dir, folder, save=True)
    assert built.success and _speed(folder) == "value_120"
    _resync(project_dir, folder, Path(built.output_path))
    module = folder / "script" / "modules" / "hill_buff" / "hill_buff.mgl"

    module.write_text(module.read_text(encoding="utf-8").replace("value_120", "value_200"), encoding="utf-8")
    rebuilt = compile_module._run_compile_in_process(project_dir, folder, save=True)

    assert rebuilt.success and _speed(folder) == "value_200"
    snapshot = json.loads((folder / "build" / "script_settings.autogenerated.json").read_text(encoding="utf-8"))
    assert snapshot["scripted_player_traits"][2]["traits"]["movement"]["speed"] == "value_200"  # what the build really holds


def test_traits_and_widgets_declared_in_a_module_follow_it_after_a_resync(tmp_path: Path) -> None:
    """A resync must not make any declared resource look hand-edited: change each declaration afterwards and it must
    follow. (Options are not covered: they can't be declared yet, see the next test.)"""
    module_text = (
        '-- @trait t_a { movement_speed = "value_120" }\n'
        "-- @widget w_a { position = 2 }\n"
        "-- @fragment HILL_PASS.buff\n-- @loop player\ncurrent_player.score += 1\n"
    )
    project_dir, folder = _new_project(tmp_path)
    hill_rush(folder, modules__hill_buff__hill_buff_dot_mgl=module_text, modules__hill_score__hill_score_dot_mgl="-- @ptimer p_t default=1\n")
    built = compile_module._run_compile_in_process(project_dir, folder, save=True)
    assert built.success, compile_module.format_build_result(built)
    _resync(project_dir, folder, Path(built.output_path))
    module = folder / "script" / "modules" / "hill_buff" / "hill_buff.mgl"

    module.write_text(module_text.replace("value_120", "value_200").replace("position = 2", "position = 3"), encoding="utf-8")
    rebuilt = compile_module._run_compile_in_process(project_dir, folder, save=True)

    assert rebuilt.success, compile_module.format_build_result(rebuilt)
    settings = json.loads((folder / "settings" / "script_settings.json").read_text(encoding="utf-8"))
    link_map = json.loads((folder / "build" / "link_map.json").read_text(encoding="utf-8"))["resources"]
    assert settings["scripted_player_traits"][link_map["t_a"]["index"]]["traits"]["movement"]["speed"] == "value_200"
    assert settings["scripted_hud_widgets"][link_map["w_a"]["index"]]["position"] == 3


_NAMED = (
    '-- @trait t_fast { movement_speed = "value_150" }\n'
    '-- @trait t_named { name = "Slow Down", desc = "Half speed", movement_speed = "value_050" }\n'
    '-- @option o_dev { type = "toggle", default = 0 }\n'
    '-- @option o_mins { type = "range", min = 1, max = 30, default = 10, name = "Minutes" }\n'
    "-- @fragment HILL_PASS.buff\n-- @loop player\ncurrent_player.apply_traits(t_fast)\n"
)


def _named_project(tmp_path: Path, module_text: str = _NAMED) -> tuple[Path, Path]:
    project_dir, folder = _new_project(tmp_path)
    hill_rush(folder, modules__hill_buff__hill_buff_dot_mgl=module_text, modules__hill_score__hill_score_dot_mgl="-- @ptimer p_t default=1\n")
    return project_dir, folder


def _resource_entries(folder: Path, output_path) -> dict:
    """``alias -> the native trait set / option`` of the built variant, read back from the saved ``.bin``."""
    mp = rvt_bridge.get_rvt().load(str(output_path)).multiplayer
    resources = json.loads((folder / "build" / "link_map.json").read_text(encoding="utf-8"))["resources"]
    return {
        alias: mp.scripted_player_trait(e["index"]) if e["kind"] == "trait" else mp.scripted_option(e["index"])
        for alias, e in resources.items()
    }


def test_a_declared_trait_set_and_option_have_names_in_the_game_not_empty_strings(tmp_path: Path) -> None:
    """The regression: a trait set the compiler creates points at the table's shared empty string, so a declared trait
    showed a blank name in game whatever it was called in the code."""
    project_dir, folder = _named_project(tmp_path)

    built = compile_module._run_compile_in_process(project_dir, folder, save=True)

    assert built.success, compile_module.format_build_result(built)
    entries = _resource_entries(folder, built.output_path)
    assert entries["t_fast"].name.text == "t_fast"  # no name given: the alias
    assert (entries["t_named"].name.text, entries["t_named"].desc.text) == ("Slow Down", "Half speed")
    assert entries["o_dev"].name.text == "o_dev" and [entries["o_dev"].value(i).name.text for i in range(2)] == ["Off", "On"]
    assert entries["o_mins"].name.text == "Minutes" and entries["o_mins"].is_range
    names = {entries[a].name.text for a in entries}
    assert len(names) == 4  # each has a string of its own: naming one never renamed another


def test_the_names_are_in_strings_json_and_nothing_is_left_unapplied(tmp_path: Path) -> None:
    from in_reach.app import apply_settings

    project_dir, folder = _named_project(tmp_path)
    built = compile_module._run_compile_in_process(project_dir, folder, save=True)
    assert built.success, compile_module.format_build_result(built)

    strings = json.loads((folder / "settings" / "strings.json").read_text(encoding="utf-8"))["script_strings"]
    english = {e["text"]["english"] for e in strings}

    assert {"t_fast", "Slow Down", "Half speed", "Off", "On", "o_dev", "Minutes"} <= english
    assert apply_settings.settings_have_unapplied_changes(folder) is False


def test_a_name_changed_in_the_code_follows_it_through_a_resync(tmp_path: Path) -> None:
    project_dir, folder = _named_project(tmp_path)
    built = compile_module._run_compile_in_process(project_dir, folder, save=True)
    assert built.success
    _resync(project_dir, folder, Path(built.output_path))
    module = folder / "script" / "modules" / "hill_buff" / "hill_buff.mgl"

    module.write_text(module.read_text(encoding="utf-8").replace("Slow Down", "Crawl"), encoding="utf-8")
    rebuilt = compile_module._run_compile_in_process(project_dir, folder, save=True)

    assert rebuilt.success, compile_module.format_build_result(rebuilt)
    assert _resource_entries(folder, rebuilt.output_path)["t_named"].name.text == "Crawl"
    strings = json.loads((folder / "settings" / "strings.json").read_text(encoding="utf-8"))["script_strings"]
    english = [e["text"]["english"] for e in strings]
    assert "Crawl" in english and "Slow Down" not in english


def test_options_declared_in_code_build_and_follow_their_declaration_after_a_resync(tmp_path: Path) -> None:
    from in_reach.app import apply_settings

    project_dir, folder = _named_project(tmp_path)
    built = compile_module._run_compile_in_process(project_dir, folder, save=True)
    assert built.success, compile_module.format_build_result(built)
    _resync(project_dir, folder, Path(built.output_path))
    assert apply_settings.settings_have_unapplied_changes(folder) is False
    module = folder / "script" / "modules" / "hill_buff" / "hill_buff.mgl"

    module.write_text(module.read_text(encoding="utf-8").replace("default = 0", "default = 1").replace("max = 30", "max = 60"), encoding="utf-8")
    rebuilt = compile_module._run_compile_in_process(project_dir, folder, save=True)

    assert rebuilt.success, compile_module.format_build_result(rebuilt)
    settings = json.loads((folder / "settings" / "script_settings.json").read_text(encoding="utf-8"))
    resources = json.loads((folder / "build" / "link_map.json").read_text(encoding="utf-8"))["resources"]
    assert settings["scripted_options"][resources["o_dev"]["index"]]["default_value_index"] == 1
    assert settings["scripted_options"][resources["o_mins"]["index"]]["range_max"]["value"] == 60
    assert apply_settings.settings_have_unapplied_changes(folder) is False


def test_an_option_is_usable_from_the_script_by_its_alias(tmp_path: Path) -> None:
    project_dir, folder = _new_project(tmp_path)
    hill_rush(
        folder,
        **_PLAYABLE,
        blocks__setup_dot_mgl=(
            '-- @option o_dev { type = "toggle", default = 1 }\n'
            "on init: do\n   if o_dev == 1 then\n      global.number[1] = 5\n   end\nend\n"
        ),
    )

    built = compile_module._run_compile_in_process(project_dir, folder, save=True)

    assert built.success, compile_module.format_build_result(built)
    text = rvt_bridge.get_rvt().load(str(built.output_path)).decompile_script()
    assert "script_option[" in text


def test_the_shipped_sample_project_builds_and_fuses_its_two_modules(tmp_path: Path) -> None:
    import shutil

    from in_reach.app.script_project.edit import set_module_enabled

    sample = Path(__file__).parents[3] / "samples" / "script_project" / "script"
    project_dir, folder = _new_project(tmp_path)
    shutil.copytree(sample, folder / "script", dirs_exist_ok=True)
    for module in ("scoring", "speed_boost"):  # the sample ships with them switched off
        set_module_enabled(folder, module, True)

    result = compile_module._run_compile_in_process(project_dir, folder, save=True)

    assert result.success, compile_module.format_build_result(result)
    text = rvt_bridge.get_rvt().load(str(result.output_path)).decompile_script().replace("\r\n", "\n")
    assert "for each player do\n   current_player.timer[0].set_rate(-100%)" in text
    assert "current_player.apply_traits(script_traits[2])\nend" in text  # in the same loop as the score
    assert "if current_player.score >= 10 then" in text
    assert rvt_bridge.get_rvt().load(str(result.output_path)).multiplayer.scripted_player_trait(2).name.text == "Fast"
