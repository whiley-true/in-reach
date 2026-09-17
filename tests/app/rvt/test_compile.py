import json
from pathlib import Path

import pytest

from in_reach.app import new_project, project
from in_reach.app.blank_variant import resolve_blank_variant
from in_reach.app.rvt import compile as compile_module
from in_reach.app.rvt import rvt_bridge

_FIXTURES_DIR = Path(__file__).parent / "resources"
_JUGGERNAUT_BIN = _FIXTURES_DIR / "juggernaut" / "juggernaut.bin"
_NEEDS_NATIVE_RVT = pytest.mark.skipif(
    not (_JUGGERNAUT_BIN.is_file() and rvt_bridge.is_available()),
    reason="fixture .bin not present, or native _reachvarianttool extension not available on this platform",
)


def _project(tmp_path: Path, *, source_variant: Path) -> tuple[Path, Path]:
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir(parents=True)
    folder, warning = new_project.create_gametype_project(project_dir, "Compile Test", source_variant=source_variant)
    assert warning is None
    return project_dir, folder


# -- orchestration (no native extension needed -- these short-circuit before ever calling rvt.load) --


def test_run_compile_reports_unreadable_settings_json_without_touching_the_native_extension(
    tmp_path: Path, monkeypatch
) -> None:
    from in_reach.app.rvt import rvt_bridge

    def _fail_if_called():
        raise AssertionError("get_rvt() should never be reached")

    monkeypatch.setattr(rvt_bridge, "get_rvt", _fail_if_called)
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir(parents=True)
    folder = tmp_path / "abcd1234"
    (folder / "settings").mkdir(parents=True)
    (folder / "settings" / "settings.json").write_text("{not valid json", encoding="utf-8")

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is False
    assert "settings.json" in result.failure


def test_format_build_result_includes_failure_and_every_message_category() -> None:
    from in_reach.app.rvt.compile import BuildMessage, BuildResult

    result = BuildResult(
        success=False,
        failure="Megalo compile failed -- see .errors/.fatal_errors for details.",
        fatal_errors=[BuildMessage(line=1, col=2, text="fatal!")],
        errors=[BuildMessage(line=3, col=4, text="err!")],
        warnings=[BuildMessage(line=5, col=6, text="warn!")],
        notices=[BuildMessage(line=7, col=8, text="notice!")],
    )

    formatted = compile_module.format_build_result(result)

    assert "Megalo compile failed" in formatted
    assert "fatal!" in formatted and "(1:2)" in formatted
    assert "err!" in formatted and "(3:4)" in formatted
    assert "warn!" in formatted and "(5:6)" in formatted
    assert "notice!" in formatted and "(7:8)" in formatted


# -- real compiles against the bundled native extension ------------------------------------------


@_NEEDS_NATIVE_RVT
def test_run_compile_against_a_real_bin(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, source_variant=_JUGGERNAUT_BIN)

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is True
    assert result.output_path == folder / "build" / "dist" / f"{folder.name}.bin"
    assert result.output_path.is_file()


@_NEEDS_NATIVE_RVT
def test_run_compile_with_save_false_writes_nothing(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, source_variant=_JUGGERNAUT_BIN)
    dist_dir = folder / "build" / "dist"

    result = compile_module.run_compile(project_dir, folder, save=False)

    assert result.success is True
    assert result.output_path is None
    assert not dist_dir.exists() or not any(dist_dir.iterdir())


@pytest.mark.skipif(not rvt_bridge.is_available(), reason="native _reachvarianttool extension not available on this platform")
def test_run_compile_falls_back_to_the_packaged_blank_when_init_gametype_bin_is_missing(
    tmp_path: Path,
) -> None:
    # Deliberately not the juggernaut fixture here: its own script references forge-label/
    # scripted-option slots that only *its own* .bin already has pre-allocated (see this module's
    # docstring for why a script like that can only ever compile against its own init_gametype
    # base, never the packaged blank) -- a blank-sourced project's own trivial script has no such
    # requirement, so it's what actually exercises the fallback path successfully.
    blank = resolve_blank_variant(firefight=False)
    project_dir, folder = _project(tmp_path, source_variant=blank)
    new_project.source_variant_path(project_dir, folder).unlink()

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is True, compile_module.format_build_result(result)
    assert result.output_path.is_file()


