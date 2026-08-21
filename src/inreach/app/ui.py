import click


def print_header(title: str) -> None:
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


def success(message: str) -> None:
    click.secho(message, fg="green")


def warning(message: str) -> None:
    click.secho(message, fg="yellow")


def error(message: str) -> None:
    click.secho(message, fg="red", bold=True)
