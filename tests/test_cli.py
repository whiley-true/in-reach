import json
import sys
import types
from pathlib import Path

import pytest
from click.testing import CliRunner

from in_reach import api
from in_reach.app import project
from in_reach.cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _hill_rush(folder: Path, **changes):
    sys.path.insert(0, str(Path(__file__).parent / "app" / "script_project"))
    from hill_project import hill_rush

    return hill_rush(folder, **changes)


def test_help_prints_help_menu(runner: CliRunner) -> None:
    result = runner.invoke(main, ["help"])

    assert result.exit_code == 0
    assert "Usage:" in result.output
    for command in ("run", "cfg", "build", "check", "link", "show", "verify", "vcs", "launch", "new-module", "env"):
        assert command in result.output


# -- run: hands over to the IDE package ---------------------------------------------------------------------


def test_run_without_the_ide_installed_says_how_to_get_it_and_exits_2(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "in_reach_ide.cli", None)  # what a missing package looks like to import_module

    result = runner.invoke(main, ["run"])

    assert result.exit_code == 2
    assert "pip install in-reach-ide" in result.output


def test_run_launches_the_installed_ide(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    launched = []
    fake_ide = types.ModuleType("in_reach_ide.cli")
    fake_ide.launch = lambda: launched.append(True)
    monkeypatch.setitem(sys.modules, "in_reach_ide", types.ModuleType("in_reach_ide"))
    monkeypatch.setitem(sys.modules, "in_reach_ide.cli", fake_ide)

    result = runner.invoke(main, ["run"])

    assert result.exit_code == 0 and launched == [True]


# -- verify: the workspace bootstrap ---------------------------------------------------------------------------


def test_verify_creates_the_workspace_on_first_run(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(main, ["verify", "--root", str(tmp_path)])

    assert result.exit_code == 0, result.output
    project_dir = project.get_project_dir(tmp_path)
    assert project_dir.is_dir()

    env_path = project_dir / ".env"
    assert env_path.is_file()
    assert not (project_dir / "example.env").exists()
    assert (project_dir / ".gitignore").is_file()

    values = dict(line.split("=", 1) for line in env_path.read_text().splitlines() if "=" in line)
    assert values["ROOT_DIR"] == str(tmp_path)
    assert values["IS_WINDOWS"] in ("true", "false")
    assert values["LOG_LEVEL"] == "INFO"
    assert values["LOG_LINES"] == "1000"
    assert values["OUTPUT_TO_STREAM"] == "false"
    assert values["LOG_DIR"]
    assert values["LOG_FILE"]


def test_verify_rechecks_an_existing_workspace_instead_of_erroring(runner: CliRunner, tmp_path: Path) -> None:
    assert runner.invoke(main, ["verify", "--root", str(tmp_path)]).exit_code == 0
    env_path = project.get_project_dir(tmp_path) / ".env"
    env_path.write_text(env_path.read_text().replace(f"ROOT_DIR={tmp_path}", "ROOT_DIR=/somewhere/stale"))  # the project moved

    second = runner.invoke(main, ["verify", "--root", str(tmp_path)])

    assert second.exit_code == 0
    values = dict(line.split("=", 1) for line in env_path.read_text().splitlines() if "=" in line)
    assert values["ROOT_DIR"] == str(tmp_path)


def test_verify_regenerates_a_missing_gitignore(runner: CliRunner, tmp_path: Path) -> None:
    runner.invoke(main, ["verify", "--root", str(tmp_path)])
    gitignore = project.get_project_dir(tmp_path) / ".gitignore"
    gitignore.unlink()

    assert runner.invoke(main, ["verify", "--root", str(tmp_path)]).exit_code == 0

    assert gitignore.read_text() == "*\n"


def test_verify_writes_a_stub_readme_into_the_in_reach_folder_and_keeps_an_edited_one(runner: CliRunner, tmp_path: Path) -> None:
    runner.invoke(main, ["verify", "--root", str(tmp_path)])
    readme = project.get_project_dir(tmp_path) / "README.md"
    assert readme.is_file() and not (tmp_path / "README.md").exists()

    readme.write_text("my own project notes\n", encoding="utf-8")
    runner.invoke(main, ["verify", "--root", str(tmp_path)])

    assert readme.read_text(encoding="utf-8") == "my own project notes\n"


def test_verify_json_lists_the_verified_keys(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(main, ["verify", "--root", str(tmp_path), "--format", "json"])

    data = json.loads(result.output)
    assert data["schema"] == api.SCHEMA_VERSION and data["ok"] is True and isinstance(data["verified"], dict)


def test_cfg_prints_placeholder_menu(runner: CliRunner) -> None:
    result = runner.invoke(main, ["cfg"])

    assert result.exit_code == 0
    assert "placeholder" in result.output.lower()


def test_bare_invocation_shows_help(runner: CliRunner) -> None:
    result = runner.invoke(main, [])

    assert "Usage:" in result.output


# -- json output and exit codes ---------------------------------------------------------------------------------


def test_check_json_is_versioned_and_carries_located_diagnostics(runner: CliRunner, tmp_path: Path) -> None:
    folder = _hill_rush(tmp_path / "proj", blocks__setup_dot_mgl="-- @number a\n-- @number a\n")

    result = runner.invoke(main, ["check", str(folder), "--format", "json"])

    data = json.loads(result.output)
    assert result.exit_code == 1 and data["schema"] == api.SCHEMA_VERSION and data["ok"] is False
    [problem] = [d for d in data["diagnostics"] if d["code"] == "IR006"]
    assert set(problem) == {"severity", "code", "message", "file", "line", "column", "hint"}
    assert (problem["severity"], problem["file"], problem["line"], problem["column"]) == ("error", "blocks/setup.mgl", 2, 1)
    assert "rename" in problem["hint"]


def test_check_json_of_a_clean_project_has_the_link_map(runner: CliRunner, tmp_path: Path) -> None:
    folder = _hill_rush(tmp_path / "proj")

    data = json.loads(runner.invoke(main, ["check", str(folder), "--format", "json"]).output)

    assert data["ok"] is True and data["link_map"]["order"] == ["SETUP", "HILL_PASS", "WIN_CHECK"]


def test_a_folder_with_no_script_exits_1_in_either_format(runner: CliRunner, tmp_path: Path) -> None:
    text = runner.invoke(main, ["check", str(tmp_path)])
    data = runner.invoke(main, ["check", str(tmp_path), "--format", "json"])

    assert text.exit_code == 1 and "has no script" in text.output
    assert data.exit_code == 1 and json.loads(data.output)["ok"] is False


def test_link_json_lists_what_was_written(runner: CliRunner, tmp_path: Path) -> None:
    folder = _hill_rush(tmp_path / "proj")

    data = json.loads(runner.invoke(main, ["link", str(folder), "--format", "json"]).output)

    assert "build/Compiled.txt" in data["written"] and data["settings_changed"] is True


def test_build_reports_a_missing_native_module_as_exit_2(runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("in_reach.app.rvt.rvt_bridge.is_available", lambda: False)

    result = runner.invoke(main, ["build", str(tmp_path), "--format", "json"])

    assert result.exit_code == 2 and json.loads(result.output)["ok"] is False


def test_build_passes_its_options_to_the_api_and_exits_by_the_result(runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_build(folder, *, env=None, dry_run=False):
        calls.append((folder, env, dry_run))
        return api.BuildOutcome(False, [api.Diagnostic("error", "X1", "boom", "blocks/a.mgl", 3, 4)], "Megalo compile failed")

    monkeypatch.setattr(api, "build", fake_build)

    text = runner.invoke(main, ["build", str(tmp_path), "--env", "release", "--dry-run"])
    data = json.loads(runner.invoke(main, ["build", str(tmp_path), "--format", "json"]).output)

    assert calls[0] == (tmp_path, "release", True) and text.exit_code == 1
    assert "blocks/a.mgl:3:4: error: boom [X1]" in text.output and "1 error, 0 warnings" in text.output
    assert data["ok"] is False and data["failure"] == "Megalo compile failed" and data["diagnostics"][0]["line"] == 3


def test_build_succeeds_and_says_where_the_bin_went(runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "build", lambda folder, **k: api.BuildOutcome(True, [], None, "x/dist/p.bin"))

    result = runner.invoke(main, ["build", str(tmp_path)])

    assert result.exit_code == 0 and "built x/dist/p.bin" in result.output


def test_export_copies_the_built_bin(runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    built = tmp_path / "p.bin"
    built.write_bytes(b"bin")
    monkeypatch.setattr(api, "build", lambda folder, **k: api.BuildOutcome(True, [], None, str(built)))
    out = tmp_path / "out"

    result = runner.invoke(main, ["export", str(tmp_path), "--out", str(out), "--format", "json"])

    assert result.exit_code == 0 and (out / "p.bin").read_bytes() == b"bin" if out.is_dir() else (out.read_bytes() == b"bin")


# -- show ---------------------------------------------------------------------------------------------------------


def test_show_megalo_prints_every_source_file_of_a_script_project(runner: CliRunner, tmp_path: Path) -> None:
    folder = _hill_rush(tmp_path / "proj")

    result = runner.invoke(main, ["show", str(folder), "--view", "megalo"])

    assert "-- ==== blocks/setup.mgl (block:SETUP) ====" in result.output and "-- @fragment HILL_PASS.score" in result.output


def test_show_megalo_of_a_single_script_is_output_txt(runner: CliRunner, tmp_path: Path) -> None:
    (tmp_path / "script").mkdir()
    (tmp_path / "script" / "output.txt").write_text("global.number[0] = 1\n", encoding="utf-8")

    assert runner.invoke(main, ["show", str(tmp_path), "--view", "megalo"]).output == "global.number[0] = 1\n"


def test_show_rvt_plus_is_the_linked_script_with_the_profile_applied(runner: CliRunner, tmp_path: Path) -> None:
    folder = _hill_rush(tmp_path / "proj")

    data = json.loads(runner.invoke(main, ["show", str(folder), "--view", "rvt+", "--format", "json"]).output)

    assert data["view"] == "rvt+" and data["path"].endswith("Compiled.txt") and "alias g_phase" in data["text"]


def test_show_rvt_before_any_build_says_to_build_first(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(main, ["show", str(tmp_path), "--view", "rvt"])

    assert result.exit_code == 1 and "in-reach build" in result.output


def test_show_needs_a_view(runner: CliRunner, tmp_path: Path) -> None:
    assert runner.invoke(main, ["show", str(tmp_path)]).exit_code == 2  # click's usage error


# -- scaffolding and envs -------------------------------------------------------------------------------------


def test_create_project_and_new_module_scaffold_a_script_project(runner: CliRunner, tmp_path: Path) -> None:
    (tmp_path / "script").mkdir()
    (tmp_path / "script" / "output.txt").write_text("x = 1\n", encoding="utf-8")

    created = runner.invoke(main, ["create-project", str(tmp_path), "--format", "json"])
    module = runner.invoke(main, ["new-module", "extras", str(tmp_path)])

    assert json.loads(created.output)["written"] == ["script/project.toml", "script/blocks/main.mgl"]
    assert module.exit_code == 0 and "script/modules/extras/module.toml" in module.output
    assert runner.invoke(main, ["check", str(tmp_path)]).exit_code == 0


def test_create_project_twice_is_refused_with_exit_1(runner: CliRunner, tmp_path: Path) -> None:
    (tmp_path / "script").mkdir()
    runner.invoke(main, ["create-project", str(tmp_path)])

    assert runner.invoke(main, ["create-project", str(tmp_path)]).exit_code == 1


def test_profiles_are_listed_and_chosen(runner: CliRunner, tmp_path: Path) -> None:
    folder = _hill_rush(tmp_path / "proj")
    (folder / "script" / "env" / "release.env").write_text("FLAGS=RELEASE\nSCORE_TO_WIN=50\n", encoding="utf-8")

    listed = json.loads(runner.invoke(main, ["env", "list", str(folder), "--format", "json"]).output)
    chosen = runner.invoke(main, ["env", "set", "release", "--folder", str(folder)])
    cleared = runner.invoke(main, ["env", "set", "--none", "--folder", str(folder), "--format", "json"])

    assert listed["envs"] == ["dev", "release"]
    assert "active env: release" in chosen.output
    assert json.loads(cleared.output)["active"] is None


def test_choosing_a_profile_that_does_not_exist_is_refused(runner: CliRunner, tmp_path: Path) -> None:
    folder = _hill_rush(tmp_path / "proj")

    result = runner.invoke(main, ["env", "set", "nope", "--folder", str(folder)])

    assert result.exit_code == 1 and "no env named" in result.output


def test_profile_set_needs_a_name_or_none(runner: CliRunner, tmp_path: Path) -> None:
    assert runner.invoke(main, ["env", "set", "--folder", str(tmp_path)]).exit_code == 2
    assert runner.invoke(main, ["env", "set", "dev", "--none", "--folder", str(tmp_path)]).exit_code == 2


# -- launch -------------------------------------------------------------------------------------------------------


def test_launch_rvt_opens_the_built_bin(runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from in_reach.app import new_project

    opened = []
    monkeypatch.setattr("in_reach.app.rvt_launcher.launch_rvt", lambda target=None: opened.append(target))
    built = new_project.compiled_variant_path(tmp_path)
    built.parent.mkdir(parents=True)
    built.write_bytes(b"bin")

    result = runner.invoke(main, ["launch", "rvt", str(tmp_path)])

    assert result.exit_code == 0 and opened == [built]


def test_launch_rvt_before_a_build_is_refused(runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("in_reach.app.rvt_launcher.launch_rvt", lambda target=None: pytest.fail("launched"))

    result = runner.invoke(main, ["launch", "rvt", str(tmp_path)])

    assert result.exit_code == 1 and "in-reach build" in result.output


def test_launch_rvt_with_no_project_just_opens_rvt(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    opened = []
    monkeypatch.setattr("in_reach.app.rvt_launcher.launch_rvt", lambda target=None: opened.append(target))

    assert runner.invoke(main, ["launch", "rvt"]).exit_code == 0 and opened == [None]


def test_launch_mcc(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    launched = []
    monkeypatch.setattr("in_reach.app.mcc_launcher.launch_mcc", lambda open_uri=None: launched.append(True))

    assert runner.invoke(main, ["launch", "mcc"]).exit_code == 0 and launched == [True]


# -- vcs ----------------------------------------------------------------------------------------------------------


def test_vcs_status_commit_and_log(runner: CliRunner, tmp_path: Path) -> None:
    folder = _hill_rush(tmp_path / "proj")
    runner.invoke(main, ["vcs", "status", str(folder)])  # the first use starts the history from the project as it is
    (folder / "script" / "notes.txt").write_text("hello\n", encoding="utf-8")

    status = json.loads(runner.invoke(main, ["vcs", "status", str(folder), "--format", "json"]).output)
    committed = runner.invoke(main, ["vcs", "commit", "--all", "-m", "first", str(folder)])
    log = json.loads(runner.invoke(main, ["vcs", "log", str(folder), "--format", "json"]).output)
    after = runner.invoke(main, ["vcs", "status", str(folder)])

    assert status["branch"] and any(c["path"] == "script/notes.txt" for c in status["changes"])
    assert committed.exit_code == 0, committed.output
    assert log["commits"][0]["message"].endswith("first")
    assert "nothing to commit" in after.output


def test_vcs_stamp_records_a_version(runner: CliRunner, tmp_path: Path) -> None:
    folder = _hill_rush(tmp_path / "proj")

    stamped = runner.invoke(main, ["vcs", "stamp", "-m", "release", "--version", "1.2.3", str(folder)])
    log = json.loads(runner.invoke(main, ["vcs", "log", str(folder), "--format", "json"]).output)

    assert stamped.exit_code == 0, stamped.output
    assert log["commits"][0]["version"] == "1.2.3"


def test_vcs_branches_can_be_made_switched_merged_and_deleted(runner: CliRunner, tmp_path: Path) -> None:
    folder = _hill_rush(tmp_path / "proj")
    base = json.loads(runner.invoke(main, ["vcs", "branches", str(folder), "--format", "json"]).output)["current"]

    made = runner.invoke(main, ["vcs", "branch", "Feature X", str(folder)])  # makes it and moves onto it
    listed = json.loads(runner.invoke(main, ["vcs", "branches", str(folder), "--format", "json"]).output)
    back = runner.invoke(main, ["vcs", "switch", base, str(folder)])
    merged = runner.invoke(main, ["vcs", "merge", "feature-x", str(folder)])
    deleted = runner.invoke(main, ["vcs", "delete", "feature-x", str(folder)])

    assert made.output.strip() == "feature-x"  # branch names are sanitised
    assert listed["current"] == "feature-x" and {base, "feature-x"} <= set(listed["branches"])
    assert all(r.exit_code == 0 for r in (back, merged, deleted)), [r.output for r in (back, merged, deleted)]


def test_vcs_refuses_bad_input_with_exit_1(runner: CliRunner, tmp_path: Path) -> None:
    folder = _hill_rush(tmp_path / "proj")

    assert runner.invoke(main, ["vcs", "switch", "no-such-branch", str(folder)]).exit_code == 1
    assert runner.invoke(main, ["vcs", "commit", "-m", "empty", str(folder)]).exit_code == 1  # nothing staged


# -- new ------------------------------------------------------------------------------------------------------------


def test_new_without_the_native_module_exits_2_and_creates_nothing(runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("in_reach.app.rvt.rvt_bridge.is_available", lambda: False)

    result = runner.invoke(main, ["new", "My Game", "--root", str(tmp_path), "--format", "json"])

    assert result.exit_code == 2 and json.loads(result.output)["ok"] is False and not (tmp_path / ".in-reach").exists()


def test_new_creates_a_gametype_project_from_a_bin(runner: CliRunner, tmp_path: Path) -> None:
    from in_reach.app.rvt import rvt_bridge

    source = Path(__file__).parent / "app" / "rvt" / "resources" / "juggernaut" / "juggernaut.bin"
    if not (source.is_file() and rvt_bridge.is_available()):
        pytest.skip("fixture .bin or native module not available")

    result = runner.invoke(main, ["new", "My Game", "--from", str(source), "--root", str(tmp_path), "--format", "json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    folder = Path(data["folder"])
    assert (folder / "settings" / "settings.json").is_file() and (folder / "script").is_dir()
    assert data["built"] is True and (folder / "build" / "docs" / "overview.md").is_file()  # built once straight away


def test_new_with_no_build_leaves_it_unbuilt(runner: CliRunner, tmp_path: Path) -> None:
    from in_reach.app import new_project
    from in_reach.app.rvt import rvt_bridge

    source = Path(__file__).parent / "app" / "rvt" / "resources" / "juggernaut" / "juggernaut.bin"
    if not (source.is_file() and rvt_bridge.is_available()):
        pytest.skip("fixture .bin or native module not available")

    result = runner.invoke(main, ["new", "My Game", "--from", str(source), "--root", str(tmp_path), "--no-build", "--format", "json"])

    folder = Path(json.loads(result.output)["folder"])
    assert result.exit_code == 0 and json.loads(result.output)["built"] is False
    assert not new_project.compiled_variant_path(folder).exists()


# -- script projects ------------------------------------------------------------------------------------


@pytest.fixture
def hill(tmp_path: Path) -> Path:
    import sys

    sys.path.insert(0, str(Path(__file__).parent / "app" / "script_project"))
    from hill_project import hill_rush

    return hill_rush(tmp_path / "proj")


def test_lint_reports_a_clean_project(runner: CliRunner, hill: Path) -> None:
    result = runner.invoke(main, ["lint", str(hill)])

    assert result.exit_code == 0 and "0 errors, 0 warnings" in result.output
    assert not (hill / "build").exists()  # lint writes nothing


def test_lint_reports_each_problem_at_its_file_and_line_and_exits_nonzero(runner: CliRunner, tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).parent / "app" / "script_project"))
    from hill_project import hill_rush

    folder = hill_rush(tmp_path / "proj", blocks__setup_dot_mgl="-- @number a\n-- @number a\n")

    result = runner.invoke(main, ["lint", str(folder)])

    assert result.exit_code == 1
    assert "blocks/setup.mgl:2" in result.output and "[IR006]" in result.output
    assert "1 error, 0 warnings" in result.output


def test_lint_defaults_to_the_current_directory(runner: CliRunner, hill: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(hill)

    result = runner.invoke(main, ["lint"])

    assert result.exit_code == 0 and "0 errors" in result.output


def test_lint_of_a_folder_with_no_script_says_so(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(main, ["lint", str(tmp_path)])

    assert result.exit_code != 0 and "has no script" in result.output


def test_link_writes_the_build_and_reports_what_it_did(runner: CliRunner, hill: Path) -> None:
    result = runner.invoke(main, ["link", str(hill)])

    assert result.exit_code == 0, result.output
    assert "blocks   SETUP -> HILL_PASS -> WIN_CHECK" in result.output
    assert "fused    HILL_PASS <- hill_score.score + hill_buff.buff" in result.output
    assert "global.number 2/12" in result.output
    assert "wrote    build/Compiled.txt" in result.output
    assert (hill / "build" / "Compiled.txt").is_file()


def test_link_dry_run_writes_nothing(runner: CliRunner, hill: Path) -> None:
    result = runner.invoke(main, ["link", "--dry-run", str(hill)])

    assert result.exit_code == 0 and "dry run: nothing written" in result.output
    assert not (hill / "build").exists() and not (hill / "settings").exists()


def test_link_of_a_broken_project_fails_and_writes_nothing(runner: CliRunner, tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).parent / "app" / "script_project"))
    from hill_project import hill_rush

    folder = hill_rush(tmp_path / "proj", project_dot_toml="[project\n")

    result = runner.invoke(main, ["link", str(folder)])

    assert result.exit_code != 0 and "nothing was written" in result.output
    assert not (folder / "build").exists()


def test_link_lists_a_merge_it_declined_with_the_reason(runner: CliRunner, tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).parent / "app" / "script_project"))
    from hill_project import hill_rush

    folder = hill_rush(
        tmp_path / "proj",
        modules__hill_score__hill_score_dot_mgl="-- @fragment HILL_PASS.score\n-- @loop player\n-- @fusion never\nx = 1\n",
    )

    result = runner.invoke(main, ["link", "--dry-run", str(folder)])

    assert "kept     hill_score.score | hill_buff.buff: @fusion never" in result.output


def test_help_lists_the_script_project_commands(runner: CliRunner) -> None:
    result = runner.invoke(main, ["help"])

    assert "lint" in result.output and "link" in result.output
