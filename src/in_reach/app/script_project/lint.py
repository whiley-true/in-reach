"""The linter's structural rules (``TO_IMPLEMENT`` §8) -- the ones that need only the project's own text.

Each diagnostic carries the rule's id as its ``code`` (``IR006``), its file and line, and a one-line ``hint``.

Implemented here:

======  =============================================================================================
IR005   a timer declared with a network priority (``declare global.timer[0] with network priority ...``)
IR006   a name declared twice -- across annotations, or the same ``declare`` slot twice
IR007   ``true`` / ``false`` used as a value: the grammar has no boolean literal, so they are bare words
IR010   an unlabelled ``for each object`` in something that runs every tick
IR011   a bitfield of more than 15 flags (bit 15 is reserved)
IR016   ``@assumes BLOCK`` where BLOCK doesn't come before the block that assumes it
======  =============================================================================================

Also: ``kind-unknown`` (object storage or a bitfield against a kind nobody declares), ``team-owner-invalid``, and
``body-syntax`` (a region's code that doesn't parse).

Not here, because they need an engine catalog or the linker's output: IR001-IR004, IR008, IR009, IR012, IR014,
IR018 (and IR006b). IR013 is the block-order cycle ``load_project`` already reports (``order-cycle``), IR015 the
unresolved-constant errors it reports (``preprocess``, ``constant-*``, ``param-*``), and IR017 no longer exists
(``next_steps.md`` decision 1 dropped ``[requires]``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from in_reach.app.rvt.megalo_ast import MegaloLexError, MegaloParseError, parse, walk
from in_reach.app.rvt.megalo_ast.annotations import BitfieldAnnotation, StorageAnnotation
from in_reach.app.rvt.megalo_ast.nodes import ForEach, Identifier, Script, VariableDeclaration

from .diagnostics import ProjectDiagnostic
from .model import SemanticModel

_TEAM_OWNER = re.compile(r"team[0-7]")
_MAX_BITFIELD_FLAGS = 15


@dataclass
class _Region:
    """A stretch of code to analyse. ``per_tick``: it runs every tick (so IR010 applies)."""

    file: str
    first_line: int  # the 1-based line of lines[0]
    lines: list[str]
    per_tick: bool
    what: str


def lint(model: SemanticModel) -> list[ProjectDiagnostic]:
    """Every structural problem in ``model``'s project, in a stable order."""
    linter = _Linter(model)
    linter.run()
    return linter.found


