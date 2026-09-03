from click.testing import CliRunner

from in_reach.cli import main


def test_help_prints_help_menu() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["help"])

    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "run" in result.output
    assert "cfg" in result.output


def test_run_prints_run() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["run"])

    assert result.exit_code == 0
    assert result.output.strip() == "run test"


def test_cfg_prints_placeholder_menu() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["cfg"])

    assert result.exit_code == 0
    assert "placeholder" in result.output.lower()


def test_bare_invocation_shows_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, [])

    assert "Usage:" in result.output
