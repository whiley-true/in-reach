"""The ``in-reach`` command line.

Everything the IDE does that has a command-line meaning is here, built on :mod:`in_reach.api`. Commands that read a
project take its folder (the one with ``settings/`` and ``script/``), defaulting to the current directory. Every command
that reports something takes ``--format text|json``; the JSON carries ``"schema": 1`` (see ``api.SCHEMA_VERSION``).

Exit codes: 0 ok; 1 the project has errors (or a command's own refusal); 2 the environment can't do it (no native module,
no IDE installed).
"""

from __future__ import annotations

import functools
import importlib
import json
import sys
from pathlib import Path

import click

from in_reach import api
from in_reach.app import project as project_module

_FOLDER = click.Path(exists=True, file_okay=False, path_type=Path)


def _format_option(func):
    @click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text", show_default=True, help="Output format.")
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


def _folder_argument(func):
    return click.argument("folder", type=_FOLDER, default=".")(func)


def _emit_json(data: dict) -> None:
    click.echo(json.dumps(data, indent=2))


def _fail(error: api.ApiError, fmt: str) -> None:
    if fmt == "json":
        _emit_json({"schema": api.SCHEMA_VERSION, "ok": False, "failure": str(error)})
        raise click.exceptions.Exit(error.exit_code)
    click.echo(f"error: {error}", err=True)
    raise click.exceptions.Exit(error.exit_code)


def _print_diagnostics(diagnostics) -> None:
    for diagnostic in diagnostics:
        click.echo(str(diagnostic), err=diagnostic.severity == "error")


def _summary(diagnostics) -> str:
    errors = sum(1 for d in diagnostics if d.severity == "error")
    warnings = sum(1 for d in diagnostics if d.severity == "warning")
    return f"{errors} error{'s' if errors != 1 else ''}, {warnings} warning{'s' if warnings != 1 else ''}"


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
def cfg() -> None:
    """Open the (placeholder) configuration menu."""
    click.echo("in-reach cfg -- placeholder menu, coming soon")


@main.command()
def run() -> None:
    """Open the in-reach IDE (needs the in-reach-ide package)."""
    try:
        ide = importlib.import_module("in_reach_ide.cli")
    except ImportError:
        click.echo("error: the IDE isn't installed. Install it with: pip install in-reach-ide", err=True)
        raise click.exceptions.Exit(api.EXIT_ENVIRONMENT) from None
    ide.launch()


# -- script projects -----------------------------------------------------------------------------------------


@main.command(name="check")
@_folder_argument
@_format_option
def check_cmd(folder: Path, fmt: str) -> None:
    """Check the script (a script project, or script/output.mgl) for problems, writing nothing. Exits 1 if anything is an
    error."""
    try:
        result = api.check(folder)
    except api.ApiError as exc:
        _fail(exc, fmt)
    if fmt == "json":
        _emit_json(result.to_dict())
    else:
        _print_diagnostics(result.diagnostics)
        click.echo(_summary(result.diagnostics))
    if not result.ok:
        raise click.exceptions.Exit(api.EXIT_PROJECT)


main.add_command(check_cmd, name="lint")  # the name this command had first


@main.command(name="docs")
@_folder_argument
@click.option("--no-write", is_flag=True, help="Print the overview, but don't write build/docs/.")
@_format_option
def docs_cmd(folder: Path, no_write: bool, fmt: str) -> None:
    """Generate the script's documentation: build/docs/overview.md and overview.json.

    Made from the script itself: -- @doc notes, -- @tags, script/README.md (and, in a script project, blocks/<name>.md
    and each module's README.md), and what the linker decided (slots, resources, budget, fusion)."""
    try:
        result = api.docs(folder, write=not no_write)
    except api.ApiError as exc:
        _fail(exc, fmt)
    if fmt == "json":
        _emit_json(result.to_dict())
    else:
        click.echo(result.markdown, nl=False)
        for path in result.written:
            click.echo(f"wrote    {path}", err=True)


