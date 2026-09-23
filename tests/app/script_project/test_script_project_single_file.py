"""A single ``script/output.txt`` linked as a project of one block: its annotations are read and checked, its storage
names get slots, and it is assembled *transparently* -- a file with no annotations links to exactly its preprocessed
text (:func:`in_reach.app.script_project.load_single_file`, the linker's single-file assembly)."""
import json
from pathlib import Path

from in_reach import api
from in_reach.app import script_preprocess
from in_reach.app.script_project import is_linked, link, load_single_file
from in_reach.app.script_project.linker import COMPILED_FILENAME, DECLARATIONS_FILENAME, LINK_MAP_FILENAME

_PLAIN = "-- a comment\nfor each player do\n   if current_player.score >= 5 then\n      game.end_round()\n   end\nend\n"


def _single(tmp_path: Path, text: str, env: str | None = None) -> Path:
    script = tmp_path / "script"
    script.mkdir()
    (script / "output.txt").write_text(text, encoding="utf-8")
    if env is not None:
        (script / "env").mkdir()
        (script / "env" / "dev.env").write_text(env, encoding="utf-8")
        script_preprocess.set_active_env(tmp_path, "dev")
    return tmp_path


def _codes(result) -> list[str]:
    return [d.code for d in result.diagnostics]


def test_a_file_with_no_annotations_links_to_itself_byte_for_byte(tmp_path: Path) -> None:
    folder = _single(tmp_path, _PLAIN)

    result = link(folder, write=False)

    assert not is_linked(folder)
    assert result.ok and result.diagnostics == []
    assert result.compiled == _PLAIN
    assert result.link_map["order"] == ["MAIN"]
    assert result.link_map["source_lines"] == [{"compiled": 1, "file": "output.txt", "source": 1, "count": 7}]


def test_a_file_without_a_final_newline_keeps_it_that_way(tmp_path: Path) -> None:
    folder = _single(tmp_path, "game.end_round()")
    assert link(folder, write=False).compiled == "game.end_round()"


def test_the_profile_is_applied_exactly_as_the_preprocessor_does(tmp_path: Path) -> None:
    source = "x = ${SCORE}\n-- @if DEV\ny = 1\n-- @end\n"
    folder = _single(tmp_path, source, env="FLAGS=DEV\nSCORE=7\n")

    result = link(folder, write=False)

    assert result.ok, result.diagnostics
    assert result.compiled == script_preprocess.preprocess_project(folder, source)
    assert result.link_map["env"] == "dev"


def test_storage_and_resources_add_declarations_above_the_unchanged_file(tmp_path: Path) -> None:
    source = (
        "-- @number g_score priority=high\n"
        '-- @trait t_fast { name = "Fast", movement_speed = "value_150" }\n'
        "for each player do\n"
        "   g_score += 1\n"
        "   current_player.apply_traits(t_fast)\n"
        "end\n"
    )
    folder = _single(tmp_path, source)

    result = link(folder, write=False)

    assert result.ok, result.diagnostics
    assert result.compiled == (
        "declare global.number[0] with network priority high\n"
        "\n"
        "alias g_score = global.number[0]\n"
        "alias t_fast = script_traits[0]\n"
        "\n" + source
    )
    # every line of the file is where the compiler sees it, five lines down
    assert result.link_map["source_lines"] == [{"compiled": 6, "file": "output.txt", "source": 1, "count": 7}]
    assert result.link_map["storage"]["g_score"] == {"slot": "global.number[0]", "owner": "output.txt"}
    assert result.link_map["resources"]["t_fast"]["kind"] == "trait"


def test_a_slot_the_file_names_itself_is_never_allocated(tmp_path: Path) -> None:
    folder = _single(tmp_path, "-- @number g_new\nglobal.number[0] = 1\ng_new = 2\n")

    result = link(folder, write=False)

    assert result.ok, result.diagnostics
    assert "alias g_new = global.number[1]" in result.compiled


def test_a_label_is_substituted_on_its_own_line(tmp_path: Path) -> None:
    folder = _single(tmp_path, '-- @label L_hill = "hill"\nfor each object with label L_hill do\nend\n')

    result = link(folder, write=False)

    assert result.ok, result.diagnostics
    assert result.compiled.splitlines()[1] == 'for each object with label "hill" do'


