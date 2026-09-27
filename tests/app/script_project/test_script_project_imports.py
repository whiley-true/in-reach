"""``-- @import MODULE`` in a block file: the module's fragments are built where the line is.

Without it a block's fragments go after all of its code, so a reader of the block can't see where a module's code
comes in -- and a script converted to a project had to be cut into blocks MAIN, PART_2, ... at every loop to keep its
triggers in order (PROMPT.md). With it, the block reads top to bottom as the built script runs.
"""
from pathlib import Path

import pytest

from in_reach.app.rvt.megalo_ast import parse_annotations
from in_reach.app.script_project import link, load_project

_PROJECT = '[blocks]\norder = ["MAIN"]\n\n[[modules]]\nname = "score"\n\n[[modules]]\nname = "tidy"\n'
_SCORE = "-- @fragment MAIN.score\n-- @loop player\n-- @fusion never\ncurrent_player.score += 1\n"
_TIDY = (
    "-- @fragment MAIN.first\n-- @loop object\n-- @fusion never\ncurrent_object.number[0] = 1\n"
    "\n-- @fragment MAIN.second\n-- @loop object\n-- @fusion never\ncurrent_object.number[1] = 2\n"
)


def _project(tmp_path: Path, main: str, **overrides: str) -> Path:
    files = {
        "project.toml": _PROJECT,
        "blocks/main.mgl": main,
        "modules/score/module.toml": '[module]\nname = "score"\n',
        "modules/score/score.mgl": _SCORE,
        "modules/tidy/module.toml": '[module]\nname = "tidy"\n',
        "modules/tidy/tidy.mgl": _TIDY,
    }
    files.update({key.replace("__", "/").replace("_dot_", "."): value for key, value in overrides.items()})
    for relative, text in files.items():
        path = tmp_path / "script" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def _order(compiled: str, *markers: str) -> list[int]:
    return [compiled.index(marker) for marker in markers]


# -- the annotation ------------------------------------------------------------------------------------------------


def test_an_import_names_a_module_or_one_of_its_fragments() -> None:
    result = parse_annotations("-- @import score\n-- @import tidy.second -- just the one\n")

    assert [(a.kind, a.module, a.fragment) for a in result.items] == [("import", "score", None), ("import", "tidy", "second")]
    assert result.items[1].target == "tidy.second" and result.items[1].note == "just the one"


@pytest.mark.parametrize(("text", "message"), [("-- @import", "needs a module name"), ("-- @import a.b.c", "MODULE.NAME"), ("-- @import 9x", "MODULE.NAME")])
def test_import_problems(text: str, message: str) -> None:
    result = parse_annotations(text)

    assert result.items == [] and message in result.diagnostics[0].message


# -- where the linker puts the code ----------------------------------------------------------------------------------


def test_an_imported_module_is_built_where_the_line_is(tmp_path: Path) -> None:
    folder = _project(tmp_path, "global.number[0] = 1\n-- @import score\nglobal.number[1] = 2\n")

    result = link(folder, write=False)

    assert result.ok, [str(d) for d in result.diagnostics]
    assert _order(result.compiled, "global.number[0] = 1", "current_player.score += 1", "global.number[1] = 2") == sorted(
        _order(result.compiled, "global.number[0] = 1", "current_player.score += 1", "global.number[1] = 2")
    )
    # tidy has no @import line: its fragments still go after the block's code, as before
    assert result.compiled.index("current_object.number[0] = 1") > result.compiled.index("global.number[1] = 2")


def test_one_fragment_can_be_imported_on_its_own(tmp_path: Path) -> None:
    folder = _project(tmp_path, "-- @import tidy.second\nglobal.number[0] = 1\n-- @import tidy\n")

    result = link(folder, write=False)

    assert result.ok, [str(d) for d in result.diagnostics]
    second, code, first = _order(result.compiled, "current_object.number[1] = 2", "global.number[0] = 1", "current_object.number[0] = 1")
    assert second < code < first  # `@import tidy` places what is left of tidy


def test_the_built_lines_still_map_back_to_their_files(tmp_path: Path) -> None:
    folder = _project(tmp_path, "global.number[0] = 1\n-- @import score\nglobal.number[1] = 2\n")

    result = link(folder, write=False)

    files = {run["file"] for run in result.link_map["source_lines"]}
    assert {"blocks/main.mgl", "modules/score/score.mgl"} <= files


def test_without_imports_a_blocks_fragments_still_come_after_its_code(tmp_path: Path) -> None:
    compiled = link(_project(tmp_path, "global.number[0] = 1\nglobal.number[1] = 2\n"), write=False).compiled

    code_end = compiled.index("global.number[1] = 2")
    assert code_end < compiled.index("current_player.score += 1") < compiled.index("current_object.number[0] = 1")


