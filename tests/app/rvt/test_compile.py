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


@pytest.mark.skipif(not rvt_bridge.is_available(), reason="native _reachvarianttool extension not available on this platform")
def test_run_compile_applies_edited_firefight_settings(tmp_path: Path) -> None:
    """Regression guard for the bug this test's own edits reproduce without
    settings_writer.apply_firefight_settings(): a Firefight project's own settings.json edits used
    to never reach the compiled .bin at all (compile.py's own Firefight branch only ever called
    apply_meta_header()), so the very next Apply's own build/dist/*.bin resync
    (in_reach.app.rvt.decompile.resync_from_bin, wired to MainWindow's own bin-file-watcher) would
    silently overwrite settings/settings.json right back to the *unedited* values -- confirmed by
    direct reproduction (edit firefight.wave_limit, compile, re-decompile the output -- it came back
    unchanged) before apply_firefight_settings() existed.

    Covers one representative field from each writable subsection (scenario flags/scalars, base
    traits, elite respawn options, the general/respawn/social/map/team/loadout options tree, round
    skulls, custom skulls, bonus wave skulls) -- NOT wave.squads, see the next test for why.
    """
    from in_reach.app.rvt.decompile import decompile_into_project

    blank_ff = resolve_blank_variant(firefight=True)
    project_dir, folder = _project(tmp_path, source_variant=blank_ff)
    settings_path = folder / "settings" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    ff = settings["firefight"]

    ff["hazards_enabled"] = True
    ff["wave_limit"] = 42
    ff["bonus_target"] = 12345
    ff["starting_lives_spartan"] = 7
    ff["base_traits_spartan"]["defense"]["vampirism"] = "value_050"
    ff["base_traits_wave"]["vision"] = "eagle_eye"
    ff["elite_respawn_options"]["lives_per_round"] = 9
    ff["options"]["general_settings"]["time_limit"] = 15
    ff["options"]["respawn_settings"]["respawn_time"] = 6
    ff["options"]["social_settings"]["friendly_fire"] = True
    ff["options"]["map_and_game_settings"]["grenades"] = False
    ff["options"]["team_settings"]["teams"][0]["color_primary"] = 3
    ff["options"]["loadout_settings"]["spartan_loadouts_enabled"] = True
    ff["rounds"][0]["skulls"]["iron"] = True
    ff["custom_skulls"][0]["traits_spartan"]["defense"]["headshot_immune"] = "enabled"
    ff["bonus_wave_skulls"]["famine"] = True
    settings_path.write_text(json.dumps(settings), encoding="utf-8")

    result = compile_module.run_compile(project_dir, folder, save=True)
    assert result.success is True, compile_module.format_build_result(result)

    compare_folder = tmp_path / "compare"
    compare_folder.mkdir()
    decompile_into_project(result.output_path, compare_folder)
    after = json.loads((compare_folder / "settings" / "settings.json").read_text(encoding="utf-8"))["firefight"]

    assert after["hazards_enabled"] is True
    assert after["wave_limit"] == 42
    assert after["bonus_target"] == 12345
    assert after["starting_lives_spartan"] == 7
    assert after["base_traits_spartan"]["defense"]["vampirism"] == "value_050"
    assert after["base_traits_wave"]["vision"] == "eagle_eye"
    assert after["elite_respawn_options"]["lives_per_round"] == 9
    assert after["options"]["general_settings"]["time_limit"] == 15
    assert after["options"]["respawn_settings"]["respawn_time"] == 6
    assert after["options"]["social_settings"]["friendly_fire"] is True
    assert after["options"]["map_and_game_settings"]["grenades"] is False
    assert after["options"]["team_settings"]["teams"][0]["color_primary"] == 3
    assert after["options"]["loadout_settings"]["spartan_loadouts_enabled"] is True
    assert after["rounds"][0]["skulls"]["iron"] is True
    assert after["custom_skulls"][0]["traits_spartan"]["defense"]["headshot_immune"] == "enabled"
    assert after["bonus_wave_skulls"]["famine"] is True


