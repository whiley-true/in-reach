"""A single ``script/output.mgl`` through the real compile, now that it is linked first: its own slots are built as
written, an annotation that would pick a slot for it fails the build (that is a script project's job), compiler errors
point at the file's own lines, and an untouched file is still recognised as unchanged (the link adds nothing to it)."""
from pathlib import Path

import pytest

from in_reach.app import new_project, project
from in_reach.app.rvt import compile as compile_module
from in_reach.app.rvt import decompile, rvt_bridge

_JUGGERNAUT_BIN = Path(__file__).parent / "resources" / "juggernaut" / "juggernaut.bin"

pytestmark = pytest.mark.skipif(
    not (_JUGGERNAUT_BIN.is_file() and rvt_bridge.is_available()),
    reason="fixture .bin not present, or native _reachvarianttool extension not available on this platform",
)


def _new_project(tmp_path: Path) -> tuple[Path, Path]:
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir(parents=True)
    folder, warning = new_project.create_gametype_project(project_dir, "Single", source_variant=_JUGGERNAUT_BIN)
    assert warning is None
    return project_dir, folder


def _decompiled(path: Path) -> str:
    return decompile.normalize_script_text(rvt_bridge.get_rvt().load(str(path)).decompile_script())


def test_an_untouched_single_file_still_builds_the_base_script_unchanged(tmp_path: Path) -> None:
    project_dir, folder = _new_project(tmp_path)

    result = compile_module._run_compile_in_process(project_dir, folder, save=True)

    assert result.success, compile_module.format_build_result(result)
    # Recompiling the decompile would change the trigger layout; identical text means the compile was skipped.
    assert _decompiled(result.output_path) == _decompiled(new_project.source_variant_path(project_dir, folder))


def test_a_single_file_names_its_own_slots_and_they_are_built_as_written(tmp_path: Path) -> None:
    project_dir, folder = _new_project(tmp_path)
    (folder / "script" / "output.mgl").write_text(
        "-- @doc Three rounds, set when the game starts.\n"
        "declare global.number[0] with network priority high\n"
        "on init: do\n"
        "   global.number[0] = 3\n"
        "end\n",
        encoding="utf-8",
    )

    result = compile_module._run_compile_in_process(project_dir, folder, save=True)

    assert result.success, compile_module.format_build_result(result)
    text = _decompiled(result.output_path)
    assert "declare global.number[0] with network priority high" in text
    assert "global.number[0] = 3" in text
    # every build refreshes the generated documentation
    overview = (folder / "build" / "docs" / "overview.md").read_text(encoding="utf-8")
    assert "Three rounds, set when the game starts." in overview


def test_a_slot_picking_annotation_fails_a_single_files_build_before_compiling(tmp_path: Path) -> None:
    project_dir, folder = _new_project(tmp_path)
    (folder / "script" / "output.mgl").write_text("-- @number g_a\non init: do\n   g_a = 1\nend\n", encoding="utf-8")

    result = compile_module._run_compile_in_process(project_dir, folder, save=True)

    assert result.success is False and result.failure == "The script has errors -- see the errors."
    assert [(m.file, m.line, m.code) for m in result.errors] == [("output.mgl", 1, "project-only")]


def test_a_compiler_error_is_reported_at_its_line_in_output_txt(tmp_path: Path) -> None:
    project_dir, folder = _new_project(tmp_path)
    (folder / "script" / "output.mgl").write_text(
        "-- @doc a note, which adds nothing above the file\n"  # 1
        "on init: do\n"  # 2
        "   global.number[0] = 1\n"  # 3
        "   this_is_not_a_real_call()\n"  # 4
        "end\n",  # 5
        encoding="utf-8",
    )

    result = compile_module._run_compile_in_process(project_dir, folder, save=True)

    assert result.success is False
    located = [(m.file, m.line) for m in (result.fatal_errors + result.errors)]
    assert ("output.mgl", 4) in located, compile_module.format_build_result(result)


def test_a_single_file_check_problem_fails_the_build_before_compiling(tmp_path: Path) -> None:
    project_dir, folder = _new_project(tmp_path)
    (folder / "script" / "output.mgl").write_text("declare global.number[0]\ndeclare global.number[0]\n", encoding="utf-8")

    result = compile_module._run_compile_in_process(project_dir, folder, save=True)

    assert result.success is False and result.failure == "The script has errors -- see the errors."
    assert [(m.file, m.line, m.code) for m in result.errors] == [("output.mgl", 2, "IR006")]