@_NEEDS_NATIVE_RVT
def test_run_compile_reports_a_real_megalo_syntax_error(tmp_path: Path) -> None:
    project_dir, folder = _project(tmp_path, source_variant=_JUGGERNAUT_BIN)
    (folder / "script" / "output.txt").write_text("this is not valid megalo script @#$%", encoding="utf-8")

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is False
    assert result.fatal_errors or result.errors
    assert not (folder / "build" / "dist" / f"{folder.name}.bin").exists()


@pytest.mark.skipif(not rvt_bridge.is_available(), reason="native _reachvarianttool extension not available on this platform")
def test_run_compile_against_a_blank_firefight_project(tmp_path: Path) -> None:
    blank_ff = resolve_blank_variant(firefight=True)
    project_dir, folder = _project(tmp_path, source_variant=blank_ff)
    settings = json.loads((folder / "settings" / "settings.json").read_text(encoding="utf-8"))
    assert settings["meta"]["is_multiplayer"] is False

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is True
    assert result.output_path.is_file()


@_NEEDS_NATIVE_RVT
def test_run_compile_round_trips_multiplayer_game_settings_and_script_settings(tmp_path: Path) -> None:
    """The strongest available correctness signal for settings_writer.py/strings_writer.py's own
    dozens of individual field-by-field writes: decompile a real fixture, compile that exact
    settings.json back unchanged, then decompile the freshly-compiled .bin -- the resulting
    multiplayer.game_settings/script_settings trees should match what went in.

    title_update_settings' handful of 0.0-2.0-fraction float fields (precision_bloom,
    magnum_damage, magnum_fire_delay, active_camo_energy_curve_min/max) are the one documented
    exception: confirmed (see settings_writer.py's own history) to be a real fixed-point
    quantization inherent to the .bin file format itself -- writing exactly 1.0 and reloading from
    disk reads back ~1.003937, independent of anything this app's own code does -- so those are
    compared with a wider tolerance instead of exact equality.
    """
    from in_reach.app.rvt.decompile import decompile_into_project

    project_dir, folder = _project(tmp_path, source_variant=_JUGGERNAUT_BIN)
    before = json.loads((folder / "settings" / "settings.json").read_text(encoding="utf-8"))
    before_script_settings = json.loads((folder / "settings" / "script_settings.json").read_text(encoding="utf-8"))

    result = compile_module.run_compile(project_dir, folder, save=True)
    assert result.success is True, compile_module.format_build_result(result)

    compare_folder = tmp_path / "compare"
    compare_folder.mkdir()
    decompile_into_project(result.output_path, compare_folder)
    after = json.loads((compare_folder / "settings" / "settings.json").read_text(encoding="utf-8"))
    after_script_settings = json.loads(
        (compare_folder / "settings" / "script_settings.json").read_text(encoding="utf-8")
    )

    before_gs = dict(before["multiplayer"]["game_settings"])
    after_gs = dict(after["multiplayer"]["game_settings"])
    before_tu = before_gs.pop("title_update_settings")
    after_tu = after_gs.pop("title_update_settings")
    assert before_gs == after_gs

    for key, before_value in before_tu.items():
        after_value = after_tu[key]
        if isinstance(before_value, float):
            assert after_value == pytest.approx(before_value, rel=0.05, abs=0.001), key
        else:
            assert after_value == before_value, key

    before_script_settings.pop("$schema", None)
    after_script_settings.pop("$schema", None)
    assert before_script_settings == after_script_settings


