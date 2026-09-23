"""The semantic model of a loaded project: what its files *mean*, not just what they contain.

:func:`~in_reach.app.script_project.project.load_project` reads files, manifests and annotations. This turns a
project into the things a linter and a linker reason about:

* **fragments** -- a loop body plus the header that says which block it belongs to and what loop it runs in;
* **preamble definitions** -- a shared prologue, with the variables it provides and where fragments go in it;
* **block code** -- the hand-authored code of a block file;
* every **declaration**: storage (``@pnumber``), engine resources (``@trait`` ...), bitfields.

How a file is cut into regions (``TO_IMPLEMENT`` §4.6, §13.6)
-------------------------------------------------------------

A **header run** is a run of annotation lines with no blank line or code between them. A run that contains
``@fragment`` opens a *fragment*; a run that contains ``@preamble`` but no ``@fragment`` opens a *preamble
definition* (in a fragment's header ``@preamble`` names one to use instead). A region's **body** is every line
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
    FusionAnnotation,
    GateAnnotation,
    GuardAnnotation,
    GuardEndAnnotation,
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
    """A loop body that lives in a block. ``body`` is the source lines after its header, verbatim."""

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
    fusion: FusionAnnotation | None = None
    assumes: list[AssumesAnnotation] = field(default_factory=list)
    doc: list[str] = field(default_factory=list)
    body: list[str] = field(default_factory=list)
    body_line: int = 0  # 1-based line of body[0]

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
    """A block file's code: every line of it, annotations and all (they are comments)."""

    block: str
    file: str
    lines: list[str]
    assumes: list[AssumesAnnotation] = field(default_factory=list)


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
    return model


def _diagnose(model: SemanticModel, severity: str, code: str, message: str, file: str, line: int) -> None:
    model.diagnostics.append(ProjectDiagnostic(severity=severity, code=code, message=message, file=file, line=line))


# -- block files ----------------------------------------------------------------------------------------


def _block_code(model: SemanticModel, name: str, file: SourceFile) -> None:
    lines = (file.processed or "").split("\n")
    assumes = [a for a in file.annotations.items if isinstance(a, AssumesAnnotation)]
    model.blocks[name] = BlockCode(block=name, file=file.path, lines=lines, assumes=assumes)
    for annotation in file.annotations.items:
        if isinstance(annotation, FragmentAnnotation):
            _diagnose(
                model, "error", "fragment-in-block",
                "a block file is hand-written code; fragments belong in a module",
                file.path, annotation.span.start_line,
            )


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
        if kind == "fragment":
            _fragment(model, module, file, run, body, body_line)
        else:
            _preamble(model, module, file, run, body, body_line)


def _doc_lines(run: _Run) -> list[str]:
    return [a.text for a in run.annotations if isinstance(a, DocAnnotation)]


def _fragment(model: SemanticModel, module: str, file: SourceFile, run: _Run, body: list[str], body_line: int) -> None:
    head = next(a for a in run.annotations if isinstance(a, FragmentAnnotation))
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
        elif isinstance(annotation, FusionAnnotation):
            _once(model, file, annotation, "fusion", seen)
            fragment.fusion = fragment.fusion or annotation
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
        if isinstance(annotation, (LoopAnnotation, GateAnnotation, FusionAnnotation)):
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