class _Linter:
    def __init__(self, model: SemanticModel) -> None:
        self.model = model
        self.found: list[ProjectDiagnostic] = []

    def add(self, code: str, message: str, file: str, line: int, hint: str = "", severity: str = "error") -> None:
        self.found.append(ProjectDiagnostic(severity=severity, code=code, message=message, file=file, line=line, hint=hint))

    def run(self) -> None:
        self._duplicate_names()
        self._kinds_and_owners()
        self._bitfields()
        self._assumptions()
        for region in self._regions():
            script = self._parse(region)
            if script is not None:
                self._code_rules(region, script)
        self._loop_annotations()

    # -- regions of code ------------------------------------------------------------------------------

    def _regions(self) -> list[_Region]:
        regions = [
            _Region(block.file, 1, block.lines, per_tick=True, what=f"block {name}")
            for name, block in self.model.blocks.items()
        ]
        for fragment in self.model.fragments:
            regions.append(_Region(fragment.file, fragment.body_line, fragment.body, True, f"fragment {fragment.id}"))
        for preamble in self.model.preambles.values():
            regions.append(_Region(preamble.file, preamble.body_line, preamble.body, True, f"preamble {preamble.name}"))
        return regions

    def _parse(self, region: _Region) -> Script | None:
        try:
            return parse("\n".join(region.lines))
        except (MegaloLexError, MegaloParseError) as exc:
            token = getattr(exc, "token", None)
            line = region.first_line + (getattr(token, "start_line", 1) - 1)
            self.add(
                "body-syntax", str(exc).split(" at line")[0], region.file, line,
                hint=f"in {region.what}", severity="error",
            )
            return None

    def _code_rules(self, region: _Region, script: Script) -> None:
        def line_of(node) -> int:
            return region.first_line + node.span.start_line - 1

        event_statements = {id(statement) for statement in script.body if statement.kind == "on"}
        per_tick_nodes: set[int] = set()
        if region.per_tick:
            for statement in script.body:
                if id(statement) not in event_statements:
                    per_tick_nodes.update(id(node) for node in walk(statement))

        for node in walk(script):
            if isinstance(node, Identifier) and node.name in ("true", "false"):
                self.add(
                    "IR007", f"{node.name!r} is not a value in Megalo -- it is just an unknown name",
                    region.file, line_of(node), hint="use 1 or 0",
                )
            elif isinstance(node, VariableDeclaration) and node.type == "timer" and node.priority is not None:
                self.add(
                    "IR005", f"a timer has no network priority, but {node.scope}.timer[{node.index}] is declared with one",
                    region.file, line_of(node), hint="remove 'with network priority ...'",
                )
            elif isinstance(node, ForEach) and node.selector == "object" and node.label is None and id(node) in per_tick_nodes:
                self.add(
                    "IR010", "an unlabelled 'for each object' in something that runs every tick visits every object in the map",
                    region.file, line_of(node), hint="give the objects a label and use 'with label ...'",
                )

    def _loop_annotations(self) -> None:
        for fragment in self.model.fragments:
            if fragment.loop == "object":
                self.add(
                    "IR010", f"fragment {fragment.id} loops over every object in the map every tick",
                    fragment.file, fragment.line, hint="loop over players and use 'for each object with label ...' inside",
                )

    # -- declarations ---------------------------------------------------------------------------------

    def _duplicate_names(self) -> None:
        first: dict[str, tuple[str, int]] = {}
        declared = [(d.annotation.name, d.file, d.annotation.span.start_line) for d in self.model.storage]
        declared += [(d.annotation.name, d.file, d.annotation.span.start_line) for d in self.model.resources]
        declared += [(d.annotation.name, d.file, d.annotation.span.start_line) for d in self.model.bitfields]
        declared += [(v.name, p.file, p.line) for p in self.model.preambles.values() for v in p.provides]
        for name, file, line in declared:
            if name in first:
                where_file, where_line = first[name]
                self.add(
                    "IR006", f"{name} is already declared at {where_file}:{where_line}", file, line,
                    hint="every name is one thing across the whole project; rename one",
                )
            else:
                first[name] = (file, line)

        slots: dict[tuple[str, str, int], tuple[str, int]] = {}
        for region in self._regions():
            script = self._quiet_parse(region)
            if script is None:
                continue
            for node in walk(script):
                if isinstance(node, VariableDeclaration):
                    key = (node.scope, node.type, node.index)
                    line = region.first_line + node.span.start_line - 1
                    if key in slots:
                        self.add(
                            "IR006", f"{node.scope}.{node.type}[{node.index}] is already declared at {slots[key][0]}:{slots[key][1]}",
                            region.file, line, hint="declare each slot once",
                        )
                    else:
                        slots[key] = (region.file, line)

    def _quiet_parse(self, region: _Region) -> Script | None:
        try:
            return parse("\n".join(region.lines))
        except (MegaloLexError, MegaloParseError):
            return None  # reported once, by _parse

    def _kinds_and_owners(self) -> None:
        kinds = self.model.project.kinds
        for declared in self.model.storage:
            annotation = declared.annotation
            if not isinstance(annotation, StorageAnnotation) or annotation.owner is None:
                continue
            line = annotation.span.start_line
            if annotation.scope == "object" and annotation.owner not in kinds:
                self.add(
                    "kind-unknown", f"{annotation.name} is storage for kind {annotation.owner!r}, which no [kinds] table declares",
                    declared.file, line, hint=f"add [kinds.{annotation.owner}] to project.toml or a module.toml",
                )
            elif annotation.scope == "team" and not _TEAM_OWNER.fullmatch(annotation.owner):
                self.add(
                    "team-owner-invalid", f"{annotation.owner!r} isn't a team (team0 to team7)", declared.file, line,
                    hint="team storage is written TEAM.NAME, like team3.tc_mines_alive",
                )

    def _bitfields(self) -> None:
        kinds = self.model.project.kinds
        for declared in self.model.bitfields:
            annotation = declared.annotation
            if not isinstance(annotation, BitfieldAnnotation):
                continue
            line = annotation.span.start_line
            if len(annotation.flags) > _MAX_BITFIELD_FLAGS:
                self.add(
                    "IR011", f"{annotation.name} has {len(annotation.flags)} flags; a number holds {_MAX_BITFIELD_FLAGS} (bit 15 is reserved)",
                    declared.file, line, hint="split it into two bitfields",
                )
            if annotation.owner not in kinds:
                self.add(
                    "kind-unknown", f"{annotation.name} is a bitfield of kind {annotation.owner!r}, which no [kinds] table declares",
                    declared.file, line, hint=f"add [kinds.{annotation.owner}]",
                )

    def _assumptions(self) -> None:
        order = {name: index for index, name in enumerate(self.model.project.order)}
        sites = [
            (name, a, block.file) for name, block in self.model.blocks.items() for a in block.assumes
        ] + [(f.block, a, f.file) for f in self.model.fragments for a in f.assumes]
        for block, annotation, file in sites:
            line = annotation.span.start_line
            if annotation.block not in order:
                self.add(
                    "IR016", f"@assumes names {annotation.block}, but no block has that name", file, line,
                    hint="check the spelling against [blocks].order",
                )
            elif block in order and order[annotation.block] >= order[block]:
                self.add(
                    "IR016", f"{block} assumes {annotation.block} runs first, but the order has {annotation.block} at position "
                    f"{order[annotation.block] + 1} and {block} at {order[block] + 1}",
                    file, line, hint="reorder [blocks].order or drop the assumption",
                )
