"""The linker: a project folder in, ``build/Compiled.txt``, ``declarations.mgl``, ``link_map.json`` and any
``script_settings.json`` change out (:func:`in_reach.app.script_project.linker.link`)."""
import json
from pathlib import Path

import pytest
from hill_project import HILL, hill_rush, write_project

from in_reach.app.script_project import link
from in_reach.app.script_project.linker import COMPILED_FILENAME, DECLARATIONS_FILENAME, LINK_MAP_FILENAME


def _build_file(folder: Path, name: str) -> Path:
    return folder / "build" / name


def _codes(result) -> list[str]:
    return [d.code for d in result.diagnostics]


def _linked(tmp_path: Path, **changes: str | None):
    hill_rush(tmp_path, **changes)
    return link(tmp_path)


# -- the design's example ---------------------------------------------------------------------------------


def test_the_hill_rush_example_links_to_the_expected_script(tmp_path: Path) -> None:
    result = _linked(tmp_path)

    assert result.ok and result.diagnostics == []
    assert result.compiled == "\n".join([
        "-- in-reach build: hill_rush  env=dev  flags=DEV",
        "-- Auto-generated and non-editable. Edit script/ and rebuild.",
        "",
        "declare global.number[1] with network priority low",
        "declare player.timer[0] = 1",
        "",
        "alias g_phase = global.number[1]",
        "alias p_hill_timer = player.timer[0]",
        "alias t_hill_buff = script_traits[0]",
        "",
        "-- SETUP (blocks/setup.mgl)",
        "on init: do",
        "   g_phase = 0",
        "end",
        "",
        "-- HILL_PASS (fused: hill_score.score, hill_buff.buff)",
        "for each player do",
        "   -- hill_score.score",
        "   x = 1",
        "   -- hill_buff.buff",
        "   y = 1",
        "end",
        "",
        "-- WIN_CHECK (blocks/win_check.mgl)",
        "if global.number[0] == 5 then",
        "   game.end_round()",
        "end",
        "",
    ])


def test_a_slot_the_hand_written_code_uses_is_never_allocated(tmp_path: Path) -> None:
    """``win_check`` says ``global.number[0]``, so ``g_phase`` -- the first declared -- takes ``[1]``."""
    result = _linked(tmp_path)

    assert result.link_map["storage"]["g_phase"]["slot"] == "global.number[1]"


def test_annotation_lines_and_directives_never_reach_the_compiler(tmp_path: Path) -> None:
    result = _linked(tmp_path)

    assert "@" not in result.compiled and "${" not in result.compiled


def test_the_profile_decides_which_conditional_code_is_built(tmp_path: Path) -> None:
    hill_rush(tmp_path)
    (tmp_path / "script" / "env" / "release.env").write_text("FLAGS=RELEASE\nSCORE_TO_WIN=50\n", encoding="utf-8")
    toml = (tmp_path / "script" / "project.toml").read_text(encoding="utf-8").replace('env = "dev"', 'env = "release"')
    (tmp_path / "script" / "project.toml").write_text(toml, encoding="utf-8")

    result = link(tmp_path)

    assert result.ok and "y = 1" not in result.compiled and "global.number[0] == 50" in result.compiled
    assert result.link_map["env"] == "release"


# -- what is written --------------------------------------------------------------------------------------


def test_a_link_writes_the_build_files_and_the_settings_it_changed(tmp_path: Path) -> None:
    result = _linked(tmp_path)

    assert _build_file(tmp_path, COMPILED_FILENAME).read_text(encoding="utf-8") == result.compiled
    assert _build_file(tmp_path, DECLARATIONS_FILENAME).read_text(encoding="utf-8") == result.declarations
    assert json.loads(_build_file(tmp_path, LINK_MAP_FILENAME).read_text(encoding="utf-8")) == result.link_map
    settings = json.loads((tmp_path / "settings" / "script_settings.json").read_text(encoding="utf-8"))
    assert [t["name"] for t in settings["scripted_player_traits"]] == ["t_hill_buff"]
    assert result.settings_changed
    assert {p.name for p in result.written} == {COMPILED_FILENAME, DECLARATIONS_FILENAME, LINK_MAP_FILENAME, "script_settings.json"}


def test_declarations_are_the_declare_and_alias_lines_alone(tmp_path: Path) -> None:
    result = _linked(tmp_path)

    assert result.declarations.splitlines()[0] == "declare global.number[1] with network priority low"
    assert "on init" not in result.declarations and "alias g_phase = global.number[1]" in result.declarations


