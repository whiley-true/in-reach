import click

from inreach.app import verify
from inreach.app.setup import create_project, run_init_menu
from inreach.logging_config import setup_logging


@click.group()
def cli() -> None:
    """inreach command-line tool."""
    setup_logging()


@cli.command(name="verify")
def verify_command() -> None:
    """Run verification."""
    verify.verify_installs()


@cli.command(name="init")
def init_command() -> None:
    """Initialize the application."""
    project_dir = create_project()
    if project_dir is not None:
        run_init_menu(project_dir)


def main(argv=None) -> int:
    return cli.main(args=argv, prog_name="inreach", standalone_mode=False)


if __name__ == "__main__":
    cli()