@main.command(name="link")
@_folder_argument
@click.option("--dry-run", is_flag=True, help="Check and report, but write nothing.")
@_format_option
def link_cmd(folder: Path, dry_run: bool, fmt: str) -> None:
    """Link the script: write its link map, and build/Compiled.txt for a script project (no compile).

    Adds any trait sets, options and widgets the script declares to settings/script_settings.json."""
    try:
        result = api.link(folder, write=not dry_run)
    except api.ApiError as exc:
        _fail(exc, fmt)
    if fmt == "json":
        _emit_json(result.to_dict())
    else:
        _print_diagnostics(result.diagnostics)
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
                click.echo(f"wrote    {path}")
    if not result.ok:
        raise click.exceptions.Exit(api.EXIT_PROJECT)


@main.command(name="build")
@_folder_argument
@click.option("--env", default=None, help="Build with this env (for this build only).")
@click.option("--dry-run", is_flag=True, help="Compile and report everything, but save nothing.")
@_format_option
def build_cmd(folder: Path, env: str | None, dry_run: bool, fmt: str) -> None:
    """Build the project's gametype .bin (build/dist/<name>.bin). Exits 1 if it doesn't build, 2 without the native module."""
    try:
        outcome = api.build(folder, env=env, dry_run=dry_run)
    except api.ApiError as exc:
        _fail(exc, fmt)
    if fmt == "json":
        _emit_json(outcome.to_dict())
    else:
        _print_diagnostics(outcome.diagnostics)
        if outcome.failure:
            click.echo(outcome.failure, err=True)
        if outcome.success:
            click.echo(f"built {outcome.output_path}" if outcome.output_path else "dry run: nothing saved")
        click.echo(_summary(outcome.diagnostics))
    if not outcome.success:
        raise click.exceptions.Exit(api.EXIT_PROJECT)


@main.command(name="show")
@_folder_argument
@click.option("--view", type=click.Choice(list(api.VIEWS)), required=True, help="rvt: the built .bin decompiled; rvt+: the script with the env applied; megalo: the source as written.")
@_format_option
def show_cmd(folder: Path, view: str, fmt: str) -> None:
    """Print the project's script as RVT shows it, with the env applied, or as written."""
    try:
        result = api.show(folder, view)
    except api.ApiError as exc:
        _fail(exc, fmt)
    if fmt == "json":
        _emit_json(result.to_dict())
    else:
        click.echo(result.text, nl=not result.text.endswith("\n"))


@main.command(name="create-project")
@_folder_argument
@click.option("--backup", is_flag=True, help="Copy script/ to .in-reach/backups/ first.")
@_format_option
def create_project_cmd(folder: Path, backup: bool, fmt: str) -> None:
    """Convert a single-file script into a script project (script/project.toml + blocks/main.mgl).

    Experimental, and one-way: from then on script/output.mgl is no longer compiled. --backup keeps a copy first."""
    backup_path = None
    try:
        if backup:
            backup_path = api.backup_script(folder)
        written = api.create_script_project(folder)
    except api.ApiError as exc:
        _fail(exc, fmt)
    if fmt == "json":
        _emit_json({"schema": api.SCHEMA_VERSION, "ok": True, "written": written, "backup": str(backup_path) if backup_path else None})
    else:
        if backup_path is not None:
            click.echo(f"backup   {backup_path}")
        for path in written:
            click.echo(f"wrote    {path}")


@main.command(name="new-module")
@click.argument("name")
@_folder_argument
@_format_option
def new_module_cmd(name: str, folder: Path, fmt: str) -> None:
    """Add a module NAME to a script project."""
    try:
        written = api.new_script_module(folder, name)
    except api.ApiError as exc:
        _fail(exc, fmt)
    if fmt == "json":
        _emit_json({"schema": api.SCHEMA_VERSION, "ok": True, "written": written})
    else:
        for path in written:
            click.echo(f"wrote    {path}")


@main.group(name="env")
def env_group() -> None:
    """List, choose, add and remove envs (script/env/<name>.env: FLAGS for -- @if blocks, NAME=value for ${NAME})."""