@pytest.mark.skipif(not rvt_bridge.is_available(), reason="native _reachvarianttool extension not available on this platform")
def test_run_compile_cannot_apply_firefight_wave_squads(tmp_path: Path) -> None:
    """Documents the one known gap in apply_firefight_settings() (see its own docstring): the
    bundled _reachvarianttool extension exposes FirefightWave.squad(i) as read-only (no setter
    exists in the native bindings at all), so an edited squad list currently has no effect on
    compile -- unlike every other firefight field, which test_run_compile_applies_edited_firefight_
    settings confirms does apply. This is a regression guard the *other* direction: if a future
    native-extension update adds a squad setter and nobody notices, this starts failing (the output
    would then actually match the edit) as a prompt to also update apply_firefight_settings()."""
    from in_reach.app.rvt.decompile import decompile_into_project

    blank_ff = resolve_blank_variant(firefight=True)
    project_dir, folder = _project(tmp_path, source_variant=blank_ff)
    settings_path = folder / "settings" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    original_squads = settings["firefight"]["rounds"][0]["wave_initial"]["squads"]
    settings["firefight"]["rounds"][0]["wave_initial"]["squads"] = ["brutes"] * len(original_squads)
    settings_path.write_text(json.dumps(settings), encoding="utf-8")

    result = compile_module.run_compile(project_dir, folder, save=True)
    assert result.success is True, compile_module.format_build_result(result)

    compare_folder = tmp_path / "compare"
    compare_folder.mkdir()
    decompile_into_project(result.output_path, compare_folder)
    after = json.loads((compare_folder / "settings" / "settings.json").read_text(encoding="utf-8"))

    assert after["firefight"]["rounds"][0]["wave_initial"]["squads"] == original_squads


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
def test_run_compile_does_not_re_stamp_meta_generated_at(tmp_path: Path) -> None:
    """PROMPT.md: "we want to update our compiling process so it no longers updates a game's
    created at ... this is because every compile was updating this value and causing git changes[;]
    instead created at and modified at should be set to the same value of when the gametype was
    created in in-reach" -- traced to settings/settings.json's own meta.generated_at, which
    extraction.py's _extract_meta() always stamps fresh with datetime.now() on its own; compile.py's
    own write_build_snapshot() call now reads this project's already-established value back via
    settings_io.load_meta_generated_at() and carries it forward instead, so two real compiles of the
    same project produce the exact same build/settings.autogenerated.json meta.generated_at rather
    than a fresh one every time (a real, VCS-tracked-churn bug once settings/settings.json itself
    gets resynced from the same freshly-compiled .bin, see test_decompile.py's own
    test_resync_from_bin_carries_generated_at_through for that other half)."""
    import time

    project_dir, folder = _project(tmp_path, source_variant=_JUGGERNAUT_BIN)
    build_settings_path = folder / "build" / "settings.autogenerated.json"
    before = json.loads(build_settings_path.read_text(encoding="utf-8"))["meta"]["generated_at"]

    time.sleep(1.1)
    result = compile_module.run_compile(project_dir, folder, save=True)
    assert result.success is True, compile_module.format_build_result(result)

    after = json.loads(build_settings_path.read_text(encoding="utf-8"))["meta"]["generated_at"]
    assert after == before


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


# -- message positions ----------------------------------------------------------------------------------------


class _NativeMessage:
    def __init__(self, line: int, col: int, text: str) -> None:
        self.line, self.col, self.text = line, col, text


def test_native_line_numbers_are_shifted_to_one_based_and_columns_left_alone() -> None:
    """The native compiler numbers lines from 0 and columns from 1 (measured: a bad call at the start of
    the first line reports (0, 1); indented five spaces on the second, (1, 6)). Unshifted, every error
    pointed one line above the one that was wrong."""
    first, indented = compile_module._messages([_NativeMessage(0, 1, "a"), _NativeMessage(1, 6, "b")])
    assert (first.line, first.col) == (1, 1)
    assert (indented.line, indented.col) == (2, 6)
    assert [first.text, indented.text] == ["a", "b"]


def test_a_real_native_error_reports_the_line_the_user_sees_in_their_editor(tmp_path) -> None:
    from in_reach.app.rvt import rvt_bridge

    if not rvt_bridge.is_available():
        pytest.skip("native extension not available")
    rvt = rvt_bridge.get_rvt()
    from in_reach.app.blank_variant import resolve_blank_variant

    variant = rvt.load(str(resolve_blank_variant(firefight=False)))
    result = variant.multiplayer.compile_script("game.end_round()\n\n   this_is_not_a_real_call()\n")  # line 3, col 4
    [message] = compile_module._messages(list(result.fatal_errors) + list(result.errors))
    assert (message.line, message.col) == (3, 4)
