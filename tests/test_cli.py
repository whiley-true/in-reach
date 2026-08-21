import logging

from click.testing import CliRunner

from inreach.cli import cli, main


def test_verify_command_logs_starting_verification(caplog):
    with caplog.at_level(logging.INFO, logger="inreach"):
        main(["verify"])
    assert "Starting verification" in caplog.text


def test_no_command_prints_help():
    result = CliRunner().invoke(cli, [])
    assert "usage" in result.output.lower()


def test_init_command_creates_project_and_exits_menu(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["init"], input="2\n")  # Exit, skip setup

    assert result.exit_code == 0
    assert (tmp_path / ".inreach" / ".env").exists()


def test_init_command_exits_if_project_already_exists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".inreach").mkdir()

    result = CliRunner().invoke(cli, ["init"])

    assert "already exists" in result.output.lower()
