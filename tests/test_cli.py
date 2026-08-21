import logging

from click.testing import CliRunner

from inreach.app.setup import setup_proj
from inreach.cli import cli, main


def test_verify_command_logs_starting_verification(caplog):
    with caplog.at_level(logging.INFO, logger="inreach"):
        main(["verify"])
    assert "Starting verification" in caplog.text


def test_no_command_prints_help():
    result = CliRunner().invoke(cli, [])
    assert "usage" in result.output.lower()


def test_init_command_declines_creates_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["init"], input="2\n")  # Exit

    assert result.exit_code == 0
    assert not (tmp_path / ".inreach").exists()


def test_init_command_creates_project_and_runs_setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    called = []
    monkeypatch.setattr(setup_proj, "setup_project", lambda project_dir: called.append(project_dir))

    result = CliRunner().invoke(cli, ["init"], input="1\n")  # Create new project

    assert result.exit_code == 0
    assert (tmp_path / ".inreach" / ".env").exists()
    assert called == [tmp_path / ".inreach"]


def test_init_command_exits_if_project_already_exists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".inreach").mkdir()

    result = CliRunner().invoke(cli, ["init"], input="1\n")  # Create new project

    assert "already exists" in result.output.lower()