def test_imported_fragments_are_never_fused_with_ones_placed_elsewhere(tmp_path: Path) -> None:
    fusable = "-- @fragment MAIN.score\n-- @loop player\ncurrent_player.score += 1\n"
    other = "-- @fragment MAIN.first\n-- @loop player\ncurrent_player.number[0] = 1\n"
    folder = _project(tmp_path, "-- @import score\nglobal.number[0] = 1\n", modules__score__score_dot_mgl=fusable, modules__tidy__tidy_dot_mgl=other)

    result = link(folder, write=False)

    assert result.ok, [str(d) for d in result.diagnostics]
    assert result.compiled.count("for each player do") == 2  # the code between them keeps them apart


# -- what it reports --------------------------------------------------------------------------------------------------


def _problems(folder: Path) -> list[tuple[str, str, int]]:
    return [(d.code, d.file, d.line) for d in link(folder, write=False).diagnostics if d.severity == "error"]


def test_importing_a_module_that_does_not_exist_is_an_error_at_its_line(tmp_path: Path) -> None:
    folder = _project(tmp_path, "global.number[0] = 1\n-- @import scroe\n")

    assert _problems(folder) == [("import-unknown", "blocks/main.mgl", 2)]


def test_importing_a_module_with_nothing_for_this_block_says_where_its_fragments_are(tmp_path: Path) -> None:
    folder = _project(
        tmp_path, "-- @import score\n",
        project_dot_toml=_PROJECT.replace('order = ["MAIN"]', 'order = ["MAIN", "END"]'),
        modules__score__score_dot_mgl=_SCORE.replace("MAIN.score", "END.score"),
        blocks__end_dot_mgl="global.number[3] = 1\n",
    )

    diagnostics = [d for d in link(folder, write=False).diagnostics if d.code == "import-empty"]

    assert len(diagnostics) == 1 and "in END" in diagnostics[0].message


def test_importing_the_same_fragments_twice_is_an_error(tmp_path: Path) -> None:
    folder = _project(tmp_path, "-- @import score\nglobal.number[0] = 1\n-- @import score\n")

    assert _problems(folder) == [("import-duplicate", "blocks/main.mgl", 3)]


def test_an_import_in_a_module_is_an_error(tmp_path: Path) -> None:
    folder = _project(tmp_path, "global.number[0] = 1\n", modules__score__score_dot_mgl="-- @import tidy\n" + _SCORE)

    assert "import-in-module" in {d.code for d in load_project(folder).diagnostics}


def test_importing_a_disabled_module_places_nothing_and_is_not_an_error(tmp_path: Path) -> None:
    folder = _project(
        tmp_path, "global.number[0] = 1\n-- @import score\n",
        project_dot_toml=_PROJECT.replace('name = "score"\n', 'name = "score"\nenabled = false\n'),
    )

    result = link(folder, write=False)

    assert result.ok, [str(d) for d in result.diagnostics]
    assert "current_player.score" not in result.compiled


def test_a_single_file_cannot_import(tmp_path: Path) -> None:
    from in_reach.app.script_project.project import load_single_file

    (tmp_path / "script").mkdir()
    (tmp_path / "script" / "output.mgl").write_text("-- @import score\nglobal.number[0] = 1\n", encoding="utf-8")

    assert [d.code for d in load_single_file(tmp_path).diagnostics] == ["project-only"]


# -- moving a fragment away takes its @import line with it ---------------------------------------------------------


def test_moving_an_imported_fragment_to_another_block_removes_the_stale_import(tmp_path: Path) -> None:
    from in_reach.app.script_project import edit

    folder = _project(
        tmp_path, "global.number[0] = 1\n-- @import score\n-- @import tidy.first\nglobal.number[1] = 2\n",
        project_dot_toml=_PROJECT.replace('order = ["MAIN"]', 'order = ["MAIN", "END"]'),
        blocks__end_dot_mgl="global.number[3] = 1\n",
    )

    edit.move_fragment(folder, "score.score", "END")
    edit.move_fragment(folder, "tidy.first", "END")

    assert (folder / "script" / "blocks" / "main.mgl").read_text(encoding="utf-8") == "global.number[0] = 1\nglobal.number[1] = 2\n"
    assert link(folder, write=False).ok


def test_a_module_import_stays_while_the_module_still_has_a_fragment_in_the_block(tmp_path: Path) -> None:
    from in_reach.app.script_project import edit

    folder = _project(
        tmp_path, "-- @import tidy\nglobal.number[0] = 1\n",
        project_dot_toml=_PROJECT.replace('order = ["MAIN"]', 'order = ["MAIN", "END"]'),
        blocks__end_dot_mgl="global.number[3] = 1\n",
    )

    edit.move_fragment(folder, "tidy.first", "END")

    assert (folder / "script" / "blocks" / "main.mgl").read_text(encoding="utf-8").startswith("-- @import tidy\n")
    assert link(folder, write=False).ok