def test_a_name_declared_twice_is_ir006_at_its_line(tmp_path: Path) -> None:
    folder = _single(tmp_path, "-- @number g_a\n-- @pnumber g_a\n")

    result = link(folder, write=False)

    assert not result.ok
    [clash] = [d for d in result.diagnostics if d.code == "IR006"]
    assert (clash.file, clash.line) == ("output.txt", 2)


def test_an_annotation_only_a_project_understands_is_an_error_pointing_at_convert(tmp_path: Path) -> None:
    folder = _single(tmp_path, "-- @fragment TICK.score\n-- @loop player\n-- @guard-end\ngame.end_round()\n")

    result = link(folder, write=False)

    assert not result.ok
    problems = [(d.code, d.line) for d in result.diagnostics if d.code == "project-only"]
    assert problems == [("project-only", 1), ("project-only", 2), ("project-only", 3)]
    assert "Convert to Project" in result.diagnostics[0].message
    assert "@guard-end" in result.diagnostics[2].message


def test_an_unknown_annotation_is_only_a_warning_since_it_used_to_be_a_comment(tmp_path: Path) -> None:
    folder = _single(tmp_path, "-- @todo make this faster\ngame.end_round()\n")

    result = link(folder, write=False)

    assert result.ok
    assert [(d.severity, d.code, d.line) for d in result.diagnostics] == [("warning", "annotation", 1)]


def test_a_malformed_known_annotation_is_an_error(tmp_path: Path) -> None:
    folder = _single(tmp_path, "-- @number\ngame.end_round()\n")

    result = link(folder, write=False)

    assert not result.ok and [(d.severity, d.code) for d in result.diagnostics] == [("error", "annotation")]


def test_the_linter_runs_on_a_single_file(tmp_path: Path) -> None:
    folder = _single(tmp_path, "global.number[0] = true\nfor each object do\nend\n")

    result = link(folder, write=False)

    assert _codes(result) == ["IR007", "IR010"]
    assert all(d.file == "output.txt" for d in result.diagnostics)


def test_a_constant_nobody_defined_is_located_in_the_file(tmp_path: Path) -> None:
    folder = _single(tmp_path, "x = 1\ny = ${NOPE}\n", env="FLAGS=DEV\n")

    result = link(folder, write=False)

    assert [(d.code, d.file, d.line, d.col) for d in result.diagnostics] == [("preprocess", "output.txt", 2, 4)]


def test_writing_a_single_file_link_leaves_compiled_txt_to_the_output_view(tmp_path: Path) -> None:
    folder = _single(tmp_path, '-- @number g_score\n-- @trait t_fast { name = "Fast" }\ng_score = 1\n')

    result = link(folder)

    build = folder / "build"
    assert result.ok and not (build / COMPILED_FILENAME).exists()
    assert (build / DECLARATIONS_FILENAME).read_text(encoding="utf-8") == (
        "alias g_score = global.number[0]\nalias t_fast = script_traits[0]\n"  # no priority or default: no declare
    )
    assert json.loads((build / LINK_MAP_FILENAME).read_text(encoding="utf-8"))["storage"]["g_score"]["slot"] == "global.number[0]"
    settings = json.loads((folder / "settings" / "script_settings.json").read_text(encoding="utf-8"))
    assert len(settings["scripted_player_traits"]) == 1


def test_load_single_file_reads_an_unsaved_buffer_instead_of_the_file(tmp_path: Path) -> None:
    folder = _single(tmp_path, "game.end_round()\n")

    project = load_single_file(folder, "-- @number g_x\n")

    assert project.blocks["MAIN"].file.text == "-- @number g_x\n"
    assert [a.name for a in project.blocks["MAIN"].file.annotations.items] == ["g_x"]


def test_api_check_accepts_a_single_file(tmp_path: Path) -> None:
    folder = _single(tmp_path, "-- @number g_a\n-- @number g_a\n")

    result = api.check(folder)

    assert not result.ok and [d.code for d in result.errors] == ["IR006"]
    assert not (folder / "build").exists()  # a check writes nothing
