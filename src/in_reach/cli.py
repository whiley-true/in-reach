import sys
from pathlib import Path

import click

from in_reach.app import logging_setup, project, verify


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
    project.ensure_readme(project_dir)
    verify.verify_project(project_dir)
    # verify_project() above guarantees the LOG_* keys this reads are populated -- see
    # logging_setup's own module docstring for why every logger in the app is a child of
    # "in_reach" rather than the root logger.
    logger = logging_setup.configure_logging(project_dir)
    logger.info("in-reach run starting (project_dir=%s)", project_dir)

    from in_reach.ide import app as ide_app

    ide_app.run(project_dir)


@main.command()
def cfg() -> None:
    """Open the (placeholder) configuration menu."""
    click.echo("in-reach cfg -- placeholder menu, coming soon")


def _script_project_folder(folder: Path) -> Path:
    """``folder`` if it is a gametype project with a ``script/project.toml``; otherwise a :class:`click.ClickException`."""
    from in_reach.app.script_project import is_linked

    if not is_linked(folder):
        raise click.ClickException(f"{folder} is not a script project (there is no script/project.toml in it).")
    return folder


def _echo_diagnostics(diagnostics) -> None:
    for diagnostic in diagnostics:
        click.echo(str(diagnostic), err=diagnostic.severity == "error")


@main.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path), default=".")
def lint(folder: Path) -> None:
    """Check a script project for problems, writing nothing.

    FOLDER is the gametype project (the one with script/project.toml); the current directory by default. Exits
    non-zero if anything is an error."""
    from in_reach.app.script_project import link

    result = link(_script_project_folder(folder), write=False)
    _echo_diagnostics(result.diagnostics)
    errors = len(result.errors)
    warnings = len(result.diagnostics) - errors
    click.echo(f"{errors} error{'s' if errors != 1 else ''}, {warnings} warning{'s' if warnings != 1 else ''}")
    if errors:
        raise click.exceptions.Exit(1)


@main.command(name="link")
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path), default=".")
@click.option("--dry-run", is_flag=True, help="Check and report, but write nothing.")
def link_cmd(folder: Path, dry_run: bool) -> None:
    """Link a script project: write build/Compiled.txt and its link map (no compile).

    Adds any trait sets, options and widgets the project declares to settings/script_settings.json. FOLDER is the
    gametype project; the current directory by default. Exits non-zero if the project doesn't link."""
    from in_reach.app.script_project import link

    folder = _script_project_folder(folder)
    result = link(folder, write=not dry_run)
    _echo_diagnostics(result.diagnostics)
    if not result.ok:
        raise click.ClickException(f"{len(result.errors)} error(s); nothing was written.")
    link_map = result.link_map
    click.echo(f"blocks   {' -> '.join(link_map['order'])}")
    for group in link_map["fusion"]["groups"]:
        click.echo(f"fused    {group['trigger']} <- {' + '.join(group['fragments'])}")
    for declined in link_map["fusion"]["declined"]:
        click.echo(f"kept     {' | '.join(declined['fragments'])}: {declined['reason']}")
    budget = "  ".join(f"{name} {entry['used']}/{entry['cap']}" for name, entry in link_map["budget"].items() if "cap" in entry)
    if budget:
        click.echo(f"budget   {budget}")
    if dry_run:
        click.echo("dry run: nothing written")
    else:
        for path in result.written:
            click.echo(f"wrote    {path.relative_to(folder).as_posix()}")
