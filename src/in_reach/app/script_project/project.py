"""Loading a script project: ``script/project.toml``, its modules and its block files.

::

    script/
      project.toml                 [blocks].order, [[modules]], [constants], [kinds] ...
      blocks/setup.mgl             a hand-authored block; its name is the file stem, upper-cased (SETUP)
      modules/hill_score/
        module.toml
        hill_score.mgl             a module: any number of .mgl files
      env/dev.env                  the envs (see in_reach.app.script_preprocess)

:func:`load_project` reads all of it and reports every problem it finds -- in a manifest, in a constant, in a
file's preprocessing or annotations, in the block order -- as a located diagnostic, without stopping at the first.
It doesn't lint the code or allocate anything: that is what reads the result.

Each source file is preprocessed with the constants its owner sees (see :mod:`.constants`) *before* its
annotations are read, since an annotation may contain a placeholder (``default=${score_interval}``); the
preprocessor never moves a line, so positions in the diagnostics are positions in the file as written.

A module contributes to a block by writing ``-- @fragment BLOCK.name``; that is the only way a block
comes to exist without a file of its own, and it is how a module's blocks are known (the design's
``[provides] blocks`` is dropped).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from in_reach.app import new_project, script_preprocess
from in_reach.app.rvt.megalo_ast.annotations import (
    Annotations, BlockAnnotation, FragmentAnnotation, parse_annotations,
)

from .constants import ConstantProblem, base_constants, module_constants
from .diagnostics import ProjectDiagnostic
from .manifests import KindSpec, ModuleManifest, ProjectManifest, read_manifest
from .ordering import Edge, order_blocks
from .toml_positions import locate, positions

PROJECT_FILENAME = "project.toml"
MODULE_FILENAME = "module.toml"
SOURCE_SUFFIX = ".mgl"
BLOCKS_DIRNAME = "blocks"
MODULES_DIRNAME = "modules"

_MODULE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_BLOCK_NAME = re.compile(r"[A-Z_][A-Z0-9_]*")


@dataclass
class SourceFile:
    """One ``.mgl`` file. ``owner`` is ``"block:SETUP"`` or ``"module:hill_score"``; ``processed`` is ``text``
    with constants substituted and ``-- @if`` blocks resolved, and is ``None`` if that failed."""

    path: str
    owner: str
    text: str
    processed: str | None
    annotations: Annotations


@dataclass
class LoadedModule:
    name: str
    manifest: ModuleManifest
    constants: dict[str, str]
    files: list[SourceFile] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)  # the blocks it contributes fragments to, first-seen order


@dataclass
class LoadedBlock:
    name: str
    file: SourceFile | None = None  # None: it exists only because fragments name it
    contributors: list[str] = field(default_factory=list)  # modules with a fragment in it


@dataclass
class MergedKind:
    """A kind of object (``TO_IMPLEMENT`` §4.2), as the project and its modules together define it."""

    reached_by: list[str]
    defined_by: list[str]  # "project.toml" and/or "module <name>"


@dataclass
class ScriptProject:
    folder: Path
    manifest: ProjectManifest | None = None
    env: script_preprocess.Env | None = None
    constants: dict[str, str] = field(default_factory=dict)
    modules: list[LoadedModule] = field(default_factory=list)
    disabled_modules: list[str] = field(default_factory=list)  # listed with enabled = false: kept, not built
    blocks: dict[str, LoadedBlock] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    kinds: dict[str, MergedKind] = field(default_factory=dict)
    diagnostics: list[ProjectDiagnostic] = field(default_factory=list)

    @property
    def files(self) -> list[SourceFile]:
        found = [block.file for block in self.blocks.values() if block.file is not None]
        return found + [file for module in self.modules for file in module.files]

    @property
    def errors(self) -> list[ProjectDiagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors


def script_dir(folder: Path) -> Path:
    return folder / new_project.SCRIPT_DIRNAME


def is_linked(folder: Path) -> bool:
    """Whether ``folder`` is a *linked* project: it has a ``script/project.toml``, so its script is built from
    blocks and modules rather than being the single hand-edited ``script/output.mgl``."""
    return (script_dir(folder) / PROJECT_FILENAME).is_file()


class _Loader:
    def __init__(self, folder: Path, overrides: dict[str, str] | None = None) -> None:
        self.folder = folder
        self.scripts = script_dir(folder)
        self.project = ScriptProject(folder=folder)
        self.overrides = overrides or {}  # path relative to script/ -> text standing in for the file (an unsaved buffer)

    # -- reporting ------------------------------------------------------------------------------------

    def report(self, severity: str, code: str, message: str, file: str, line: int = 0, col: int = 0) -> None:
        self.project.diagnostics.append(
            ProjectDiagnostic(severity=severity, code=code, message=message, file=file, line=line, col=col)
        )

    def error(self, code: str, message: str, file: str, line: int = 0, col: int = 0) -> None:
        self.report("error", code, message, file, line, col)

    def warn(self, code: str, message: str, file: str, line: int = 0, col: int = 0) -> None:
        self.report("warning", code, message, file, line, col)

    def raw(self, relative: str) -> str:
        """``relative``'s text, or the override standing in for it. Raises ``OSError``/``UnicodeDecodeError``."""
        if relative in self.overrides:
            return self.overrides[relative]
        return (self.scripts / relative).read_text(encoding="utf-8")

    def read(self, relative: str) -> str | None:
        try:
            return self.raw(relative)
        except FileNotFoundError:
            self.error("file-missing", f"{relative} doesn't exist", relative)
        except (OSError, UnicodeDecodeError) as exc:
            self.error("file-unreadable", f"can't read {relative}: {exc}", relative)
        return None

    def manifest_diagnostics(self, diagnostics: list[ProjectDiagnostic]) -> None:
        self.project.diagnostics.extend(diagnostics)

    # -- the pieces -----------------------------------------------------------------------------------

    def load(self) -> ScriptProject:
        text = self.read(PROJECT_FILENAME)
        if text is None:
            return self.project
        manifest, diagnostics = read_manifest(text, ProjectManifest, PROJECT_FILENAME)
        self.manifest_diagnostics(diagnostics)
        if manifest is None:
            return self.project
        self.project.manifest = manifest
        where = positions(text)

        self._load_env_and_constants(manifest, where)
        self._load_modules(manifest, where)
        self._load_blocks()
        self._collect_blocks(manifest, where)
        self._order(manifest, where)
        self._merge_kinds(manifest, where)
        self._check_pins()
        return self.project

    def _check_pins(self) -> None:
        """Warns when a shared module's vendored files no longer match ``project.lock`` (editing them is legitimate, so
        this is never an error here; ``in-reach module verify`` is the strict check)."""
        from . import packages

        if (self.scripts / packages.LOCK_FILENAME).is_file():
            self.project.diagnostics += packages.verify_modules(self.folder, severity="warning")

    def _load_env_and_constants(self, manifest: ProjectManifest, where: dict) -> None:
        if manifest.project.profile is not None:
            line, col = locate(where, ("project", "profile"))
            self.warn("env-key-renamed", "[project] profile is now called env: rename the key", PROJECT_FILENAME, line, col)
        name = script_preprocess.active_env_name(self.folder) or manifest.project.env or manifest.project.profile
        env = None
        if name:
            try:
                env = script_preprocess.load_env(self.folder, name)
            except script_preprocess.PreprocessError as exc:
                file = f"{script_preprocess.ENV_DIRNAME}/{name}{script_preprocess.ENV_SUFFIX}"
                self.error("env-invalid", exc.message, file, exc.line, exc.col)
        self.project.env = env

        constants, problems = base_constants(manifest.constants, env)
        self.project.constants = constants
        for problem in problems:
            line, col = locate(where, ("constants", problem.name))
            self.error(problem.code, problem.message, PROJECT_FILENAME, line, col)

    def _process(self, relative: str, owner: str, text: str, constants: dict[str, str]) -> SourceFile:
        flags = self.project.env.flags if self.project.env else frozenset()
        try:
            processed: str | None = script_preprocess.preprocess(text, script_preprocess.Env("", flags, constants))
        except script_preprocess.PreprocessError as exc:
            self.error("preprocess", exc.message, relative, exc.line, exc.col)
            processed = None
        annotations = parse_annotations(processed) if processed is not None else Annotations()
        for diagnostic in annotations.diagnostics:
            self.error("annotation", diagnostic.message, relative, diagnostic.span.start_line, diagnostic.span.start_col)
        return SourceFile(path=relative, owner=owner, text=text, processed=processed, annotations=annotations)

    def _load_modules(self, manifest: ProjectManifest, where: dict) -> None:
        modules_dir = self.scripts / MODULES_DIRNAME
        listed: set[str] = set()
        for index, ref in enumerate(manifest.modules):
            line, col = locate(where, ("modules", index, "name"))
            if not _MODULE_NAME.fullmatch(ref.name):
                self.error("module-name", f"{ref.name!r} isn't a valid module name", PROJECT_FILENAME, line, col)
                continue
            if ref.name in listed:
                self.error("module-duplicate", f"module {ref.name} is listed twice", PROJECT_FILENAME, line, col)
                continue
            listed.add(ref.name)
            if not ref.enabled:
                self.project.disabled_modules.append(ref.name)
                continue  # switched off: it stays in the project, but nothing of it is built
            self._load_module(index, ref.name, ref.params, where)

        if modules_dir.is_dir():
            for path in sorted(modules_dir.iterdir()):
                if path.is_dir() and (path / MODULE_FILENAME).is_file() and path.name not in listed:
                    self.warn(
                        "module-unlisted",
                        f"module {path.name} isn't listed in project.toml, so it isn't built",
                        f"{MODULES_DIRNAME}/{path.name}/{MODULE_FILENAME}",
                    )

    def _load_module(self, index: int, name: str, given: dict, project_where: dict) -> None:
        base = f"{MODULES_DIRNAME}/{name}"
        manifest_file = f"{base}/{MODULE_FILENAME}"
        list_line, list_col = locate(project_where, ("modules", index, "name"))
        if not (self.scripts / base).is_dir():
            self.error("module-missing", f"module {name} has no folder script/{base}", PROJECT_FILENAME, list_line, list_col)
            return
        text = self.read(manifest_file)
        if text is None:
            return
        manifest, diagnostics = read_manifest(text, ModuleManifest, manifest_file)
        self.manifest_diagnostics(diagnostics)
        if manifest is None:
            return
        module_where = positions(text)
        if manifest.module.name != name:
            line, col = locate(module_where, ("module", "name"))
            self.error(
                "module-name-mismatch",
                f"the folder is {name} but module.toml says {manifest.module.name!r}",
                manifest_file, line, col,
            )

        constants, problems = module_constants(self.project.constants, manifest.params, given)
        for problem in problems:
            self._constant_problem(problem, index, project_where, manifest_file, module_where)

        module = LoadedModule(name=name, manifest=manifest, constants=constants)
        sources = sorted((self.scripts / base).rglob(f"*{SOURCE_SUFFIX}"))
        if not sources:
            self.warn("module-empty", f"module {name} has no {SOURCE_SUFFIX} files", manifest_file)
        for path in sources:
            relative = path.relative_to(self.scripts).as_posix()
            source_text = self.read(relative)
            if source_text is not None:
                module.files.append(self._process(relative, f"module:{name}", source_text, constants))
        self.project.modules.append(module)

    def _constant_problem(
        self, problem: ConstantProblem, index: int, project_where: dict, manifest_file: str, module_where: dict
    ) -> None:
        if problem.source == "importer":
            path = ("modules", index, "params", problem.name) if problem.code != "param-missing" else ("modules", index)
            line, col = locate(project_where, path)
            self.error(problem.code, f"module parameter: {problem.message}", PROJECT_FILENAME, line, col)
        else:
            line, col = locate(module_where, ("params", problem.name, "default"))
            self.error(problem.code, problem.message, manifest_file, line, col)

    def _load_blocks(self) -> None:
        blocks_dir = self.scripts / BLOCKS_DIRNAME
        if not blocks_dir.is_dir():
            return
        for path in sorted(blocks_dir.glob(f"*{SOURCE_SUFFIX}")):
            relative = path.relative_to(self.scripts).as_posix()
            name = path.stem.upper()
            if not _BLOCK_NAME.fullmatch(name):
                self.error("block-name", f"{path.stem!r} can't be a block name (letters, digits and underscores)", relative)
                continue
            # Registered before reading, so a block whose file can't be read is still *defined* (the read error is the
            # problem; "nothing defines this block" would be a second, misleading one).
            block = self.project.blocks[name] = LoadedBlock(name=name)
            text = self.read(relative)
            if text is not None:
                block.file = self._process(relative, f"block:{name}", text, self.project.constants)
                for annotation in block.file.annotations.items:
                    if isinstance(annotation, BlockAnnotation) and annotation.name != name:
                        self.error(
                            "block-name-mismatch",
                            f"this file is block {name} (from its name), but @block says {annotation.name}",
                            relative, annotation.span.start_line, annotation.span.start_col,
                        )

    def _collect_blocks(self, manifest: ProjectManifest, where: dict) -> None:
        """Every block a fragment names exists, and every module knows which blocks it contributes to."""
        for module in self.project.modules:
            for file in module.files:
                for annotation in file.annotations.items:
                    if isinstance(annotation, BlockAnnotation):
                        self.error(
                            "block-in-module",
                            "@block belongs at the top of a file in blocks/; a module contributes with @fragment",
                            file.path, annotation.span.start_line, annotation.span.start_col,
                        )
                    if isinstance(annotation, FragmentAnnotation):
                        block = self.project.blocks.setdefault(annotation.block, LoadedBlock(name=annotation.block))
                        if module.name not in block.contributors:
                            block.contributors.append(module.name)
                        if annotation.block not in module.blocks:
                            module.blocks.append(annotation.block)

        seen: set[str] = set()
        for index, name in enumerate(manifest.blocks.order):
            line, col = locate(where, ("blocks", "order"))
            if name in seen:
                self.error("block-order-duplicate", f"block {name} is listed twice in [blocks].order", PROJECT_FILENAME, line, col)
            seen.add(name)
            if name not in self.project.blocks:
                self.warn(
                    "block-undefined",
                    f"[blocks].order lists {name}, but no file or fragment defines it",
                    PROJECT_FILENAME, line, col,
                )

    def _order(self, manifest: ProjectManifest, where: dict) -> None:
        listed = list(dict.fromkeys(manifest.blocks.order))
        universe = list(dict.fromkeys([*listed, *self.project.blocks]))
        for name in universe:
            self.project.blocks.setdefault(name, LoadedBlock(name=name))

        edges = [Edge(a, b, "project.toml [blocks].order") for a, b in zip(listed, listed[1:])]
        for module in self.project.modules:
            order = module.manifest.order
            manifest_file = f"{MODULES_DIRNAME}/{module.name}/{MODULE_FILENAME}"
            module_where = positions(self.raw(manifest_file))
            source = f"module {module.name} [order]"
            # Not when the module's files failed to load: their fragments are missing because of *that* problem.
            files_loaded = bool(module.files) and all(file.processed is not None for file in module.files)
            if (order.after or order.before) and not module.blocks and files_loaded:
                line, col = locate(module_where, ("order",))
                self.warn("order-unused", f"module {module.name} has an [order] but contributes no fragments", manifest_file, line, col)
            for key, names in (("after", order.after), ("before", order.before)):
                for name in names:
                    if name not in self.project.blocks:
                        line, col = locate(module_where, ("order", key))
                        self.error("order-unknown-block", f"[order].{key} names {name}, but no block has that name", manifest_file, line, col)
                        continue
                    for block in module.blocks:
                        edges.append(Edge(name, block, source) if key == "after" else Edge(block, name, source))

        result, cycle = order_blocks(universe, listed, edges)
        self.project.order = result
        if cycle is not None:
            line, col = locate(where, ("blocks", "order"))
            steps = ", ".join(f"{e.before} before {e.after} ({e.source})" for e in cycle)
            self.error("order-cycle", f"the blocks can't be ordered: {steps}", PROJECT_FILENAME, line, col)

    def _merge_kinds(self, manifest: ProjectManifest, where: dict) -> None:
        claimed: dict[str, str] = {}  # a reached_by entry -> the kind that claims it

        def add(kind_name: str, spec: KindSpec, owner: str, file: str, positions_: dict) -> None:
            line, col = locate(positions_, ("kinds", kind_name))
            existing = self.project.kinds.get(kind_name)
            if existing is not None and set(existing.reached_by) != set(spec.reached_by):
                self.error(
                    "kind-conflict",
                    f"kind {kind_name} is also defined by {', '.join(existing.defined_by)} with a different reached_by",
                    file, line, col,
                )
                return
            merged = existing or MergedKind(reached_by=[], defined_by=[])
            merged.defined_by.append(owner)
            for entry in spec.reached_by:
                other = claimed.get(entry)
                if other is not None and other != kind_name:
                    self.error("kind-conflict", f"{entry!r} can't reach both {other} and {kind_name}", file, line, col)
                    continue
                claimed[entry] = kind_name
                if entry not in merged.reached_by:
                    merged.reached_by.append(entry)
            self.project.kinds[kind_name] = merged

        for kind_name, spec in manifest.kinds.items():
            add(kind_name, spec, "project.toml", PROJECT_FILENAME, where)
        for module in self.project.modules:
            manifest_file = f"{MODULES_DIRNAME}/{module.name}/{MODULE_FILENAME}"
            module_where = positions(self.raw(manifest_file))
            for kind_name, spec in module.manifest.kinds.items():
                add(kind_name, spec, f"module {module.name}", manifest_file, module_where)


