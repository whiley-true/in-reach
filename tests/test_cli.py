from pathlib import Path

import pytest
from click.testing import CliRunner

from in_reach.app import project
from in_reach.cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_help_prints_help_menu(runner: CliRunner) -> None:
    result = runner.invoke(main, ["help"])

    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "run" in result.output
    assert "cfg" in result.output


def test_run_prints_run(runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(main, ["run"])

    assert result.exit_code == 0
    assert result.output.strip() == "run test"


def test_run_creates_project_on_first_run(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

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

    first = runner.invoke(main, ["run"])
    assert first.exit_code == 0

    project_dir = project.get_project_dir(tmp_path)
    gitignore_path = project_dir / ".gitignore"
    gitignore_path.unlink()

    second = runner.invoke(main, ["run"])
    assert second.exit_code == 0

    assert gitignore_path.read_text() == "*\n"


def test_cfg_prints_placeholder_menu(runner: CliRunner) -> None:
    result = runner.invoke(main, ["cfg"])

    assert result.exit_code == 0
    assert "placeholder" in result.output.lower()


def test_bare_invocation_shows_help(runner: CliRunner) -> None:
    result = runner.invoke(main, [])

    assert "Usage:" in result.output
