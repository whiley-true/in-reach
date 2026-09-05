import sys

import click

from in_reach.app import project, verify


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
    """Open the in-reach IDE, fullscreen."""
    # macOS support is dropped -- the IDE (frameless-window resize/maximize handling in
    # in_reach.ide.main_window) relies on Windows-specific behavior, so refuse to launch anywhere
    # else rather than opening into a broken window.
    if sys.platform != "win32":
        raise click.ClickException("in-reach's IDE is Windows-only.")

    project_dir = project.get_project_dir()
    if not project.project_exists():
        project.create_project()
    project.ensure_gitignore(project_dir)
    verify.verify_project(project_dir)

    from in_reach.ide import app as ide_app

    ide_app.run(project_dir)


@main.command()
def cfg() -> None:
    """Open the (placeholder) configuration menu."""
    click.echo("in-reach cfg -- placeholder menu, coming soon")