def load_project(folder: Path, overrides: dict[str, str] | None = None) -> ScriptProject:
    """Loads ``folder``'s script project (``folder`` is the gametype project, not ``script/``).

    Never raises for a problem in the project's files; they come back in :attr:`ScriptProject.diagnostics`. A
    folder with no ``script/project.toml`` yields a project with one ``project-missing`` error (check
    :func:`is_linked` first to tell a single-file project from a broken linked one, or use :func:`load_script`).
    ``overrides`` maps a path relative to ``script/`` to text that stands in for that file (unsaved editor buffers)."""
    if not is_linked(folder):
        loader = _Loader(folder)
        loader.error("project-missing", "there is no script/project.toml", PROJECT_FILENAME)
        return loader.project
    return _Loader(folder, overrides).load()


SINGLE_FILE = new_project.SCRIPT_FILENAME
SINGLE_BLOCK = "MAIN"
#: What only a script project can express: how blocks and fragments are cut and ordered.
_PROJECT_STRUCTURE = frozenset(
    {"block", "fragment", "loop", "gate", "guard", "guard_end", "preamble", "provides", "traits", "fusion", "assumes"}
)
#: What only a script project does for you: pick a storage slot for a name, or a table entry for a resource. A single
#: file names its slots itself (``global.number[0]``) and its resources by index (``script_traits[0]``).
_PROJECT_ALLOCATED = frozenset({"storage", "bitfield", "trait", "option", "widget", "label"})
_PROJECT_ONLY = _PROJECT_STRUCTURE | _PROJECT_ALLOCATED
_WRITTEN_NAME = re.compile(r"@([A-Za-z][A-Za-z0-9_-]*)")