def _print_envs(info: api.EnvInfo) -> None:
    for details in info.details:
        mark = "*" if details.name == info.active else " "
        if details.error:
            click.echo(f"{mark} {details.name}  (invalid: {details.error})")
            continue
        flags = ",".join(details.flags) or "-"
        constants = " ".join(f"{k}={v}" for k, v in details.constants.items())
        click.echo(f"{mark} {details.name}  flags={flags}" + (f"  {constants}" if constants else ""))
    if not info.names:
        click.echo("no envs")


@env_group.command(name="list")
@_folder_argument
@_format_option
def env_list(folder: Path, fmt: str) -> None:
    """List the project's envs with their flags and constants; the active one is marked."""
    info = api.envs(folder)
    if fmt == "json":
        _emit_json(info.to_dict())
    else:
        _print_envs(info)


@env_group.command(name="new")
@click.argument("name")
@click.option("--copy-from", default=None, help="Start as a copy of this env.")
@click.option("--folder", type=_FOLDER, default=".", help="The project folder.")
@_format_option
def env_new(name: str, copy_from: str | None, folder: Path, fmt: str) -> None:
    """Add env NAME (empty, or a copy of --copy-from). It isn't made active."""
    try:
        info = api.new_env(folder, name, copy_from=copy_from)
    except api.ApiError as exc:
        _fail(exc, fmt)
    if fmt == "json":
        _emit_json(info.to_dict())
    else:
        click.echo(f"added    script/env/{name}.env")


@env_group.command(name="delete")
@click.argument("name")
@click.option("--folder", type=_FOLDER, default=".", help="The project folder.")
@_format_option
def env_delete(name: str, folder: Path, fmt: str) -> None:
    """Remove env NAME (deleting the active env leaves none active)."""
    try:
        info = api.delete_env(folder, name)
    except api.ApiError as exc:
        _fail(exc, fmt)
    if fmt == "json":
        _emit_json(info.to_dict())
    else:
        click.echo(f"removed  script/env/{name}.env")


@env_group.command(name="set")
@click.argument("name", required=False)
@click.option("--none", "clear", is_flag=True, help="Build with no env.")
@click.option("--folder", type=_FOLDER, default=".", help="The project folder.")
@_format_option
def env_set(name: str | None, clear: bool, folder: Path, fmt: str) -> None:
    """Choose the env NAME to build with (or --none)."""
    if (name is None) == (not clear):
        raise click.UsageError("give an env NAME, or --none")
    if name is not None and name not in api.envs(folder).names:
        _fail(api.ApiError(f"there is no env named {name!r}"), fmt)
    try:
        info = api.set_env(folder, None if clear else name)
    except api.ApiError as exc:
        _fail(exc, fmt)
    if fmt == "json":
        _emit_json(info.to_dict())
    else:
        click.echo(f"active env: {info.active or 'none'}")


@main.group(name="module")
def module_group() -> None:
    """Add, pin, verify and update shared modules (vendored into script/modules/, pinned in script/project.lock)."""


@module_group.command(name="add")
@click.argument("source")
@click.option("--name", default=None, help="Call the module this instead of its own name.")
@click.option("--rev", default=None, help="For a git source: the branch, tag or commit.")
@click.option("--folder", type=_FOLDER, default=".", help="The project folder.")
@_format_option
def module_add(source: str, name: str | None, rev: str | None, folder: Path, fmt: str) -> None:
    """Add the module at SOURCE: a folder, or git+URL[@rev][#subdir=path]."""
    try:
        change = api.add_module(folder, source, name=name, rev=rev)
    except api.ApiError as exc:
        _fail(exc, fmt)
    _print_module_change(change, "added", fmt)


@module_group.command(name="update")
@click.argument("name")
@click.option("--rev", default=None, help="For a git source: the branch, tag or commit (default: its current head).")
@click.option("--folder", type=_FOLDER, default=".", help="The project folder.")
@_format_option
def module_update(name: str, rev: str | None, folder: Path, fmt: str) -> None:
    """Fetch NAME's source again and replace its vendored files (local edits are lost)."""
    try:
        change = api.update_module(folder, name, rev=rev)
    except api.ApiError as exc:
        _fail(exc, fmt)
    _print_module_change(change, "updated", fmt)


