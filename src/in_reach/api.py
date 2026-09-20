"""The programmatic face of in-reach: what the command line, the IDE and anything else call.

Every function takes a *gametype project folder* (the one with ``settings/`` and ``script/``) and returns plain
dataclasses -- never Qt objects, never raw native handles -- with a ``to_dict()`` that is the JSON the CLI prints
(``--format json``). The shape of that JSON is versioned by :data:`SCHEMA_VERSION`; a change that breaks a consumer
raises it.

::

    from in_reach import api

    result = api.check(folder)               # CheckResult: ok, diagnostics, link_map
    for d in result.diagnostics:
        print(d.file, d.line, d.severity, d.code, d.message)
    outcome = api.build(folder)              # BuildOutcome: success, diagnostics, output_path

Problems the caller can fix (not a script project, no such view, nothing built yet) raise :class:`ApiError`, which carries
the exit code the CLI uses: ``1`` for a problem with the project, ``2`` for the environment (no native module).
Nothing here needs Qt; only :func:`build`, :func:`show` of the ``rvt`` view and :func:`export` need the native module.
"""

from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from in_reach.app import new_project, output_view, script_preprocess
from in_reach.app import project as project_module
from in_reach.app.script_project import edit as _edit
from in_reach.app.script_project import packages as _packages
from in_reach.app.script_project import (
    LinkResult,
    create_module,
    create_project,
    is_linked,
    link as _link,
    load_project,
)

SCHEMA_VERSION = 1
#: Bumped when a function here changes incompatibly; ``in-reach-ide`` states the range it works with.
API_VERSION = 1

EXIT_OK = 0
EXIT_PROJECT = 1
EXIT_ENVIRONMENT = 2

VIEWS = ("rvt", "rvt+", "megalo")


class ApiError(Exception):
    """A problem the caller can act on. ``exit_code`` is what the CLI exits with."""

    def __init__(self, message: str, exit_code: int = EXIT_PROJECT) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class Diagnostic:
    severity: str  # error | warning | notice
    code: str
    message: str
    file: str = ""  # relative to the project's script/ folder ("../settings/..." for a file outside it)
    line: int = 0  # 1-based; 0 = no position
    column: int = 0  # 1-based; 0 = no position
    hint: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def __str__(self) -> str:
        where = f"{self.file}:{self.line}:{self.column}: " if self.file and self.line else (f"{self.file}: " if self.file else "")
        code = f" [{self.code}]" if self.code else ""
        hint = f" ({self.hint})" if self.hint else ""
        return f"{where}{self.severity}: {self.message}{code}{hint}"


@dataclass
class CheckResult:
    ok: bool
    diagnostics: list[Diagnostic] = field(default_factory=list)
    link_map: dict = field(default_factory=dict)
    #: The raw :class:`~in_reach.app.script_project.LinkResult`, for a caller (the IDE) that shows modules and blocks.
    link_result: LinkResult | None = field(default=None, repr=False, compare=False)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "warning"]

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA_VERSION, "ok": self.ok, "diagnostics": [d.to_dict() for d in self.diagnostics],
            "link_map": self.link_map,
        }


@dataclass
class LinkOutcome(CheckResult):
    written: list[str] = field(default_factory=list)  # relative to the project folder
    settings_changed: bool = False

    def to_dict(self) -> dict:
        return {**super().to_dict(), "written": self.written, "settings_changed": self.settings_changed}


@dataclass
class BuildOutcome:
    success: bool
    diagnostics: list[Diagnostic] = field(default_factory=list)
    failure: str | None = None
    output_path: str | None = None

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA_VERSION, "ok": self.success, "failure": self.failure, "output_path": self.output_path,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
        }


@dataclass
class ShowResult:
    view: str
    path: str | None  # the file the text was also written to, if any
    text: str

    def to_dict(self) -> dict:
        return {"schema": SCHEMA_VERSION, "view": self.view, "path": self.path, "text": self.text}