def test_relinking_an_unchanged_project_writes_nothing(tmp_path: Path) -> None:
    first = _linked(tmp_path)
    stamp = {p.name: p.stat().st_mtime_ns for p in (tmp_path / "build").iterdir()}

    second = link(tmp_path)

    assert second.compiled == first.compiled and second.link_map == first.link_map
    assert second.written == [] and not second.settings_changed
    assert {p.name: p.stat().st_mtime_ns for p in (tmp_path / "build").iterdir()} == stamp


def test_a_change_to_one_file_rewrites_only_what_it_changes(tmp_path: Path) -> None:
    _linked(tmp_path)
    settings = tmp_path / "settings" / "script_settings.json"
    before = settings.stat().st_mtime_ns

    (tmp_path / "script" / "blocks" / "setup.mgl").write_text(
        "-- @number g_phase priority=low\non init: do\n   g_phase = 1\nend\n", encoding="utf-8"
    )
    result = link(tmp_path)

    assert {p.name for p in result.written} == {COMPILED_FILENAME}  # same slots, same lines: the map and declarations stand
    assert settings.stat().st_mtime_ns == before


def test_write_false_touches_nothing(tmp_path: Path) -> None:
    hill_rush(tmp_path)

    result = link(tmp_path, write=False)

    assert result.ok and result.compiled
    assert not (tmp_path / "build").exists() and not (tmp_path / "settings").exists()


def test_a_project_that_does_not_link_leaves_no_half_a_build(tmp_path: Path) -> None:
    for name, changes, code in (
        ("toml", {"project_dot_toml": "[project\n"}, "toml-syntax"),
        ("code", {"blocks__win_check_dot_mgl": "if x then\n"}, "body-syntax"),
    ):
        folder = tmp_path / name
        folder.mkdir()

        broken = link(hill_rush(folder, **changes))

        assert not broken.ok and code in _codes(broken), name
        assert not (folder / "build").exists() and not (folder / "settings").exists(), name


def test_a_lint_error_stops_the_link_before_anything_is_written(tmp_path: Path) -> None:
    result = _linked(tmp_path, blocks__setup_dot_mgl="-- @number a\n-- @number a\n")

    assert not result.ok and "IR006" in _codes(result)
    assert not (tmp_path / "build").exists() and result.compiled == ""


def test_an_unreadable_settings_file_is_never_overwritten(tmp_path: Path) -> None:
    hill_rush(tmp_path)
    settings = tmp_path / "settings" / "script_settings.json"
    settings.parent.mkdir()
    settings.write_text("{ not json", encoding="utf-8")

    result = link(tmp_path)

    assert not result.ok and "settings-invalid" in _codes(result)
    assert settings.read_text(encoding="utf-8") == "{ not json"


# -- storage --------------------------------------------------------------------------------------------


def test_a_full_pool_fails_the_link_at_the_name_that_tipped_it(tmp_path: Path) -> None:
    many = "".join(f"-- @number n{i}\n" for i in range(13))

    result = _linked(tmp_path, blocks__setup_dot_mgl=many)

    assert not result.ok
    # global.number[0] is the win check's own, so eleven of the thirteen fit and the twelfth is the first to fail
    first, second = [d for d in result.diagnostics if d.code == "alloc"]
    assert "global.number is full" in first.message and "n11" in first.message and "n12" in second.message
    assert first.file == "blocks/setup.mgl" and first.line == 12


def test_a_pin_is_honoured_and_recorded(tmp_path: Path) -> None:
    toml = HILL["project.toml"] + '\n[pins]\ng_phase = "global.number[5]"\n'

    result = _linked(tmp_path, project_dot_toml=toml)

    assert result.ok and result.link_map["storage"]["g_phase"]["slot"] == "global.number[5]"
    assert "alias g_phase = global.number[5]" in result.compiled


def test_bitfield_flags_are_aliased_to_powers_of_two(tmp_path: Path) -> None:
    toml = HILL["project.toml"] + '\n[kinds.carrier]\nreached_by = ["label:carrier"]\n'

    result = _linked(tmp_path, project_dot_toml=toml, blocks__setup_dot_mgl="-- @bitfield carrier.c_flags { kit, latch }\non init: do\nend\n")

    assert result.ok, [str(d) for d in result.diagnostics]

    assert "alias flag_kit = 1" in result.compiled and "alias flag_latch = 2" in result.compiled


# -- labels, resources, temporaries -----------------------------------------------------------------------


def test_a_label_name_is_replaced_by_its_text(tmp_path: Path) -> None:
    body = '-- @label L_hill = "hill"\nfor each object with label L_hill do\n   x = 1\nend\n'

    result = _linked(tmp_path, blocks__setup_dot_mgl=body)

    assert 'for each object with label "hill" do' in result.compiled and "L_hill" not in result.compiled


