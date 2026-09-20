from pathlib import Path

import pytest
from click.testing import CliRunner

from in_reach.app import project
from in_reach.cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture(autouse=True)
def stub_ide_launch(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """``in-reach run`` launches a real, blocking Qt window -- every test in this file exercises
    the CLI's project-bootstrap logic only, never the IDE itself, so the actual launch is stubbed
    out everywhere by default. ``test_run_launches_the_ide_against_the_project_dir`` below asserts
    against the call this records."""
    calls: list[Path] = []
    monkeypatch.setattr("in_reach.ide.app.run", lambda project_dir: calls.append(project_dir))
    return calls


def test_help_prints_help_menu(runner: CliRunner) -> None:
    result = runner.invoke(main, ["help"])

    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "run" in result.output
    assert "cfg" in result.output


def test_run_refuses_to_launch_off_windows(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_ide_launch: list[Path]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("in_reach.cli.sys.platform", "linux")

    result = runner.invoke(main, ["run"])

    assert result.exit_code != 0
    assert "windows" in result.output.lower()
    assert stub_ide_launch == []


def test_run_launches_the_ide_against_the_project_dir(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_ide_launch: list[Path]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("in_reach.cli.sys.platform", "win32")

    result = runner.invoke(main, ["run"])

    assert result.exit_code == 0
    assert stub_ide_launch == [project.get_project_dir(tmp_path)]


def test_run_creates_project_on_first_run(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("in_reach.cli.sys.platform", "win32")

    runner.invoke(main, ["run"])

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


def test_run_rechecks_existing_project_instead_of_erroring(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("in_reach.cli.sys.platform", "win32")

    first = runner.invoke(main, ["run"])
    assert first.exit_code == 0

    project_dir = project.get_project_dir(tmp_path)
    env_path = project_dir / ".env"

    # Simulate the project having moved: ROOT_DIR is now stale.
    stale = env_path.read_text().replace(f"ROOT_DIR={tmp_path}", "ROOT_DIR=/somewhere/stale")
    env_path.write_text(stale)

    second = runner.invoke(main, ["run"])
    assert second.exit_code == 0

    values = dict(line.split("=", 1) for line in env_path.read_text().splitlines() if "=" in line)
    assert values["ROOT_DIR"] == str(tmp_path)


def test_run_regenerates_missing_gitignore(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("in_reach.cli.sys.platform", "win32")

    first = runner.invoke(main, ["run"])
    assert first.exit_code == 0

    project_dir = project.get_project_dir(tmp_path)
    gitignore_path = project_dir / ".gitignore"
    gitignore_path.unlink()

    second = runner.invoke(main, ["run"])
    assert second.exit_code == 0

    assert gitignore_path.read_text() == "*\n"


def test_run_writes_a_stub_readme_into_the_in_reach_folder(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PROMPT.md: "please move the generated README.md file to be in generated .in-reach folder".
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("in_reach.cli.sys.platform", "win32")

    result = runner.invoke(main, ["run"])

    assert result.exit_code == 0
    readme_path = project.get_project_dir(tmp_path) / "README.md"
    assert readme_path.is_file()
    assert not (tmp_path / "README.md").exists()  # not at the repo root anymore


def test_run_leaves_an_existing_readme_untouched(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("in_reach.cli.sys.platform", "win32")
    first = runner.invoke(main, ["run"])
    assert first.exit_code == 0

    readme_path = project.get_project_dir(tmp_path) / "README.md"
    readme_path.write_text("my own project notes\n", encoding="utf-8")

    second = runner.invoke(main, ["run"])

    assert second.exit_code == 0
    assert readme_path.read_text(encoding="utf-8") == "my own project notes\n"


def test_cfg_prints_placeholder_menu(runner: CliRunner) -> None:
    result = runner.invoke(main, ["cfg"])

    assert result.exit_code == 0
    assert "placeholder" in result.output.lower()


def test_bare_invocation_shows_help(runner: CliRunner) -> None:
    result = runner.invoke(main, [])

    assert "Usage:" in result.output


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


def test_lint_of_a_folder_that_is_not_a_script_project_says_so(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(main, ["lint", str(tmp_path)])

    assert result.exit_code != 0 and "not a script project" in result.output


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