def _project_only_message(annotation, line: str) -> str:
    match = _WRITTEN_NAME.search(line)
    written = f"@{match[1]}" if match else f"@{annotation.kind.replace('_', '-')}"
    if annotation.kind in _PROJECT_ALLOCATED:
        return (
            f"{written} has in-reach choose a slot or table entry for you, which only a script project does -- in a "
            "single file write it yourself (global.number[0], script_traits[0]), or Convert to Project"
        )
    return f"{written} belongs in a script project (Convert to Project to use it)"


def load_single_file(folder: Path, text: str | None = None) -> ScriptProject:
    """``folder``'s ``script/output.mgl`` as a project of one block, :data:`SINGLE_BLOCK`, so the model, the linter
    and the allocator read it the same way they read a script project. ``text`` stands in for the file's content
    (an unsaved editor buffer).

    The file is preprocessed exactly as a single-file build always has been (the active env, nothing else). What a
    single file gets from annotations is documentation (``@doc``, ``@tags``, ``@see``) and the checks; anything that has
    in-reach choose for it -- a storage slot (``@number``), a trait set or other table entry (``@trait``), a label -- or
    that shapes blocks and fragments is a ``project-only`` error, since that is what a script project is for. An
    *unknown* ``-- @name`` is a warning, since before a single file's annotations were read it was just a comment."""
    loader = _Loader(folder)
    project = loader.project
    project.manifest = ProjectManifest()
    name = script_preprocess.active_env_name(folder)
    if name:
        try:
            project.env = script_preprocess.load_env(folder, name)
        except script_preprocess.PreprocessError as exc:
            loader.error("env-invalid", exc.message, f"{script_preprocess.ENV_DIRNAME}/{name}{script_preprocess.ENV_SUFFIX}", exc.line, exc.col)
            return project
    if project.env is not None:
        project.constants = dict(project.env.constants)

    if text is None:
        path = new_project.migrate_script_file(folder)
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
    try:
        processed: str | None = script_preprocess.preprocess(text, project.env)
    except script_preprocess.PreprocessError as exc:
        loader.error("preprocess", exc.message, SINGLE_FILE, exc.line, exc.col)
        processed = None
    annotations = parse_annotations(processed) if processed is not None else Annotations()
    for diagnostic in annotations.diagnostics:
        severity = "warning" if diagnostic.message.startswith("unknown annotation") else "error"
        loader.report(severity, "annotation", diagnostic.message, SINGLE_FILE, diagnostic.span.start_line, diagnostic.span.start_col)
    lines = (processed or "").split("\n")
    for annotation in annotations.items:
        if annotation.kind in _PROJECT_ONLY:
            line = lines[annotation.span.start_line - 1] if annotation.span.start_line <= len(lines) else ""
            loader.error(
                "project-only", _project_only_message(annotation, line),
                SINGLE_FILE, annotation.span.start_line, annotation.span.start_col,
            )
    source = SourceFile(path=SINGLE_FILE, owner=f"block:{SINGLE_BLOCK}", text=text, processed=processed, annotations=annotations)
    project.blocks[SINGLE_BLOCK] = LoadedBlock(name=SINGLE_BLOCK, file=source)
    project.order = [SINGLE_BLOCK]
    return project


def load_script(folder: Path, overrides: dict[str, str] | None = None) -> ScriptProject:
    """Whichever of the two ``folder`` is: its script project, or its single file as a one-block project. See
    :func:`load_project` for ``overrides``."""
    if is_linked(folder):
        return load_project(folder, overrides)
    return load_single_file(folder, (overrides or {}).get(SINGLE_FILE))