@dataclass
class ProfileInfo:
    names: list[str]
    active: str | None

    def to_dict(self) -> dict:
        return {"schema": SCHEMA_VERSION, "profiles": self.names, "active": self.active}


# -- conversions ---------------------------------------------------------------------------------------------


def _from_project_diagnostic(d) -> Diagnostic:
    return Diagnostic(d.severity, d.code, d.message, d.file, d.line, d.col + 1 if d.line else 0, d.hint)


def _from_build_message(severity: str, message) -> Diagnostic:
    return Diagnostic(severity, message.code, message.text, message.file, message.line, message.col)


def _script_project(folder: Path) -> Path:
    folder = Path(folder)
    if not is_linked(folder):
        raise ApiError(f"{folder} is not a script project (there is no script/project.toml in it).")
    return folder


def _project_dir(folder: Path) -> Path:
    """The ``.in-reach`` folder that goes with the gametype project ``folder``: a gametype project lives at ``<root>/<id>``,
    next to ``<root>/.in-reach`` (which holds its frozen base ``.bin``, the history and the workspace ``.env``)."""
    return project_module.get_project_dir(folder.parent)


# -- checking and linking ------------------------------------------------------------------------------------


def _link_outcome(folder: Path, write: bool) -> LinkOutcome:
    result = _link(folder, write=write)
    if not result.ok:
        from in_reach.app.script_project import read_link_map

        result.link_map = read_link_map(folder)  # a project that doesn't link still shows what it last built
    return LinkOutcome(
        ok=result.ok,
        diagnostics=[_from_project_diagnostic(d) for d in result.diagnostics],
        link_map=result.link_map,
        link_result=result,
        written=[p.relative_to(folder).as_posix() for p in result.written],
        settings_changed=result.settings_changed,
    )


def check(folder: Path) -> CheckResult:
    """Everything wrong with a script project (project model, lint, allocation, fusion), writing nothing."""
    outcome = _link_outcome(_script_project(folder), write=False)
    return CheckResult(outcome.ok, outcome.diagnostics, outcome.link_map, outcome.link_result)


def link(folder: Path, *, write: bool = True) -> LinkOutcome:
    """Assembles ``build/Compiled.txt`` and its link map (and any settings the project declares); no compile."""
    return _link_outcome(_script_project(folder), write)


# -- building ------------------------------------------------------------------------------------------------


def build(folder: Path, *, profile: str | None = None, dry_run: bool = False) -> BuildOutcome:
    """Builds the project's gametype ``.bin`` (``build/dist/<name>.bin``); ``dry_run`` compiles and reports everything but
    saves nothing. ``profile`` builds with that profile for this call only.

    Raises:
        ApiError: The native extension isn't available (exit code 2), or the profile doesn't exist."""
    from in_reach.app.rvt import rvt_bridge
    from in_reach.app.rvt.compile import run_compile

    folder = Path(folder)
    if not rvt_bridge.is_available():
        raise ApiError("the native _reachvarianttool module isn't available for this Python", EXIT_ENVIRONMENT)
    previous = script_preprocess.active_profile_name(folder)
    if profile is not None:
        if profile not in script_preprocess.list_profiles(folder):
            raise ApiError(f"there is no profile named {profile!r} (have: {', '.join(script_preprocess.list_profiles(folder)) or 'none'})")
        script_preprocess.set_active_profile(folder, profile)
    try:
        result = run_compile(_project_dir(folder), folder, save=not dry_run)
    finally:
        if profile is not None and previous != profile:
            script_preprocess.set_active_profile(folder, previous)
    diagnostics = [
        *(_from_build_message("error", m) for m in [*result.fatal_errors, *result.errors]),
        *(_from_build_message("warning", m) for m in result.warnings),
        *(_from_build_message("notice", m) for m in result.notices),
    ]
    return BuildOutcome(result.success, diagnostics, result.failure, str(result.output_path) if result.output_path else None)


