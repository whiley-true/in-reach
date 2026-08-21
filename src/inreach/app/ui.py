import sys
import time
from typing import Callable

import click


def clear_screen() -> None:
    """Clear the terminal.

    ``click.clear()`` shells out to ``cls`` on Windows, which in Windows
    Terminal just scrolls the viewport (padding it with blank lines)
    rather than truly erasing it. Writing the ANSI clear sequence
    directly avoids that padding.
    """
    if not sys.stdout.isatty():
        return
    click.echo("\x1b[3J\x1b[2J\x1b[H", nl=False)


def print_header(title: str) -> None:
    clear_screen()
    click.echo()
    click.secho(title, fg="cyan", bold=True)
    click.secho("-" * len(title), fg="cyan")


def select_option(title: str, options: list[str]) -> int:
    """Display a numbered menu and return the index of the chosen option."""
    print_header(title)
    for i, option in enumerate(options, start=1):
        click.echo(f"  [{i}] {option}")

    choice = click.prompt("Select an option", type=click.IntRange(1, len(options)))
    return choice - 1


def confirm(prompt: str, default: bool = True) -> bool:
    return click.confirm(prompt, default=default)


def press_enter(prompt: str) -> None:
    """Block until the user presses Enter (or types anything then Enter)."""
    click.prompt(prompt, default="", show_default=False)


def info(message: str) -> None:
    click.echo(message)


def success(message: str) -> None:
    click.secho(message, fg="green")


def warning(message: str) -> None:
    click.secho(message, fg="yellow")


def error(message: str) -> None:
    click.secho(message, fg="red", bold=True)


def checklist(
    title: str, items: list[tuple[str, str]], check: Callable[[str], str | None], delay: float = 0.5
) -> list[str]:
    """Print each (key, label) item, ticking it off once ``check`` resolves it.

    Each item's label is shown immediately with an empty checkbox; after
    ``delay`` seconds it's ticked off (or not) in place, with the detail
    ``check`` returned appended to the same line. ``check(key)`` should
    return a truthy string describing where the item was found, or a
    falsy value if it wasn't found. Returns the keys ``check`` returned
    falsy for.
    """
    print_header(title)
    missing = []
    for key, label in items:
        click.echo(f"  [ ] {label}", nl=False)
        if delay:
            time.sleep(delay)
        detail = check(key)
        if detail:
            mark = click.style("[x]", fg="green")
            click.echo(f"\r  {mark} {label} - found at {detail}")
        else:
            mark = click.style("[ ]", fg="yellow")
            click.echo(f"\r  {mark} {label} - not found")
            missing.append(key)
    return missing