def test_a_resource_keeps_its_index_across_links(tmp_path: Path) -> None:
    _linked(tmp_path)
    (tmp_path / "script" / "modules" / "hill_score" / "hill_score.mgl").write_text(
        '-- @trait t_first { movement_speed = "value_050" }\n-- @fragment HILL_PASS.score\n-- @loop player\nx = 1\n', encoding="utf-8"
    )

    result = link(tmp_path)

    assert result.link_map["resources"]["t_hill_buff"]["index"] == 0
    assert result.link_map["resources"]["t_first"]["index"] == 1
    assert "alias t_first = script_traits[1]" in result.compiled


def test_a_resource_the_user_edited_in_settings_is_not_overwritten(tmp_path: Path) -> None:
    _linked(tmp_path)
    settings_path = tmp_path / "settings" / "script_settings.json"
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    data["scripted_player_traits"][0]["traits"]["movement"]["speed"] = "value_200"  # what someone did in RVT
    settings_path.write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "script" / "modules" / "hill_buff" / "hill_buff.mgl").write_text(
        '-- @trait t_hill_buff { movement_speed = "value_150" }\n-- @fragment HILL_PASS.buff\n-- @loop player\ny = 1\n', encoding="utf-8"
    )

    result = link(tmp_path)

    assert result.ok and not result.settings_changed
    assert json.loads(settings_path.read_text(encoding="utf-8"))["scripted_player_traits"][0]["traits"]["movement"]["speed"] == "value_200"


def test_a_resource_table_that_is_full_fails_the_link(tmp_path: Path) -> None:
    widgets = "".join(f"-- @widget w{i} {{ position = {i} }}\n" for i in range(5))

    result = _linked(tmp_path, blocks__setup_dot_mgl=widgets + "on init: do\nend\n")

    assert not result.ok and "resource-full" in _codes(result)


def test_a_preamble_wraps_the_fragment_and_provides_temporaries(tmp_path: Path) -> None:
    module = (
        "-- @preamble ctx\n-- @provides cx:object role:number\ncx = current_player.biped\nrole = 2\n"
        "if cx != no_object then\n   -- @guard-end\nend\n\n"
        "-- @fragment HILL_PASS.score\n-- @loop player\n-- @preamble ctx\n-- @guard role == 2\ny = 1\n"
    )

    result = _linked(tmp_path, modules__hill_score__hill_score_dot_mgl=module)

    assert result.ok, [str(d) for d in result.diagnostics]
    lines = result.compiled.splitlines()
    start = lines.index("-- HILL_PASS.score")
    assert lines[start + 1:start + 11] == [
        "for each player do",
        "   alias cx = temporaries.object[0]",
        "   alias role = temporaries.number[0]",
        "   cx = current_player.biped",
        "   role = 2",
        "   if cx != no_object then",
        "      if role == 2 then",
        "         y = 1",
        "      end",
        "   end",
    ]
    assert result.link_map["temporaries"] == [{"block": "HILL_PASS", "fragments": ["hill_score.score"], "object": 1, "number": 1}]


def test_a_trigger_needing_more_temporaries_than_exist_fails(tmp_path: Path) -> None:
    names = " ".join(f"t{i}:number" for i in range(11))
    module = f"-- @preamble ctx\n-- @provides {names}\nt0 = 1\n-- @guard-end\n\n-- @fragment HILL_PASS.score\n-- @loop player\n-- @preamble ctx\ny = 1\n"

    result = _linked(tmp_path, modules__hill_score__hill_score_dot_mgl=module)

    assert not result.ok and "IR004" in _codes(result)


def test_a_gate_wraps_the_whole_trigger(tmp_path: Path) -> None:
    module = "-- @fragment HILL_PASS.score\n-- @loop player\n-- @gate global.number[3] == 1\ny = 1\n"

    result = _linked(tmp_path, modules__hill_score__hill_score_dot_mgl=module)

    lines = result.compiled.splitlines()
    start = lines.index("-- HILL_PASS.score")
    assert lines[start + 1:start + 6] == ["if global.number[3] == 1 then", "   for each player do", "      y = 1", "   end", "end"]


# -- the link map -----------------------------------------------------------------------------------------


def test_the_link_map_records_owners_pool_usage_and_order(tmp_path: Path) -> None:
    link_map = _linked(tmp_path).link_map

    assert link_map["storage"]["p_hill_timer"] == {"slot": "player.timer[0]", "owner": "module hill_score"}
    assert link_map["budget"]["global.number"] == {"cap": 12, "used": 2}
    assert link_map["budget"]["traits"] == {"cap": 16, "used": 1}
    assert link_map["order"] == ["SETUP", "HILL_PASS", "WIN_CHECK"]
    assert link_map["env"] == "dev" and link_map["flags"] == ["DEV"]


