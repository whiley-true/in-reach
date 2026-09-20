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