def export(folder: Path, out: Path) -> BuildOutcome:
    """Builds ``folder`` and copies the resulting ``.bin`` to ``out`` (a file, or a folder to put ``<name>.bin`` in)."""
    outcome = build(folder)
    if outcome.success and outcome.output_path:
        target = Path(out)
        if target.is_dir():
            target = target / Path(outcome.output_path).name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(outcome.output_path, target)
        outcome.output_path = str(target)
    return outcome


# -- views of the script -------------------------------------------------------------------------------------


def show(folder: Path, view: str) -> ShowResult:
    """The project's script as one of :data:`VIEWS`:

    * ``rvt`` -- what RVT shows: the built ``.bin`` decompiled, no modules, no profile (``build/Decompiled.txt``). Needs
      a build and the native module.
    * ``rvt+`` -- the same script before it is compiled, with the profile applied: ``build/Compiled.txt``.
    * ``megalo`` -- the source as written: ``script/output.txt``, or every block and module file of a script project."""
    folder = Path(folder)
    if view not in VIEWS:
        raise ApiError(f"unknown view {view!r}; choose one of {', '.join(VIEWS)}")
    if view == "rvt+":
        path = output_view.write_output_view(folder)
        return ShowResult(view, str(path), path.read_text(encoding="utf-8"))
    if view == "rvt":
        built = new_project.compiled_variant_path(folder)
        if not built.is_file():
            raise ApiError("nothing has been built yet: run `in-reach build` first")
        try:
            path = output_view.write_decompiled_view(folder)
        except (ImportError, OSError, RuntimeError) as exc:
            raise ApiError(f"couldn't decompile {built.name}: {exc}", EXIT_ENVIRONMENT) from exc
        return ShowResult(view, str(path), path.read_text(encoding="utf-8"))
    return ShowResult(view, None, _megalo_source(folder))


def _megalo_source(folder: Path) -> str:
    if not is_linked(folder):
        try:
            return (folder / new_project.SCRIPT_DIRNAME / "output.txt").read_text(encoding="utf-8")
        except OSError:
            return ""
    parts = []
    for source in load_project(folder).files:
        parts.append(f"-- ==== {source.path} ({source.owner}) ====\n{source.text.rstrip()}\n")
    return "\n".join(parts)


# -- scaffolding and profiles --------------------------------------------------------------------------------


def create_script_project(folder: Path) -> list[str]:
    """Turns a single-script project into a script project; returns the files written (relative to ``folder``)."""
    try:
        written = create_project(Path(folder))
    except ValueError as exc:
        raise ApiError(str(exc)) from exc
    return [p.relative_to(folder).as_posix() for p in written]


def new_script_module(folder: Path, name: str) -> list[str]:
    """Adds module ``name`` to a script project; returns the files written (relative to ``folder``)."""
    try:
        written = create_module(Path(folder), name)
    except ValueError as exc:
        raise ApiError(str(exc)) from exc
    return [p.relative_to(folder).as_posix() for p in written]


def profiles(folder: Path) -> ProfileInfo:
    return ProfileInfo(script_preprocess.list_profiles(Path(folder)), script_preprocess.active_profile_name(Path(folder)))


def set_profile(folder: Path, name: str | None) -> ProfileInfo:
    """Makes ``name`` (``None``: no profile) the profile the project builds with."""
    try:
        script_preprocess.set_active_profile(Path(folder), name)
    except (ValueError, OSError) as exc:
        raise ApiError(str(exc)) from exc
    return profiles(folder)


def new_gametype_project(root: Path, title: str, *, source_variant: Path | None = None, description: str = "") -> Path:
    """Creates a gametype project at ``<root>/<id>`` (making ``<root>/.in-reach`` if it is missing); returns its folder."""
    project_dir = project_module.get_project_dir(Path(root))
    if not project_dir.is_dir():
        project_module.create_project(Path(root))
    try:
        folder, _warning = new_project.create_gametype_project(project_dir, title, description, source_variant)
    except (ValueError, OSError) as exc:
        raise ApiError(str(exc)) from exc
    return folder


