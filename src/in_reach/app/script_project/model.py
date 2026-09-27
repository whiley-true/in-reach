"""The semantic model of a loaded project: what its files *mean*, not just what they contain.

:func:`~in_reach.app.script_project.project.load_project` reads files, manifests and annotations. This turns a
project into the things a linter and a linker reason about:

* **fragments** -- a loop body plus the header that says which block it belongs to and what loop it runs in;
* **preamble definitions** -- a shared prologue, with the variables it provides and where fragments go in it;
* **block code** -- the hand-authored code of a block file, and where its ``@import`` lines put fragments;
* every **declaration**: storage (``@pnumber``), engine resources (``@trait`` ...), bitfields.

How a file is cut into regions (``TO_IMPLEMENT`` §4.6, §13.6)
-------------------------------------------------------------

A **header run** is a run of annotation lines with no blank line or code between them. A run that contains
``@fragment`` opens a *fragment*; a run that contains ``@preamble`` but no ``@fragment`` opens a *preamble
definition* (in a fragment's header ``@preamble`` names one to use instead). A run with a ``@loop`` and neither opens
the module's one *implicit* fragment: named after the module, in whichever block has ``-- @import <module>`` (a module
with more than one loop names each with ``@fragment BLOCK.NAME``). A region's **body** is every line
after its header run up to the next header run. ``@guard-end`` is never part of a header: it marks a spot inside
the preamble body it sits in. Code before a module's first header belongs to nothing, which is reported.

Every problem found here (a fragment with no ``@loop``, a preamble nobody defined ...) is a diagnostic, and the
model is built regardless, so the linter can carry on with what is sound.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from in_reach.app.rvt.megalo_ast.annotations import (
    AssumesAnnotation,
    BitfieldAnnotation,
    DocAnnotation,
    FragmentAnnotation,
    GateAnnotation,
    GuardAnnotation,
    GuardEndAnnotation,
    ImportAnnotation,
    LabelAnnotation,
    LoopAnnotation,
    OptionAnnotation,
    PreambleAnnotation,
    ProvidedVariable,
    ProvidesAnnotation,
    StorageAnnotation,
    TraitAnnotation,
    TraitsAnnotation,
    WidgetAnnotation,
)

from in_reach.app.rvt.megalo_ast import MegaloLexError, MegaloParseError, parse
from in_reach.app.rvt.megalo_ast.nodes import Script

from .diagnostics import ProjectDiagnostic
from .project import ScriptProject, SourceFile

_ANNOTATION_LINE = re.compile(r"^\s*--\s*@[A-Za-z]")
_HEADER_KINDS = ("fragment", "preamble")


@dataclass
class Fragment:
    """A loop body that lives in a block. ``body`` is the source lines after its header, verbatim. An ``implicit``
    fragment (no ``@fragment`` line: its module's only loop) is named after its module, and its ``block`` is ``""``
    until a block's ``@import`` places it."""

    module: str
    block: str
    name: str
    file: str
    line: int  # of its @fragment annotation
    loop: str | None = None
    gate: GateAnnotation | None = None
    guards: list[GuardAnnotation] = field(default_factory=list)
    preamble: str | None = None
    layer: str | None = None
    assumes: list[AssumesAnnotation] = field(default_factory=list)
    doc: list[str] = field(default_factory=list)
    body: list[str] = field(default_factory=list)
    body_line: int = 0  # 1-based line of body[0]
    implicit: bool = False

    @property
    def id(self) -> str:
        return f"{self.module}.{self.name}"


@dataclass
class PreambleDef:
    """A shared prologue. ``body`` is its source; ``guard_index`` is the index in ``body`` of its
    ``@guard-end`` line, where fragments are inserted (``None``: at the end)."""

    name: str
    module: str
    file: str
    line: int
    provides: list[ProvidedVariable] = field(default_factory=list)
    doc: list[str] = field(default_factory=list)
    body: list[str] = field(default_factory=list)
    body_line: int = 0
    guard_index: int | None = None


@dataclass
class BlockCode:
    """A block file's code: every line of it, annotations and all (they are comments). ``placed`` is where its
    ``@import`` lines put fragments: ``(index in lines, fragments)`` in line order; the block's other fragments go after
    its code."""

    block: str
    file: str
    lines: list[str]
    assumes: list[AssumesAnnotation] = field(default_factory=list)
    imports: list[ImportAnnotation] = field(default_factory=list)
    placed: list[tuple[int, list["Fragment"]]] = field(default_factory=list)


@dataclass
class Declared:
    """One declared name, with where it came from. ``owner`` is the module (or block file path) declaring it."""

    annotation: StorageAnnotation | BitfieldAnnotation | TraitAnnotation | OptionAnnotation | WidgetAnnotation | LabelAnnotation
    file: str
    owner: str


@dataclass
class SemanticModel:
    project: ScriptProject
    fragments: list[Fragment] = field(default_factory=list)
    preambles: dict[str, PreambleDef] = field(default_factory=dict)
    blocks: dict[str, BlockCode] = field(default_factory=dict)
    storage: list[Declared] = field(default_factory=list)
    bitfields: list[Declared] = field(default_factory=list)
    resources: list[Declared] = field(default_factory=list)  # traits, options, widgets, labels
    diagnostics: list[ProjectDiagnostic] = field(default_factory=list)
    _parsed: dict[str, Script | MegaloLexError | MegaloParseError] = field(default_factory=dict, repr=False)

    def fragments_of(self, block: str) -> list[Fragment]:
        return [fragment for fragment in self.fragments if fragment.block == block]

    def parse(self, lines: list[str]) -> Script:
        """``lines`` parsed, once per distinct text however many checks ask (read-only: the tree is shared).

        Raises:
            MegaloLexError, MegaloParseError: The code doesn't parse."""
        text = "\n".join(lines)
        if text not in self._parsed:
            try:
                self._parsed[text] = parse(text)
            except (MegaloLexError, MegaloParseError) as exc:
                self._parsed[text] = exc
        found = self._parsed[text]
        if isinstance(found, Exception):
            raise found
        return found


def _is_annotation_line(line: str) -> bool:
    return bool(_ANNOTATION_LINE.match(line))


def build_model(project: ScriptProject) -> SemanticModel:
    """Builds the model of ``project`` (which should have loaded; a file that failed to preprocess is skipped)."""
    model = SemanticModel(project=project)
    for name, block in project.blocks.items():
        if block.file is not None and block.file.processed is not None:
            _block_code(model, name, block.file)
    for module in project.modules:
        for file in module.files:
            if file.processed is not None:
                _module_file(model, module.name, file)
    _collect_declarations(model)
    _check_preamble_uses(model)
    _place_imports(model)
    return model


def _diagnose(model: SemanticModel, severity: str, code: str, message: str, file: str, line: int) -> None:
    model.diagnostics.append(ProjectDiagnostic(severity=severity, code=code, message=message, file=file, line=line))


# -- block files ----------------------------------------------------------------------------------------


def _block_code(model: SemanticModel, name: str, file: SourceFile) -> None:
    lines = (file.processed or "").split("\n")
    assumes = [a for a in file.annotations.items if isinstance(a, AssumesAnnotation)]
    imports = [a for a in file.annotations.items if isinstance(a, ImportAnnotation)]
    model.blocks[name] = BlockCode(block=name, file=file.path, lines=lines, assumes=assumes, imports=imports)
    for annotation in file.annotations.items:
        if isinstance(annotation, FragmentAnnotation):
            _diagnose(
                model, "error", "fragment-in-block",
                "a block file is hand-written code; fragments belong in a module",
                file.path, annotation.span.start_line,
            )


def _place_imports(model: SemanticModel) -> None:
    """Resolves each block's ``@import`` lines to the fragments they place (``BlockCode.placed``). An import must name a
    module (or one of its fragments) that contributes to *this* block; a module import places whatever of it an earlier
    line hasn't, and an import with nothing left to place is reported. The import of a module whose loop has no
    ``@fragment`` line is what puts that loop in the block -- so exactly one block must import it."""
    project = model.project
    modules = {module.name: module for module in project.modules}
    ordered = [model.blocks[name] for name in project.order if name in model.blocks]
    ordered += [code for code in model.blocks.values() if code not in ordered]
    for code in ordered:
        placed: set[int] = set()
        for annotation in sorted(code.imports, key=lambda a: a.span.start_line):
            line = annotation.span.start_line
            if annotation.module in project.disabled_modules:
                continue  # kept, not built: nothing to place
            if annotation.module not in modules:
                _diagnose(model, "error", "import-unknown", f"@import {annotation.target}: there is no module {annotation.module}", code.file, line)
                continue
            if not _claim_implicit(model, modules[annotation.module], annotation, code):
                continue
            fragments = [
                f for f in model.fragments
                if f.module == annotation.module and f.block == code.block and annotation.fragment in (None, f.name)
            ]
            if not fragments:
                elsewhere = sorted({f.block for f in model.fragments if f.module == annotation.module})
                where = f" (its fragments are in {', '.join(elsewhere)})" if elsewhere else ""
                _diagnose(
                    model, "error", "import-empty",
                    f"@import {annotation.target}: it has no fragment for block {code.block}{where}", code.file, line,
                )
                continue
            # `@import tidy` after `@import tidy.second` places the rest of tidy; nothing left to place is a mistake.
            fragments = [f for f in fragments if id(f) not in placed]
            if not fragments:
                _diagnose(model, "error", "import-duplicate", f"@import {annotation.target}: already imported above in this block", code.file, line)
                continue
            placed.update(id(f) for f in fragments)
            code.placed.append((line - 1, fragments))
    for fragment in model.fragments:
        if fragment.implicit and not fragment.block:
            _diagnose(
                model, "error", "module-unplaced",
                f"module {fragment.module} has a loop, but no block imports it -- add '-- @import {fragment.module}' to a block",
                fragment.file, fragment.line,
            )


def _claim_implicit(model: SemanticModel, module, annotation: ImportAnnotation, code: BlockCode) -> bool:
    """Puts ``module``'s implicit fragment (if the import names it) in ``code``'s block. ``False``: it is already in
    another block (reported)."""
    for fragment in model.fragments:
        if not (fragment.implicit and fragment.module == module.name and annotation.fragment in (None, fragment.name)):
            continue
        if fragment.block and fragment.block != code.block:
            _diagnose(
                model, "error", "import-elsewhere",
                f"@import {annotation.target}: block {fragment.block} already imports it, and a loop runs in one block",
                code.file, annotation.span.start_line,
            )
            return False
        if not fragment.block:
            fragment.block = code.block
            loaded = model.project.blocks.get(code.block)
            if loaded is not None and module.name not in loaded.contributors:
                loaded.contributors.append(module.name)
            if code.block not in module.blocks:
                module.blocks.append(code.block)
    return True


# -- module files ---------------------------------------------------------------------------------------


@dataclass
class _Run:
    """A run of annotation lines: ``[first, last]`` line numbers (1-based) and what they say."""

    first: int
    last: int
    annotations: list


def _runs(file: SourceFile, lines: list[str]) -> list[_Run]:
    """The runs of contiguous annotation lines, excluding ``@guard-end`` (which is body, never header)."""
    by_line = {a.span.start_line: a for a in file.annotations.items}
    runs: list[_Run] = []
    current: _Run | None = None
    for number, text in enumerate(lines, start=1):
        annotation = by_line.get(number)
        is_marker = isinstance(annotation, GuardEndAnnotation)
        if _is_annotation_line(text) and not is_marker:
            if current is None:
                current = _Run(first=number, last=number, annotations=[])
                runs.append(current)
            current.last = number
            if annotation is not None:
                current.annotations.append(annotation)
        else:
            current = None
    return runs


def _module_file(model: SemanticModel, module: str, file: SourceFile) -> None:
    lines = (file.processed or "").split("\n")
    headers: list[tuple[_Run, str]] = []
    for run in _runs(file, lines):
        kinds = {a.kind for a in run.annotations}
        if "fragment" in kinds:
            headers.append((run, "fragment"))
        elif "preamble" in kinds:
            headers.append((run, "preamble"))
        elif "loop" in kinds:
            headers.append((run, "implicit"))

    first_header_line = headers[0][0].first if headers else len(lines) + 1
    for number in range(1, first_header_line):
        text = lines[number - 1]
        if text.strip() and not _is_annotation_line(text) and not text.lstrip().startswith("--"):
            _diagnose(
                model, "warning", "loose-code",
                "this code isn't in a fragment or a preamble, so it won't be part of the build",
                file.path, number,
            )
            break

    for index, (run, kind) in enumerate(headers):
        end = headers[index + 1][0].first - 1 if index + 1 < len(headers) else len(lines)
        body = lines[run.last:end]
        body_line = run.last + 1
        if kind in ("fragment", "implicit"):
            _fragment(model, module, file, run, body, body_line)
        else:
            _preamble(model, module, file, run, body, body_line)


def _doc_lines(run: _Run) -> list[str]:
    return [a.text for a in run.annotations if isinstance(a, DocAnnotation)]


def _fragment(model: SemanticModel, module: str, file: SourceFile, run: _Run, body: list[str], body_line: int) -> None:
    head = next((a for a in run.annotations if isinstance(a, FragmentAnnotation)), None)
    if head is None:  # the module's one loop: named after it, placed by an @import
        loop = next(a for a in run.annotations if isinstance(a, LoopAnnotation))
        fragment = Fragment(
            module=module, block="", name=module, file=file.path, line=loop.span.start_line,
            doc=_doc_lines(run), body=body, body_line=body_line, implicit=True,
        )
        if any(f.module == module and f.implicit for f in model.fragments):
            _diagnose(
                model, "error", "loop-unnamed",
                f"module {module} has more than one loop without @fragment -- name each with @fragment BLOCK.NAME",
                file.path, fragment.line,
            )
    else:
        fragment = Fragment(
            module=module, block=head.block, name=head.name, file=file.path, line=head.span.start_line,
            doc=_doc_lines(run), body=body, body_line=body_line,
        )
    seen: set[str] = set()
    for annotation in run.annotations:
        if isinstance(annotation, FragmentAnnotation) and annotation is not head:
            _diagnose(model, "error", "header-duplicate", "a fragment header has one @fragment", file.path, annotation.span.start_line)
        elif isinstance(annotation, LoopAnnotation):
            _once(model, file, annotation, "loop", seen)
            fragment.loop = fragment.loop or annotation.selector
        elif isinstance(annotation, GateAnnotation):
            _once(model, file, annotation, "gate", seen)
            fragment.gate = fragment.gate or annotation
        elif isinstance(annotation, GuardAnnotation):
            fragment.guards.append(annotation)
        elif isinstance(annotation, PreambleAnnotation):
            _once(model, file, annotation, "preamble", seen)
            fragment.preamble = fragment.preamble or annotation.name
        elif isinstance(annotation, TraitsAnnotation):
            _once(model, file, annotation, "traits", seen)
            fragment.layer = fragment.layer or annotation.layer
        elif isinstance(annotation, AssumesAnnotation):
            fragment.assumes.append(annotation)
        elif isinstance(annotation, ProvidesAnnotation):
            _diagnose(model, "error", "provides-outside-preamble", "@provides belongs to a preamble's definition", file.path, annotation.span.start_line)

    if fragment.loop is None:
        _diagnose(model, "error", "fragment-no-loop", f"fragment {fragment.id} needs a @loop (player, object or team)", file.path, fragment.line)
    if any(f.id == fragment.id for f in model.fragments):
        _diagnose(model, "error", "fragment-duplicate", f"fragment {fragment.id} is defined twice", file.path, fragment.line)
    model.fragments.append(fragment)


def _once(model: SemanticModel, file: SourceFile, annotation, what: str, seen: set[str]) -> None:
    if what in seen:
        _diagnose(model, "error", "header-duplicate", f"a fragment header has one @{what}", file.path, annotation.span.start_line)
    seen.add(what)


def _preamble(model: SemanticModel, module: str, file: SourceFile, run: _Run, body: list[str], body_line: int) -> None:
    head = next(a for a in run.annotations if isinstance(a, PreambleAnnotation))
    provides = [v for a in run.annotations if isinstance(a, ProvidesAnnotation) for v in a.variables]
    guard_index = next(
        (i for i, text in enumerate(body) if re.match(r"^\s*--\s*@guard-end\b", text)), None
    )
    definition = PreambleDef(
        name=head.name, module=module, file=file.path, line=head.span.start_line,
        provides=provides, doc=_doc_lines(run), body=body, body_line=body_line, guard_index=guard_index,
    )
    for annotation in run.annotations:
        if isinstance(annotation, (LoopAnnotation, GateAnnotation)):
            _diagnose(
                model, "error", "header-mismatch",
                f"@{annotation.kind} belongs in a fragment's header, not a preamble's definition",
                file.path, annotation.span.start_line,
            )
    if head.name in model.preambles:
        other = model.preambles[head.name]
        _diagnose(
            model, "error", "preamble-duplicate",
            f"preamble {head.name} is already defined in {other.file}:{other.line}", file.path, definition.line,
        )
        return
    model.preambles[head.name] = definition


def _check_preamble_uses(model: SemanticModel) -> None:
    for fragment in model.fragments:
        if fragment.preamble is not None and fragment.preamble not in model.preambles:
            _diagnose(
                model, "error", "preamble-unknown",
                f"fragment {fragment.id} uses preamble {fragment.preamble}, which no file defines",
                fragment.file, fragment.line,
            )


# -- declarations ---------------------------------------------------------------------------------------


def _collect_declarations(model: SemanticModel) -> None:
    project = model.project
    sources: list[tuple[SourceFile, str]] = [
        (block.file, block.file.path) for block in project.blocks.values() if block.file is not None
    ]
    sources += [(file, f"module {module.name}") for module in project.modules for file in module.files]
    for file, owner in sources:
        for annotation in file.annotations.items:
            declared = Declared(annotation=annotation, file=file.path, owner=owner)
            if isinstance(annotation, StorageAnnotation):
                model.storage.append(declared)
            elif isinstance(annotation, BitfieldAnnotation):
                model.bitfields.append(declared)
            elif isinstance(annotation, (TraitAnnotation, OptionAnnotation, WidgetAnnotation, LabelAnnotation)):
                model.resources.append(declared)