# -- a module's one loop needs no @fragment: the block that imports it is where it goes -----------------------------

_ONE_LOOP = "-- @doc Scores everyone.\n-- @loop player\ncurrent_player.score += 1\n"


def test_a_one_loop_module_goes_where_it_is_imported(tmp_path: Path) -> None:
    folder = _project(tmp_path, "global.number[0] = 1\n-- @import score\nglobal.number[1] = 2\n", modules__score__score_dot_mgl=_ONE_LOOP)

    result = link(folder, write=False)

    assert result.ok, [str(d) for d in result.diagnostics]
    assert "-- MAIN.score\nfor each player do\n   current_player.score += 1\nend" in result.compiled
    first, loop, last = _order(result.compiled, "global.number[0] = 1", "current_player.score += 1", "global.number[1] = 2")
    assert first < loop < last


def test_the_module_then_counts_as_contributing_to_that_block(tmp_path: Path) -> None:
    from in_reach.app.script_project.model import build_model

    folder = _project(tmp_path, "-- @import score\n", modules__score__score_dot_mgl=_ONE_LOOP)
    project = load_project(folder)
    model = build_model(project)

    [fragment] = [f for f in model.fragments if f.module == "score"]
    assert fragment.implicit and fragment.id == "score.score" and fragment.block == "MAIN" and fragment.doc == ["Scores everyone."]
    assert "score" in project.blocks["MAIN"].contributors
    assert project.modules[0].blocks == ["MAIN"]


def test_a_one_loop_module_no_block_imports_is_an_error_at_its_loop(tmp_path: Path) -> None:
    folder = _project(tmp_path, "global.number[0] = 1\n", modules__score__score_dot_mgl=_ONE_LOOP)

    assert _problems(folder) == [("module-unplaced", "modules/score/score.mgl", 2)]


def test_a_one_loop_module_runs_in_one_block_only(tmp_path: Path) -> None:
    folder = _project(
        tmp_path, "-- @import score\n",
        project_dot_toml=_PROJECT.replace('order = ["MAIN"]', 'order = ["MAIN", "END"]'),
        modules__score__score_dot_mgl=_ONE_LOOP,
        blocks__end_dot_mgl="-- @import score\n",
    )

    assert _problems(folder) == [("import-elsewhere", "blocks/end.mgl", 1)]


def test_a_module_with_two_unnamed_loops_must_name_them(tmp_path: Path) -> None:
    folder = _project(
        tmp_path, "-- @import score\n",
        modules__score__score_dot_mgl=_ONE_LOOP + "\n-- @loop object\ncurrent_object.number[0] = 1\n",
    )

    assert ("loop-unnamed", "modules/score/score.mgl", 5) in _problems(folder)


def test_moving_a_one_loop_module_moves_its_import(tmp_path: Path) -> None:
    from in_reach.app.script_project import edit

    folder = _project(
        tmp_path, "global.number[0] = 1\n-- @import score\n",
        project_dot_toml=_PROJECT.replace('order = ["MAIN"]', 'order = ["MAIN", "END"]'),
        modules__score__score_dot_mgl=_ONE_LOOP,
        blocks__end_dot_mgl="global.number[3] = 1\n",
    )

    changed = edit.move_fragment(folder, "score.score", "END")

    assert changed == folder / "script" / "blocks" / "end.mgl"
    assert (folder / "script" / "blocks" / "main.mgl").read_text(encoding="utf-8") == "global.number[0] = 1\n"
    assert changed.read_text(encoding="utf-8") == "global.number[3] = 1\n-- @import score\n"
    assert (folder / "script" / "modules" / "score" / "score.mgl").read_text(encoding="utf-8") == _ONE_LOOP  # untouched
    result = link(folder, write=False)
    assert result.ok and result.compiled.index("global.number[3] = 1") < result.compiled.index("current_player.score += 1")


def test_moving_a_one_loop_module_to_a_block_without_a_file_creates_it(tmp_path: Path) -> None:
    from in_reach.app.script_project import edit

    folder = _project(
        tmp_path, "-- @import score\n",
        project_dot_toml=_PROJECT.replace('order = ["MAIN"]', 'order = ["MAIN", "LATE"]'),
        modules__score__score_dot_mgl=_ONE_LOOP,
    )

    edit.move_fragment(folder, "score.score", "LATE")

    assert (folder / "script" / "blocks" / "late.mgl").read_text(encoding="utf-8") == "-- @import score\n"
    assert link(folder, write=False).ok