def test_source_lines_point_every_verbatim_line_back_at_its_file(tmp_path: Path) -> None:
    result = _linked(tmp_path)
    compiled = result.compiled.splitlines()
    runs = result.link_map["source_lines"]

    assert runs
    for run in runs:
        source = (tmp_path / "script" / run["file"]).read_text(encoding="utf-8").splitlines()
        for offset in range(run["count"]):
            assert compiled[run["compiled"] - 1 + offset].strip() == source[run["source"] - 1 + offset].strip().replace("${SCORE_TO_WIN}", "5")


def test_the_two_writers_of_a_trigger_share_no_source_line(tmp_path: Path) -> None:
    runs = _linked(tmp_path).link_map["source_lines"]

    claimed = [n for run in runs for n in range(run["compiled"], run["compiled"] + run["count"])]
    assert len(claimed) == len(set(claimed))


def test_write_project_leaves_out_none_files(tmp_path: Path) -> None:
    write_project(tmp_path, {"a.txt": "x", "b.txt": None})

    assert (tmp_path / "script" / "a.txt").is_file() and not (tmp_path / "script" / "b.txt").exists()


# -- counters measured on the built variant ---------------------------------------------------------------


def test_the_built_variants_counters_are_added_to_the_link_map(tmp_path: Path) -> None:
    from in_reach.app.script_project import record_counters

    _linked(tmp_path)

    warnings = record_counters(tmp_path, {"triggers": 12, "conditions": 40, "actions": 90, "strings": 3})

    written = json.loads(_build_file(tmp_path, LINK_MAP_FILENAME).read_text(encoding="utf-8"))
    assert written["budget"]["counters"] == {
        "triggers": {"cap": 320, "used": 12}, "conditions": {"cap": 512, "used": 40},
        "actions": {"cap": 1024, "used": 90}, "strings": {"used": 3},
    }
    assert warnings == []


def test_a_relink_keeps_the_counters_the_last_build_measured(tmp_path: Path) -> None:
    from in_reach.app.script_project import record_counters

    _linked(tmp_path)
    record_counters(tmp_path, {"triggers": 12, "conditions": 40, "actions": 90})
    before = _build_file(tmp_path, LINK_MAP_FILENAME).read_text(encoding="utf-8")

    result = link(tmp_path)

    assert result.link_map["budget"]["counters"]["actions"] == {"cap": 1024, "used": 90}
    assert result.written == [] and _build_file(tmp_path, LINK_MAP_FILENAME).read_text(encoding="utf-8") == before


@pytest.mark.parametrize(("name", "used", "cap"), [("triggers", 288, 320), ("conditions", 600, 512), ("actions", 950, 1024)])
def test_ir012_warns_when_a_counter_is_within_ten_percent_of_its_cap(tmp_path: Path, name: str, used: int, cap: int) -> None:
    from in_reach.app.script_project import record_counters

    _linked(tmp_path)

    [warning] = record_counters(tmp_path, {"triggers": 1, "conditions": 1, "actions": 1, name: used})

    assert (warning.code, warning.severity) == ("IR012", "warning")
    assert f"{used} of the {cap} {name}" in warning.message


def test_counters_with_no_link_map_are_ignored(tmp_path: Path) -> None:
    from in_reach.app.script_project import record_counters

    assert record_counters(tmp_path, {"triggers": 1}) == []
    assert not (tmp_path / "build").exists()


def test_the_text_a_declaration_asks_for_is_in_the_link_map_for_the_compile(tmp_path: Path) -> None:
    module = (
        '-- @trait t_named { name = "Slow Down", desc = "Half", movement_speed = "value_050" }\n'
        '-- @trait t_plain { movement_speed = "value_100" }\n'
        '-- @option o_dev { type = "toggle" }\n'
        "-- @fragment HILL_PASS.buff\n-- @loop player\ny = 1\n"
    )

    resources = _linked(tmp_path, modules__hill_buff__hill_buff_dot_mgl=module).link_map["resources"]

    assert resources["t_named"]["text"] == {"name": "Slow Down", "desc": "Half"}
    assert "text" not in resources["t_plain"]  # nothing asked for: the compile names it after its alias
    assert resources["o_dev"]["text"] == {"values": ["Off", "On"]}


def test_an_option_links_now_that_the_engine_can_build_one(tmp_path: Path) -> None:
    result = _linked(tmp_path, blocks__setup_dot_mgl='-- @option o_dev { type = "toggle", default = 1 }\non init: do\nend\n')

    assert result.ok and "alias o_dev = script_option[0]" in result.compiled