def prepare_workspace(root: Path | None = None) -> Path:
    """Makes sure ``root`` (the current directory by default) has a ``.in-reach`` folder with its ``.env``, ``.gitignore``
    and README, rechecks the environment, and configures logging. Returns the ``.in-reach`` folder. What every front end
    (the CLI's ``verify``, the IDE's start-up) does before it works with projects."""
    from in_reach.app import logging_setup, verify

    project_dir = project_module.get_project_dir(root)
    if not project_module.project_exists(root):
        project_module.create_project(root)
    project_module.ensure_gitignore(project_dir)
    project_module.ensure_readme(project_dir)
    verify.verify_project(project_dir)
    logger = logging_setup.configure_logging(project_dir)
    logger.info("workspace ready (project_dir=%s)", project_dir)
    return project_dir


# -- shared modules --------------------------------------------------------------------------------------------


@dataclass
class ModuleChange:
    name: str
    version: str
    source: str
    files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"schema": SCHEMA_VERSION, "ok": True, **asdict(self)}


def add_module(folder: Path, source: str, *, name: str | None = None, rev: str | None = None, base: Path | None = None) -> ModuleChange:
    """Fetches the module at ``source`` (a folder, or ``git+<url>[@rev][#subdir=path]``), vendors it into the project,
    records its source in ``project.toml`` and pins it in ``project.lock``."""
    try:
        added = _packages.add_module(Path(folder), source, name=name, rev=rev, base=base)
    except _packages.PackageError as exc:
        raise ApiError(str(exc)) from exc
    return ModuleChange(added.name, added.version, added.source, added.files, added.warnings)


def update_module(folder: Path, name: str, *, rev: str | None = None, base: Path | None = None) -> ModuleChange:
    """Fetches ``name``'s source again and replaces the vendored files."""
    try:
        updated = _packages.update_module(Path(folder), name, rev=rev, base=base)
    except _packages.PackageError as exc:
        raise ApiError(str(exc)) from exc
    return ModuleChange(updated.name, updated.version, updated.source, updated.files, updated.warnings)


def lock_modules(folder: Path) -> list[dict]:
    """Re-pins every module that has a source; returns ``[{name, version, source, sha256}]``."""
    try:
        return [asdict(entry) for entry in _packages.lock_modules(Path(folder)).values()]
    except _packages.PackageError as exc:
        raise ApiError(str(exc)) from exc


def verify_modules(folder: Path) -> CheckResult:
    """Whether every shared module still matches ``project.lock``; a mismatch is an error diagnostic."""
    folder = _script_project(folder)
    diagnostics = [_from_project_diagnostic(d) for d in _packages.verify_modules(folder)]
    return CheckResult(not any(d.severity == "error" for d in diagnostics), diagnostics)


# -- editing the composition (what a drag-and-drop board does) ---------------------------------------------------


def _edit_call(function, *args):
    try:
        return function(*args)
    except _edit.EditError as exc:
        raise ApiError(str(exc)) from exc


def set_block_order(folder: Path, order: list[str]) -> None:
    """Sets the order the blocks are built in (``project.toml``'s ``[blocks].order``)."""
    _edit_call(_edit.set_block_order, Path(folder), order)


def set_module_enabled(folder: Path, name: str, enabled: bool) -> None:
    """Turns a module on or off without removing it from the project."""
    _edit_call(_edit.set_module_enabled, Path(folder), name, enabled)


def move_fragment(folder: Path, fragment_id: str, block: str) -> str:
    """Moves fragment ``fragment_id`` (``module.name``) to ``block``; returns the file that changed, relative to ``folder``."""
    changed = _edit_call(_edit.move_fragment, Path(folder), fragment_id, block)
    return Path(changed).relative_to(folder).as_posix()
