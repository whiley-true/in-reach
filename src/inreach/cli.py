import click

from inreach.app import verify
from inreach.app.setup import run_init_menu
from inreach.logging_config import setup_logging


@click.group()
def cli() -> None:
    """inreach command-line tool."""
    setup_logging()


@cli.command(name="verify")
def verify_command() -> None:
    """Verify an existing project's install locations and Steam account."""
    verify.run_verify()


@cli.command(name="init")
def init_command() -> None:
    """Initialize the application."""
    run_init_menu()


@cli.command(name="help")
@click.pass_context
def help_command(ctx: click.Context) -> None:
    """Show this help message."""
    click.echo(ctx.parent.get_help())


def main(argv=None) -> int:
    return cli.main(args=argv, prog_name="inreach", standalone_mode=False)


if __name__ == "__main__":
    cli()