def _print_module_change(change, verb: str, fmt: str) -> None:
    if fmt == "json":
        _emit_json(change.to_dict())
        return
    click.echo(f"{verb} {change.name} {change.version} from {change.source}")
    for warning in change.warnings:
        click.echo(f"warning: {warning}", err=True)


@module_group.command(name="lock")
@_folder_argument
@_format_option
def module_lock(folder: Path, fmt: str) -> None:
    """Pin every module that has a source as its files are now."""
    try:
        entries = api.lock_modules(folder)
    except api.ApiError as exc:
        _fail(exc, fmt)
    if fmt == "json":
        _emit_json({"schema": api.SCHEMA_VERSION, "ok": True, "locked": entries})
    else:
        for entry in entries:
            click.echo(f"locked {entry['name']} {entry['version']}  {entry['sha256'][:12]}")
        if not entries:
            click.echo("no module has a source: nothing to lock")


@module_group.command(name="verify")
@_folder_argument
@_format_option
def module_verify(folder: Path, fmt: str) -> None:
    """Check every shared module still matches script/project.lock. Exits 1 on a mismatch."""
    try:
        result = api.verify_modules(folder)
    except api.ApiError as exc:
        _fail(exc, fmt)
    if fmt == "json":
        _emit_json(result.to_dict())
    else:
        _print_diagnostics(result.diagnostics)
        click.echo("all modules match their pins" if result.ok and not result.diagnostics else _summary(result.diagnostics))
    if not result.ok:
        raise click.exceptions.Exit(api.EXIT_PROJECT)


@module_group.command(name="enable")
@click.argument("name")
@click.option("--folder", type=_FOLDER, default=".", help="The project folder.")
@_format_option
def module_enable(name: str, folder: Path, fmt: str) -> None:
    """Build module NAME (the default for a listed module)."""
    _set_enabled(name, folder, True, fmt)


@module_group.command(name="disable")
@click.argument("name")
@click.option("--folder", type=_FOLDER, default=".", help="The project folder.")
@_format_option
def module_disable(name: str, folder: Path, fmt: str) -> None:
    """Stop building module NAME without removing it from the project."""
    _set_enabled(name, folder, False, fmt)


def _set_enabled(name: str, folder: Path, enabled: bool, fmt: str) -> None:
    try:
        api.set_module_enabled(folder, name, enabled)
    except api.ApiError as exc:
        _fail(exc, fmt)
    if fmt == "json":
        _emit_json({"schema": api.SCHEMA_VERSION, "ok": True, "module": name, "enabled": enabled})
    else:
        click.echo(f"{name}: {'enabled' if enabled else 'disabled'}")


@main.command(name="block-order")
@click.argument("blocks", nargs=-1, required=True)
@click.option("--folder", type=_FOLDER, default=".", help="The project folder.")
@_format_option
def block_order(blocks: tuple[str, ...], folder: Path, fmt: str) -> None:
    """Build the blocks in this order (project.toml's [blocks].order)."""
    try:
        api.set_block_order(folder, list(blocks))
    except api.ApiError as exc:
        _fail(exc, fmt)
    if fmt == "json":
        _emit_json({"schema": api.SCHEMA_VERSION, "ok": True, "order": list(blocks)})
    else:
        click.echo("order: " + " -> ".join(blocks))


@main.command(name="move-fragment")
@click.argument("fragment")
@click.argument("block")
@click.option("--folder", type=_FOLDER, default=".", help="The project folder.")
@_format_option
def move_fragment_cmd(fragment: str, block: str, folder: Path, fmt: str) -> None:
    """Move FRAGMENT (module.name) into BLOCK by rewriting its -- @fragment line."""
    try:
        changed = api.move_fragment(folder, fragment, block)
    except api.ApiError as exc:
        _fail(exc, fmt)
    if fmt == "json":
        _emit_json({"schema": api.SCHEMA_VERSION, "ok": True, "changed": changed})
    else:
        click.echo(f"moved {fragment} to {block} ({changed})")


# -- projects, export, launch ---------------------------------------------------------------------------------