@_NEEDS_NATIVE_RVT
def test_run_compile_of_an_unedited_script_reproduces_the_original_action_counts(tmp_path: Path) -> None:
    """Round-trip fidelity regression guard (PROMPT.md: "we want to make sure when we compile or
    decompile a script it processes the code correctly ... i want a working compiler/decompiler we
    can rely on"). Confirmed directly (not guessed): ``mp.compile_script()`` is not a stable fixed
    point over its own ``decompile_script()`` output -- recompiling this exact fixture completely
    unedited used to change 25 triggers/92 actions into 19/91 (some ordinary nested-trigger blocks
    silently recompile as "inline" triggers instead, a non-configurable default the native compiler
    makes on its own). A real, playable .bin can sit close enough to a budget cap that the same
    non-idempotence -- in either direction -- can push it over one even with zero edits, which is
    exactly what every Apply/Export/Launch RVT does to a project the moment it's opened. See
    :mod:`in_reach.app.rvt.compile`'s own "skip recompiling an unchanged script" comment for the fix
    this guards.
    """
    from in_reach.app.rvt.decompile import GENERATED_STATS_FILENAME

    project_dir, folder = _project(tmp_path, source_variant=_JUGGERNAUT_BIN)
    original_stats = json.loads((folder / "build" / GENERATED_STATS_FILENAME).read_text(encoding="utf-8"))

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is True, compile_module.format_build_result(result)
    compiled_stats = json.loads((folder / "build" / GENERATED_STATS_FILENAME).read_text(encoding="utf-8"))
    assert compiled_stats["counts"] == original_stats["counts"]


# -- isolated child process (see compile.py's own module docstring for why compiling runs here) --


def test_run_compile_never_spawns_a_subprocess_for_an_early_validation_failure(
    tmp_path: Path, monkeypatch
) -> None:
    def _fail_if_called(*_args, **_kwargs):
        raise AssertionError("_run_compile_isolated() should never be reached")

    monkeypatch.setattr(compile_module, "_run_compile_isolated", _fail_if_called)
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir(parents=True)
    folder = tmp_path / "abcd1234"
    (folder / "settings").mkdir(parents=True)
    (folder / "settings" / "settings.json").write_text("{not valid json", encoding="utf-8")

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is False
    assert "settings.json" in result.failure


@_NEEDS_NATIVE_RVT
def test_run_compile_isolated_reports_a_crashed_child_process_as_a_build_result(
    tmp_path: Path, monkeypatch
) -> None:
    # The one failure mode this isolation exists to contain (see compile.py's own module
    # docstring): a hard crash in the child process must surface as an ordinary, reportable
    # BuildResult -- never a raised exception or a crash of *this* (the caller's) process.
    import subprocess as subprocess_module

    project_dir, folder = _project(tmp_path, source_variant=_JUGGERNAUT_BIN)

    def _fake_run(*_args, **_kwargs):
        return subprocess_module.CompletedProcess(args=[], returncode=-1073741819, stdout="", stderr="")

    monkeypatch.setattr(compile_module.subprocess, "run", _fake_run)

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is False
    assert "exited unexpectedly" in result.failure


@_NEEDS_NATIVE_RVT
def test_run_compile_isolated_reports_unparseable_child_output_as_a_build_result(
    tmp_path: Path, monkeypatch
) -> None:
    project_dir, folder = _project(tmp_path, source_variant=_JUGGERNAUT_BIN)

    real_run = compile_module.subprocess.run

    def _fake_run(args, **kwargs):
        # Let the real child run, then clobber whatever it wrote to the result file -- simulating
        # e.g. a native call writing stray bytes to the wrong place, or a truncated write.
        completed = real_run(args, **kwargs)
        result_path = Path(args[-1])
        result_path.write_text("not json", encoding="utf-8")
        return completed

    monkeypatch.setattr(compile_module.subprocess, "run", _fake_run)

    result = compile_module.run_compile(project_dir, folder, save=True)

    assert result.success is False
    assert "compile result" in result.failure.lower()
