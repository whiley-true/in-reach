import click


@click.group()
@click.version_option(package_name="in-reach")
def main() -> None:
    """in-reach command line interface."""


@main.command(name="help")
@click.pass_context
def help_cmd(ctx: click.Context) -> None:
    """Print the help menu."""
    click.echo(ctx.parent.get_help())


@main.command()
def run() -> None:
    """Run in-reach."""
    click.echo("run test")


@main.command()
def cfg() -> None:
    """Open the (placeholder) configuration menu."""
    click.echo("in-reach cfg -- placeholder menu, coming soon")
