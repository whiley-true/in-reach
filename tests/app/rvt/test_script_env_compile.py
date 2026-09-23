"""Env envs through a real Apply: ``${CONSTANTS}`` and ``-- @if`` blocks in ``script/output.txt``.

The unit tests for the preprocessor itself are ``tests/app/test_script_preprocess.py``; these prove the
compiler is actually handed the *processed* text, that switching envs changes what's built, and that
a compiler error still points at the right line of the file the user edits after a block has been
stripped out above it.
"""
from pathlib import Path

import pytest

from in_reach.app import new_project, project, script_preprocess
from in_reach.app.blank_variant import resolve_blank_variant
from in_reach.app.rvt import compile as compile_module
from in_reach.app.rvt import rvt_bridge

pytestmark = pytest.mark.skipif(
    not rvt_bridge.is_available(), reason="native _reachvarianttool extension not available on this platform"
)

_SCRIPT = (
    "-- @if DEV\n"
    "for each player do\n"
    "   current_player.number[0] += ${STEP}\n"
    "end\n"
    "-- @end\n"
    "if global.number[0] >= ${SCORE} then\n"
    "   game.end_round()\n"
    "end\n"
)


def _project(tmp_path: Path, script: str = _SCRIPT) -> tuple[Path, Path]:
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir(parents=True)
    folder, warning = new_project.create_gametype_project(
        project_dir, "Env Test", source_variant=resolve_blank_variant(firefight=False)
    )
    assert warning is None
    (folder / "script" / "output.txt").write_text(script, encoding="utf-8")
    # A new project already ships starter dev/release envs with dev active (see new_project); these
    # tests define their own, and each picks the active one explicitly.
    env = folder / "script" / "env"
    (env / "dev.env").write_text("FLAGS=DEV\nSTEP=2\nSCORE=5\n", encoding="utf-8")
    (env / "release.env").write_text("STEP=1\nSCORE=50\n", encoding="utf-8")
    script_preprocess.set_active_env(folder, None)
    return project_dir, folder


def _built_script(result) -> str:
    return rvt_bridge.get_rvt().load(str(result.output_path)).decompile_script()


def test_the_dev_profile_builds_the_dev_blocks_and_constants(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path)
    script_preprocess.set_active_env(folder, "dev")

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is True, compile_module.format_build_result(result)
    text = _built_script(result)
    assert "current_player.number[0] += 2" in text
    assert "global.number[0] >= 5" in text


def test_switching_to_release_changes_what_is_built(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path)
    script_preprocess.set_active_env(folder, "release")

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is True, compile_module.format_build_result(result)
    text = _built_script(result)
    assert "global.number[0] >= 50" in text
    assert "current_player.number[0] +=" not in text  # the DEV block is gone entirely


def test_the_source_file_is_never_modified_by_applying(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path)
    script_preprocess.set_active_env(folder, "dev")
    compile_module.run_compile(project_dir, folder, save=True)
    assert (folder / "script" / "output.txt").read_text(encoding="utf-8") == _SCRIPT


def test_a_project_with_no_profiles_and_no_directives_builds_exactly_as_before(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, "if global.number[0] >= 5 then\n   game.end_round()\nend\n")
    for path in (folder / "script" / "env").iterdir():
        path.unlink()

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is True, compile_module.format_build_result(result)
    assert "global.number[0] >= 5" in _built_script(result)


def test_an_undefined_constant_fails_the_build_at_its_line_and_column(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, "-- comment\nx = ${NOPE}\n")
    script_preprocess.set_active_env(folder, "dev")

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is False and result.output_path is None
    assert [(m.line, m.col) for m in result.errors] == [(2, 5)]  # 1-based, like the editor
    assert result.errors[0].file == "output.txt" and result.errors[0].code == "preprocess"
    assert "error (output.txt:2:5): '${NOPE}' isn't defined in the 'dev' env" in compile_module.format_build_result(result)


def test_a_constant_with_no_profile_active_says_so(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path)  # references ${SCORE}, but nothing is chosen
    result = compile_module.run_compile(project_dir, folder, save=True)
    assert result.success is False
    assert "no env is active" in compile_module.format_build_result(result)


def test_a_broken_env_file_fails_the_build_naming_that_file(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path)
    (folder / "script" / "env" / "dev.env").write_text("STEP=2\nSCORE=oops oops\n", encoding="utf-8")
    script_preprocess.set_active_env(folder, "dev")

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is False
    assert [(m.file, m.line, m.code) for m in result.errors] == [("env/dev.env", 2, "env-invalid")]


def test_an_active_profile_whose_file_was_deleted_is_a_clear_failure(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path)
    script_preprocess.set_active_env(folder, "dev")
    (folder / "script" / "env" / "dev.env").unlink()

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is False
    assert any("the active env 'dev' has no file" in m.text for m in result.errors)


def test_an_unbalanced_block_fails_the_build_at_the_open_if(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, "game.end_round()\n-- @if DEV\nx()\n")
    script_preprocess.set_active_env(folder, "dev")

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is False
    assert [m.line for m in result.errors] == [2]


def test_a_compiler_error_after_a_stripped_block_still_reports_the_right_line(tmp_path: Path) -> None:
    """The reason preprocessing keeps line numbers: a dev-only block sits above the mistake, and the
    error must still say line 7 -- the line the user sees in their editor."""
    script = (
        "-- @if DEV\n"  # 1
        "dev_a = 1\n"  # 2  (all of these vanish in release)
        "dev_b = 2\n"  # 3
        "dev_c = 3\n"  # 4
        "-- @end\n"  # 5
        "game.end_round()\n"  # 6
        "this_is_not_a_real_call()\n"  # 7
    )
    project_dir, folder = _project(tmp_path, script)
    script_preprocess.set_active_env(folder, "release")

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is False
    reported = [m.line for m in (result.fatal_errors + result.errors)]
    assert 7 in reported, compile_module.format_build_result(result)


def test_a_dry_run_applies_the_profile_too(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, "x = ${MISSING}\n")
    script_preprocess.set_active_env(folder, "dev")
    result = compile_module.run_compile(project_dir, folder, save=False)
    assert result.success is False and result.errors