@main.command(name="new")
@click.argument("title")
@click.option("--from", "source", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None, help="Start from this game variant (.bin).")
@click.option("--description", default="", help="The project's description.")
@click.option("--root", type=click.Path(file_okay=False, path_type=Path), default=".", help="Where the .in-reach folder is (or goes).")
@click.option("--no-build", is_flag=True, help="Don't build the new project once straight away.")
@_format_option
def new_cmd(title: str, source: Path | None, description: str, root: Path, no_build: bool, fmt: str) -> None:
    """Create a new gametype project called TITLE, and build it once (so it has a .bin and a decompiled view)."""
    try:
        folder = api.new_gametype_project(root, title, source_variant=source, description=description, build=not no_build)
    except api.ApiError as exc:
        _fail(exc, fmt)
    from in_reach.app import new_project

    built = new_project.compiled_variant_path(folder).is_file()
    if fmt == "json":
        _emit_json({"schema": api.SCHEMA_VERSION, "ok": True, "folder": str(folder), "built": built})
    else:
        click.echo(str(folder))
        if not no_build and not built:
            click.echo("warning: the first build failed -- run `in-reach build` to see why", err=True)


@main.command(name="export")
@_folder_argument
@click.option("--out", "out", type=click.Path(path_type=Path), required=True, help="A .bin path, or a folder to put <name>.bin in.")
@_format_option
def export_cmd(folder: Path, out: Path, fmt: str) -> None:
    """Build the project and copy the resulting .bin to --out."""
    try:
        outcome = api.export(folder, out)
    except api.ApiError as exc:
        _fail(exc, fmt)
    if fmt == "json":
        _emit_json(outcome.to_dict())
    else:
        _print_diagnostics(outcome.diagnostics)
        click.echo(f"exported {outcome.output_path}" if outcome.success else (outcome.failure or "the build failed"))
    if not outcome.success:
        raise click.exceptions.Exit(api.EXIT_PROJECT)


@main.command(name="verify")
@click.option("--root", type=click.Path(file_okay=False, path_type=Path), default=".", help="Where the .in-reach folder is.")
@_format_option
def verify_cmd(root: Path, fmt: str) -> None:
    """Recheck the workspace's .in-reach/.env and report which install locations are verified."""
    from within_reach import system_verify

    project_dir = api.prepare_workspace(root.resolve())
    keys = system_verify.verified_keys(project_dir)
    if fmt == "json":
        _emit_json({"schema": api.SCHEMA_VERSION, "ok": True, "project_dir": str(project_dir), "verified": keys})
    else:
        click.echo(f"workspace {project_dir}")
        for key, verified in sorted(keys.items()):
            click.echo(f"{'ok ' if verified else '-- '} {key}")


@main.group(name="launch")
def launch_group() -> None:
    """Launch ReachVariantTool or Halo: MCC."""


@launch_group.command(name="rvt")
@click.argument("folder", type=_FOLDER, required=False)
def launch_rvt_cmd(folder: Path | None) -> None:
    """Open ReachVariantTool, on FOLDER's built .bin if given (build first)."""
    from in_reach.app import new_project, rvt_launcher

    target = None
    if folder is not None:
        target = new_project.compiled_variant_path(folder)
        if not target.is_file():
            raise click.ClickException("nothing has been built yet: run `in-reach build` first")
    rvt_launcher.launch_rvt(target)


@launch_group.command(name="mcc")
def launch_mcc_cmd() -> None:
    """Launch Halo: MCC through Steam."""
    from in_reach.app import mcc_launcher

    mcc_launcher.launch_mcc()


# -- history (the shadow VCS) ---------------------------------------------------------------------------------


@main.group(name="vcs")
def vcs_group() -> None:
    """A project's own version history (kept in .in-reach/history, separate from your git)."""


def _vcs(folder: Path):
    from in_reach.app import vcs

    if not vcs.is_initialized(folder):
        vcs.init(folder)
    return vcs


