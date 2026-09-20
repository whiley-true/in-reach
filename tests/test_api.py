"""``in_reach.api`` directly (the CLI tests cover it through the command line): shapes, errors and the profile handling."""
import json
import sys
from pathlib import Path

import pytest

from in_reach import api
from in_reach.app import script_preprocess

sys.path.insert(0, str(Path(__file__).parent / "app" / "script_project"))
from hill_project import hill_rush  # noqa: E402

_JUGGERNAUT = Path(__file__).parent / "app" / "rvt" / "resources" / "juggernaut" / "juggernaut.bin"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_a_diagnostic_prints_like_a_compiler_message() -> None:
    d = api.Diagnostic("error", "IR006", "dup", "blocks/a.mgl", 3, 5, "rename it")

    assert str(d) == "blocks/a.mgl:3:5: error: dup [IR006] (rename it)"
    assert str(api.Diagnostic("warning", "", "whole project")) == "warning: whole project"
    assert str(api.Diagnostic("error", "x", "in a file", "project.toml")) == "project.toml: error: in a file [x]"


def test_every_result_serialises_to_versioned_json(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "p")

    for result in (api.check(folder), api.link(folder, write=False), api.profiles(folder), api.show(folder, "megalo")):
        data = json.loads(json.dumps(result.to_dict()))
        assert data["schema"] == api.SCHEMA_VERSION


def test_check_carries_the_raw_link_result_for_front_ends_that_show_more(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "p")

    result = api.check(folder)

    assert result.ok and [m.name for m in result.link_result.project.modules] == ["hill_score", "hill_buff"]
    assert "link_result" not in result.to_dict()


def test_a_broken_project_still_reports_what_it_last_built(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "p")
    api.link(folder)
    (folder / "script" / "blocks" / "setup.mgl").write_text("-- @number a\n-- @number a\n", encoding="utf-8")

    result = api.check(folder)

    assert not result.ok and result.link_map["order"] == ["SETUP", "HILL_PASS", "WIN_CHECK"]


def test_check_and_link_of_a_single_script_project_raise_an_api_error(tmp_path: Path) -> None:
    for call in (api.check, api.link):
        with pytest.raises(api.ApiError) as raised:
            call(tmp_path)
        assert raised.value.exit_code == api.EXIT_PROJECT


def test_show_rejects_an_unknown_view(tmp_path: Path) -> None:
    with pytest.raises(api.ApiError, match="unknown view"):
        api.show(tmp_path, "python")


def test_show_rvt_without_a_build_asks_for_one(tmp_path: Path) -> None:
    with pytest.raises(api.ApiError, match="in-reach build"):
        api.show(tmp_path, "rvt")


