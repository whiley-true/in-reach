"""Command-line interface for inreach.

Wired up in pyproject.toml as:

    [project.scripts]
    inreach = "inreach.cli:main"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from inreach import __version__
from inreach.app import project
from inreach.logging_config import setup_logging

# from inreach.app import verify
# from inreach.app.setup import run_init_menu

TITLE_MAX_LEN = 32
DESCRIPTION_MAX_LEN = 127


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def _start_logging(args: argparse.Namespace) -> None:
    """Starts logging using the verbosity/stream options from parsed args.

    Args:
        args: Parsed CLI arguments. ``args.verbose`` and
            ``args.log_stream`` are read if present (both are
            ``argparse.SUPPRESS``-defaulted global options), falling back
            to ``0`` and ``False`` respectively when absent.
    """
    setup_logging(
        getattr(args, "verbose", 0),
        stream=getattr(args, "log_stream", False),
    )


def _require_new_project(args: argparse.Namespace) -> bool:
    """Resolves the ``.inreach`` project folder for a folder-creating command.

    If a project already exists at the repo root, prints instructions to
    remove or load it and leaves it untouched. Otherwise creates one from
    the packaged template. Either way, logging is only started once the
    folder's final state is known, so it can log to the right place.

    Args:
        args: Parsed CLI arguments for the calling subcommand. Only the
            logging-related global options are consulted.

    Returns:
        ``True`` if a new project was created and the caller should
        proceed, ``False`` if one already existed and the caller should
        abort.
    """
    if project.project_exists():
        print(
            "error: a .inreach project already exists here.\n"
            "  run `inreach delete` to remove it, or `inreach load` to load it.",
            file=sys.stderr,
        )
        return False

    project.create_project()
    _start_logging(args)
    return True


def cmd_setup(args: argparse.Namespace) -> int:
    """Runs one-time local environment setup.

    Creates the ``.inreach`` project folder if one doesn't already exist
    at the repo root; if one does, aborts with instructions to delete or
    load it instead.

    Args:
        args: Parsed CLI arguments for the ``setup`` subcommand.

    Returns:
        Process exit code. ``0`` on success, ``1`` if a project already
        exists.
    """
    if not _require_new_project(args):
        return 1
    print("running setup...")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Runs verification checks against the current configuration.

    Stub: not yet wired up to the project folder or real checks.

    Args:
        args: Parsed CLI arguments for the ``verify`` subcommand.

    Returns:
        Process exit code. Always ``0``.
    """
    _start_logging(args)
    print("running verification...")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    """Imports an existing project or script from disk.

    Creates the ``.inreach`` project folder if one doesn't already exist
    at the repo root; if one does, aborts with instructions to delete or
    load it instead.

    Args:
        args: Parsed CLI arguments for the ``import`` subcommand. Only
            ``args.path`` is consulted beyond the project-folder check.

    Returns:
        Process exit code. ``0`` on success, ``1`` if a project already
        exists or ``args.path`` does not exist.
    """
    if not _require_new_project(args):
        return 1

    if not args.path.exists():
        print(f"error: no such file or directory: {args.path}", file=sys.stderr)
        return 1
    print(f"importing from {args.path}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Initialises a new project, interactively or from flags.

    Creates the ``.inreach`` project folder if one doesn't already exist
    at the repo root; if one does, aborts with instructions to delete or
    load it instead. With no init options at all, hands off to the
    interactive wizard. Otherwise ``--title`` is required and the project
    is seeded from exactly one source: ``--use-file``, ``--use-ff``, or
    ``--use-blank`` (the default when none is given).

    Args:
        args: Parsed CLI arguments for the ``init`` subcommand.

    Returns:
        Process exit code. ``0`` on success, ``1`` if a project already
        exists or ``--use-file`` was given but does not exist, ``2`` if
        ``--title`` is missing while other init options were given, or if
        ``--title``/``--description`` exceed :data:`TITLE_MAX_LEN`/
        :data:`DESCRIPTION_MAX_LEN`.
    """
    # Validate flags before touching the project folder, so a rejected
    # `--title`/`--description` doesn't leave a half-initialised .inreach
    # behind for the user to clean up.
    if not _init_is_bare(args):
        if args.title is None:
            print("error: --title is required when passing init options "
                  "(run bare `inreach init` for the wizard)", file=sys.stderr)
            return 2

        if len(args.title) > TITLE_MAX_LEN:
            print(f"error: --title must be {TITLE_MAX_LEN} characters or "
                  f"fewer (got {len(args.title)})", file=sys.stderr)
            return 2

        if args.description is not None and len(args.description) > DESCRIPTION_MAX_LEN:
            print(f"error: --description must be {DESCRIPTION_MAX_LEN} "
                  f"characters or fewer (got {len(args.description)})", file=sys.stderr)
            return 2

    if not _require_new_project(args):
        return 1

    if _init_is_bare(args):
        # no options at all -> hand off to the wizard
        # return run_init_menu()
        print("launching init wizard...")
        return 0

    # --use-blank is the fallback when no other source is given
    use_blank = args.use_blank or not (args.use_ff or args.use_file)

    print(f"initialising {args.title!r}")
    if args.description:
        print(f"  description: {args.description}")

    if args.use_file is not None:
        if not args.use_file.exists():
            print(f"error: no such file: {args.use_file}", file=sys.stderr)
            return 1
        print(f"  source: file {args.use_file}")
    elif args.use_ff:
        print("  source: forge fundamentals")
    elif use_blank:
        print("  source: blank")
    return 0


def _init_is_bare(args: argparse.Namespace) -> bool:
    """Reports whether `inreach init` was called with no init options.

    Args:
        args: Parsed CLI arguments for the ``init`` subcommand.

    Returns:
        ``True`` if none of ``--title``, ``--description``, ``--use-file``,
        ``--use-blank``, or ``--use-ff`` were given.
    """
    return (
        args.title is None
        and args.description is None
        and args.use_file is None
        and not args.use_blank
        and not args.use_ff
    )


def cmd_delete(args: argparse.Namespace) -> int:
    """Deletes the local ``.inreach`` project folder, if one exists.

    Prompts for confirmation before removing anything, since this
    permanently deletes the project's local config and logs.

    Args:
        args: Parsed CLI arguments for the ``delete`` subcommand.

    Returns:
        Process exit code. ``0`` on success (including when there was
        nothing to delete), ``1`` if the user declined to confirm.
    """
    if not project.project_exists():
        print("no .inreach project found here.")
        return 0

    project_dir = project.get_project_dir()
    answer = input(f"delete {project_dir} and all its contents? [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        print("aborted.")
        return 1

    project.delete_project()
    print(f"deleted {project_dir}")
    return 0


def cmd_load(args: argparse.Namespace) -> int:
    """Loads an existing project from the local ``.inreach`` folder.

    Stub: not yet implemented.

    Args:
        args: Parsed CLI arguments for the ``load`` subcommand.

    Returns:
        Process exit code. ``0`` on success, ``1`` if no project exists to
        load.
    """
    if not project.project_exists():
        print("error: no .inreach project found here.", file=sys.stderr)
        return 1

    _start_logging(args)
    print("loading project... (not yet implemented)")
    return 0


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Builds the top-level argparse parser and its subcommands.

    ``-v``/``--verbose`` and ``-s``/``--log-stream`` are defined on a shared
    ``global_opts`` parent so they can appear either before or after the
    subcommand (e.g. both ``inreach -v verify`` and ``inreach verify -v``
    work). They default to ``argparse.SUPPRESS`` rather than a concrete
    value so that one parsed at the top level isn't clobbered by the
    subparser's own default.

    Returns:
        A configured parser with the ``setup``, ``verify``, ``import``,
        ``init``, ``delete``, and ``load`` subcommands attached, ready to
        parse ``sys.argv``-style input.
    """
    # Shared options, available before *and* after the subcommand.
    # SUPPRESS matters: without it the subparser's default would clobber a
    # value already parsed by the top-level parser (`inreach -v verify`).
    global_opts = argparse.ArgumentParser(add_help=False)
    global_opts.add_argument(
        "-v", "--verbose",
        action="count",
        default=argparse.SUPPRESS,
        help="increase log verbosity (-v, -vv)",
    )
    global_opts.add_argument(
        "-s", "--log-stream",
        action="store_true",
        default=argparse.SUPPRESS,
        help="also stream logs to stdout, in addition to the log file",
    )

    parser = argparse.ArgumentParser(
        prog="inreach",
        description="inreach command line tools for Halo Reach scripting.",
        parents=[global_opts],
    )
    parser.add_argument(
        "-V", "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    # inreach setup
    setup = subparsers.add_parser(
        "setup",
        help="set up the local environment (without creating a project)",
        description="Set up the local environment (without creating a project).",
        parents=[global_opts],
    )
    setup.set_defaults(func=cmd_setup)

    # inreach verify
    verify = subparsers.add_parser(
        "verify",
        help="verify the current configuration",
        description="Verify the current configuration.",
        parents=[global_opts],
    )
    verify.set_defaults(func=cmd_verify)

    # inreach import PATH
    import_ = subparsers.add_parser(
        "import",
        help="import an existing project",
        description="Import an existing project.",
        parents=[global_opts],
    )
    import_.add_argument(
        "path",
        type=Path,
        help="path to import from",
    )
    import_.set_defaults(func=cmd_import)

    # inreach init [--title T] [--description D]
    #              [--use-blank | --use-ff | --use-file PATH]
    init = subparsers.add_parser(
        "init",
        help="initialise a new project (interactive if no options given)",
        description="Initialise a new project. Run with no options for the "
                    "interactive wizard.",
        parents=[global_opts],
    )
    init.add_argument(
        "--title",
        help=f"project title (max {TITLE_MAX_LEN} characters)",
    )
    init.add_argument(
        "--description",
        help=f"short project description (max {DESCRIPTION_MAX_LEN} characters)",
    )

    source = init.add_mutually_exclusive_group()
    source.add_argument(
        "--use-blank",
        action="store_true",
        help="start from a blank project (default)",
    )
    source.add_argument(
        "--use-ff",
        action="store_true",
        help="start from forge fundamentals",
    )
    source.add_argument(
        "--use-file",
        type=Path,
        metavar="PATH",
        help="start from an existing file",
    )
    init.set_defaults(func=cmd_init)

    # inreach delete
    delete = subparsers.add_parser(
        "delete",
        help="delete the local .inreach project",
        description="Delete the local .inreach project folder.",
        parents=[global_opts],
    )
    delete.set_defaults(func=cmd_delete)

    # inreach load
    load = subparsers.add_parser(
        "load",
        help="load the local .inreach project",
        description="Load the local .inreach project.",
        parents=[global_opts],
    )
    load.set_defaults(func=cmd_load)

    return parser


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Parses arguments and dispatches to a subcommand.

    Logging isn't started here: each subcommand starts it itself (via
    :func:`inreach.logging_config.setup_logging`) once it has resolved
    where the ``.inreach`` project folder actually is -- found already
    existing, or just created from the template -- so logs land in the
    right place from the first line.

    Args:
        argv: Argument list to parse in place of ``sys.argv[1:]``. Passing
            ``None`` (the default) parses the real process arguments.

    Returns:
        Process exit code returned by the dispatched subcommand, or ``0``
        if no subcommand was given (help text is printed in that case).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    # bare `inreach` -> show help
    if args.command is None:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