@vcs_group.command(name="status")
@_folder_argument
@_format_option
def vcs_status(folder: Path, fmt: str) -> None:
    """The branch and every file that differs from the last commit."""
    vcs = _vcs(folder)
    changes = vcs.uncommitted_changes(folder)
    branch = vcs.current_branch(folder)
    if fmt == "json":
        _emit_json({
            "schema": api.SCHEMA_VERSION, "branch": branch,
            "changes": [{"path": c.path, "change": c.change_type, "staged": c.staged} for c in changes],
        })
    else:
        click.echo(f"branch {branch}")
        for change in changes:
            click.echo(f"{'S' if change.staged else ' '} {change.change_type:<9} {change.path}")
        if not changes:
            click.echo("nothing to commit")


@vcs_group.command(name="log")
@_folder_argument
@_format_option
def vcs_log(folder: Path, fmt: str) -> None:
    """The current branch's history, newest first."""
    vcs = _vcs(folder)
    snapshots = vcs.history(folder)
    if fmt == "json":
        _emit_json({
            "schema": api.SCHEMA_VERSION,
            "commits": [{"sha": s.sha, "message": s.message, "at": s.at, "stamp": s.stamp_message, "version": s.version} for s in snapshots],
        })
    else:
        for snapshot in snapshots:
            tag = f"  [v{snapshot.version}]" if snapshot.version else ""
            click.echo(f"{snapshot.sha[:8]}  {snapshot.stamp_message or snapshot.message}{tag}")


@vcs_group.command(name="commit")
@click.option("-m", "--message", required=True)
@click.option("--all", "stage_all", is_flag=True, help="Stage every change first.")
@_folder_argument
def vcs_commit(message: str, stage_all: bool, folder: Path) -> None:
    """Commit the staged changes."""
    vcs = _vcs(folder)
    try:
        if stage_all:
            vcs.stage_all(folder)
        click.echo(vcs.commit(folder, message)[:8])
    except ValueError as exc:
        raise click.ClickException(str(exc)) from None


@vcs_group.command(name="stamp")
@click.option("-m", "--message", required=True)
@click.option("--version", "version", required=True, help="major.minor.patch")
@_folder_argument
def vcs_stamp(message: str, version: str, folder: Path) -> None:
    """Stamp a versioned release of the project as it is now."""
    vcs = _vcs(folder)
    try:
        click.echo(vcs.stamp(folder, message, version=version)[:8])
    except ValueError as exc:
        raise click.ClickException(str(exc)) from None


@vcs_group.command(name="branches")
@_folder_argument
@_format_option
def vcs_branches(folder: Path, fmt: str) -> None:
    """List branches; the current one is marked."""
    vcs = _vcs(folder)
    current = vcs.current_branch(folder)
    names = vcs.list_branches(folder)
    if fmt == "json":
        _emit_json({"schema": api.SCHEMA_VERSION, "current": current, "branches": names})
    else:
        for name in names:
            click.echo(f"{'*' if name == current else ' '} {name}")


def _vcs_branch_command(name: str, help_text: str, action):
    @vcs_group.command(name=name, help=help_text)
    @click.argument("branch")
    @_folder_argument
    def command(branch: str, folder: Path) -> None:
        vcs = _vcs(folder)
        try:
            action(vcs, folder, branch)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from None
        click.echo("ok")

    return command


_vcs_branch_command("switch", "Switch to BRANCH.", lambda vcs, folder, branch: vcs.switch_branch(folder, branch))
_vcs_branch_command("delete", "Delete BRANCH.", lambda vcs, folder, branch: vcs.delete_branch(folder, branch))
_vcs_branch_command("merge", "Merge BRANCH into the current branch.", lambda vcs, folder, branch: vcs.merge_branch(folder, branch))


@vcs_group.command(name="branch")
@click.argument("name")
@click.option("--from", "source", default=None, help="Branch (or stamp) to start from; the current one by default.")
@_folder_argument
def vcs_branch(name: str, source: str | None, folder: Path) -> None:
    """Create a branch NAME."""
    vcs = _vcs(folder)
    try:
        click.echo(vcs.create_branch(folder, name, source=source))
    except ValueError as exc:
        raise click.ClickException(str(exc)) from None


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv[1:])