def test_show_rvt_writes_the_decompiled_view(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from in_reach.app import new_project, output_view

    built = new_project.compiled_variant_path(tmp_path)
    built.parent.mkdir(parents=True)
    built.write_bytes(b"bin")
    monkeypatch.setattr(output_view, "write_decompiled_view", lambda folder: _write(folder / "build" / "Decompiled.txt", "-- x\n"))

    result = api.show(tmp_path, "rvt")

    assert result.view == "rvt" and result.text == "-- x\n" and result.path.endswith("Decompiled.txt")


def test_the_decompiled_view_of_a_real_build_shows_the_built_script(tmp_path: Path) -> None:
    from in_reach.app import new_project, project
    from in_reach.app.rvt import rvt_bridge

    if not (_JUGGERNAUT.is_file() and rvt_bridge.is_available()):
        pytest.skip("fixture .bin or native module not available")
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir(parents=True)
    folder, _ = new_project.create_gametype_project(project_dir, "Decompile Me", source_variant=_JUGGERNAUT)
    hill_rush(
        folder,
        modules__hill_score__hill_score_dot_mgl="-- @fragment HILL_PASS.score\n-- @loop player\ncurrent_player.score += 1\n",
        modules__hill_buff__hill_buff_dot_mgl="-- @fragment HILL_PASS.buff\n-- @loop player\ncurrent_player.score += 2\n",
    )

    built = api.build(folder)
    shown = api.show(folder, "rvt")

    assert built.success, built.diagnostics
    assert shown.text.startswith("-- This file is auto-generated and non-editable")
    assert "current_player.score += 1" in shown.text and "@" not in shown.text  # the built script: no annotations, no modules
    assert shown.path == str(folder / "build" / "Decompiled.txt")


def test_build_uses_a_profile_for_that_build_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = hill_rush(tmp_path / "p")
    (folder / "script" / "env" / "release.env").write_text("FLAGS=RELEASE\n", encoding="utf-8")
    script_preprocess.set_active_profile(folder, "dev")
    seen = []

    class Result:
        success, fatal_errors, errors, warnings, notices, failure, output_path = True, [], [], [], [], None, None

    def fake_run_compile(project_dir, f, *, save):
        seen.append((script_preprocess.active_profile_name(f), save))
        return Result()

    monkeypatch.setattr("in_reach.app.rvt.rvt_bridge.is_available", lambda: True)
    monkeypatch.setattr("in_reach.app.rvt.compile.run_compile", fake_run_compile)

    outcome = api.build(folder, profile="release", dry_run=True)

    assert outcome.success and seen == [("release", False)]
    assert script_preprocess.active_profile_name(folder) == "dev"  # put back


def test_build_restores_the_profile_even_when_the_compile_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = hill_rush(tmp_path / "p")
    (folder / "script" / "env" / "release.env").write_text("FLAGS=RELEASE\n", encoding="utf-8")
    script_preprocess.set_active_profile(folder, "dev")
    monkeypatch.setattr("in_reach.app.rvt.rvt_bridge.is_available", lambda: True)

    def boom(*a, **k):
        raise RuntimeError("native crash")

    monkeypatch.setattr("in_reach.app.rvt.compile.run_compile", boom)

    with pytest.raises(RuntimeError):
        api.build(folder, profile="release")

    assert script_preprocess.active_profile_name(folder) == "dev"


def test_build_with_an_unknown_profile_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = hill_rush(tmp_path / "p")
    monkeypatch.setattr("in_reach.app.rvt.rvt_bridge.is_available", lambda: True)

    with pytest.raises(api.ApiError, match="no profile named 'nope'"):
        api.build(folder, profile="nope")


def test_build_merges_every_message_kind_into_diagnostics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from in_reach.app.rvt.compile import BuildMessage

    class Result:
        success = False
        fatal_errors = [BuildMessage(line=1, col=1, text="fatal")]
        errors = [BuildMessage(line=2, col=3, text="err", file="blocks/a.mgl", code="X")]
        warnings = [BuildMessage(line=0, col=0, text="warn")]
        notices = [BuildMessage(line=0, col=0, text="note")]
        failure = "failed"
        output_path = None

    monkeypatch.setattr("in_reach.app.rvt.rvt_bridge.is_available", lambda: True)
    monkeypatch.setattr("in_reach.app.rvt.compile.run_compile", lambda *a, **k: Result())

    outcome = api.build(tmp_path)

    assert [(d.severity, d.message) for d in outcome.diagnostics] == [
        ("error", "fatal"), ("error", "err"), ("warning", "warn"), ("notice", "note")
    ]
    assert outcome.diagnostics[1].file == "blocks/a.mgl" and outcome.diagnostics[1].code == "X" and outcome.failure == "failed"


def test_the_in_reach_folder_goes_with_the_project_next_to_it(tmp_path: Path) -> None:
    assert api._project_dir(tmp_path / "abc12345") == tmp_path / ".in-reach"


def test_set_profile_reports_the_new_state(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path / "p")

    assert api.set_profile(folder, "dev").active == "dev"
    assert api.set_profile(folder, None).active is None


def test_new_gametype_project_makes_the_workspace_when_it_is_missing(tmp_path: Path) -> None:
    if not _JUGGERNAUT.is_file():
        pytest.skip("fixture .bin not present")

    folder = api.new_gametype_project(tmp_path, "Fresh", source_variant=_JUGGERNAUT)

    assert (tmp_path / ".in-reach").is_dir() and folder.parent == tmp_path and (folder / "settings" / "settings.json").is_file()
