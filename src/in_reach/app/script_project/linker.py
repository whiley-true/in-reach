"""The linker: a loaded, checked project in, ``build/Compiled.txt`` and friends out (``TO_IMPLEMENT`` §6).

:func:`link` does, in order: load the project; build its semantic model; lint it; allocate storage; plan the
engine resources; assemble the text; and (if asked) write ``build/Compiled.txt``, ``build/declarations.mgl``,
``build/link_map.json`` and any change to ``settings/script_settings.json``. Nothing is written unless everything
before it succeeded, so a broken project never leaves half a build behind.

What ``Compiled.txt`` contains, in order:

1. a header (project, profile, flags -- no timestamp, so an unchanged project rebuilds to identical bytes);
2. ``declare`` lines for the slots that were asked to carry a priority or a default;
3. ``alias`` lines: every storage name to its slot, every bitfield flag to its value, every resource to its table
   entry (``alias t_freeze = script_traits[0]``);
4. each block, in :attr:`ScriptProject.order`: a block file's code as written, then each fragment as a trigger.

A fragment becomes ``for each <loop> do ... end`` (inside an ``if <gate> then`` if it has a ``@gate``): the provided
temporaries as aliases, its preamble with the fragment's body -- inside its ``@guard`` conditions -- inserted at the
preamble's ``@guard-end``. Labels are substituted (``with label L_hill`` becomes ``with label "hill"``); annotation
lines are dropped from the output (they're metadata; ordinary comments stay).

``link_map.json`` records where everything went, so a later link keeps what it decided and so the budget panel and
the Problems panel have something to read: each name's slot and owner, each resource's index and the digest of what
was written, pool usage, the block order, and ``source_lines`` -- which lines of ``Compiled.txt`` came verbatim
from which source lines, to turn a compiler error back into a place in your files.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from in_reach.app import new_project
from in_reach.app.rvt import settings_io
from in_reach.app.rvt.megalo_ast import MegaloLexError, MegaloParseError, parse, render_expr, walk
from in_reach.app.rvt.megalo_ast.nodes import Index, VariableDeclaration
from in_reach.app.rvt.megalo_compiler import _MAX_ACTIONS, _MAX_CONDITIONS, _SCRIPT_TABLES
from in_reach.app.rvt.models.script_settings import ScriptSettings
from in_reach.app.rvt.variable_declarations import UnsupportedDeclaration, _variable_reference

from .allocation import POOL_SIZES, Allocation, allocate
from .diagnostics import ProjectDiagnostic
from .fusion import plan_fusion
from .lint import lint
from .model import Fragment, PreambleDef, SemanticModel, build_model
from .project import ScriptProject, load_project
from .resources import ResourcePlan, plan_resources

COMPILED_FILENAME = "Compiled.txt"
DECLARATIONS_FILENAME = "declarations.mgl"
LINK_MAP_FILENAME = "link_map.json"

_ANNOTATION_LINE = re.compile(r"^\s*--\s*@[A-Za-z]")
_INDENT = "   "
_SCOPE_ORDER = {"global": 0, "player": 1, "object": 2, "team": 3}
_TYPE_ORDER = {"number": 0, "object": 1, "player": 2, "team": 3, "timer": 4}
_TEMPORARY_CAPS = POOL_SIZES["temporaries"]
#: What the engine allows in a whole script (Megalo::Limits). Only the built variant knows how many it has, so these
#: are recorded after the compile (:func:`record_counters`), not by the link.
COUNTER_CAPS = {"triggers": 320, "conditions": _MAX_CONDITIONS, "actions": _MAX_ACTIONS}
_NEAR_CAP = 0.9


@dataclass
class LinkResult:
    ok: bool
    diagnostics: list[ProjectDiagnostic] = field(default_factory=list)
    compiled: str = ""
    declarations: str = ""
    link_map: dict = field(default_factory=dict)
    settings_changed: bool = False
    written: list[Path] = field(default_factory=list)
    project: ScriptProject | None = None  # what was linked, for a caller that wants its modules and blocks

    @property
    def errors(self) -> list[ProjectDiagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]


# -- assembling text ------------------------------------------------------------------------------------


class _Text:
    """Output lines, remembering which came verbatim from a source line."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.origins: list[tuple[str, int] | None] = []

    def add(self, line: str = "", origin: tuple[str, int] | None = None) -> None:
        self.lines.append(line)
        self.origins.append(origin)

    def blank(self) -> None:
        if self.lines and self.lines[-1] != "":
            self.add("")

    def source_lines(self) -> list[dict]:
        """Runs of consecutive output lines that came from consecutive lines of one file."""
        runs: list[dict] = []
        for number, origin in enumerate(self.origins, start=1):
            if origin is None:
                continue
            file, line = origin
            last = runs[-1] if runs else None
            if last and last["file"] == file and last["compiled"] + last["count"] == number and last["source"] + last["count"] == line:
                last["count"] += 1
            else:
                runs.append({"compiled": number, "file": file, "source": line, "count": 1})
        return runs


def _is_annotation(line: str) -> bool:
    return bool(_ANNOTATION_LINE.match(line))


def _code_lines(lines: list[str], first_line: int, file: str) -> list[tuple[str, tuple[str, int]]]:
    """``lines`` (starting at file line ``first_line``) without annotation lines, trailing blanks or a common
    indent, each with where it came from."""
    kept = [(line, (file, first_line + index)) for index, line in enumerate(lines) if not _is_annotation(line)]
    while kept and not kept[-1][0].strip():
        kept.pop()
    while kept and not kept[0][0].strip():
        kept.pop(0)
    if not kept:
        return []
    indent = min((len(l) - len(l.lstrip()) for l, _ in kept if l.strip()), default=0)
    return [(l[indent:] if l.strip() else "", origin) for l, origin in kept]


def _code_text(lines: list[str], first_line: int, file: str) -> str:
    """The code ``lines`` will become in the built script (annotations dropped), for analysis."""
    return "\n".join(line for line, _ in _code_lines(lines, first_line, file))


def _substitute_labels(line: str, labels: dict[str, str]) -> str:
    for name, text in labels.items():
        line = re.sub(rf"(?<=with label ){re.escape(name)}\b", json.dumps(text), line)
    return line


@dataclass
class _Trigger:
    """One emitted trigger: fragments sharing a loop (one, until fusion joins compatible neighbours)."""

    block: str
    fragments: list[Fragment]
    hoisted: list = field(default_factory=list)  # guards every fragment shares, tested once around them all
    temporaries: dict[str, int] = field(default_factory=dict)


def _emit_trigger(
    text: _Text, trigger: _Trigger, preamble: PreambleDef | None, labels: dict[str, str], problems: list[ProjectDiagnostic]
) -> None:
    first = trigger.fragments[0]
    ids = ", ".join(f.id for f in trigger.fragments)
    fused = f" (fused: {ids}" + (f"; preamble {preamble.name})" if preamble else ")") if len(trigger.fragments) > 1 else ""
    text.add(f"-- {first.block}.{first.name}{fused}" if len(trigger.fragments) == 1 else f"-- {first.block}{fused}")

    depth = 0
    if first.gate is not None:
        text.add(f"if {render_expr(first.gate.condition)} then")
        depth = 1
    pad = _INDENT * depth
    text.add(f"{pad}for each {first.loop} do")
    inner = pad + _INDENT

    if preamble is not None:
        for variable in preamble.provides:
            index = trigger.temporaries.get(variable.type, 0)
            if index >= _TEMPORARY_CAPS.get(variable.type, 0):
                problems.append(
                    ProjectDiagnostic(
                        severity="error", code="IR004",
                        message=f"trigger {first.block} needs more than {_TEMPORARY_CAPS.get(variable.type, 0)} temporary {variable.type}s "
                        f"({variable.name} from preamble {preamble.name})",
                        file=preamble.file, line=preamble.line,
                    )
                )
                continue
            trigger.temporaries[variable.type] = index + 1
            text.add(f"{inner}alias {variable.name} = temporaries.{variable.type}[{index}]")

    part_one, part_two, extra_indent = _split_preamble(preamble)
    for line, origin in part_one:
        text.add(_indent(_substitute_labels(line, labels), inner), origin)

    body_indent = inner + " " * extra_indent
    hoisted = [render_expr(g.condition) for g in trigger.hoisted]
    if hoisted:
        text.add(f"{body_indent}if {' and '.join(hoisted)} then")
        body_indent += _INDENT
    for fragment in trigger.fragments:
        if len(trigger.fragments) > 1:
            text.add(f"{body_indent}-- {fragment.id}")
        guard = " and ".join(text_ for text_ in (render_expr(g.condition) for g in fragment.guards) if text_ not in hoisted)
        wrapped = bool(guard)
        if wrapped:
            text.add(f"{body_indent}if {guard} then")
        for line, origin in _code_lines(fragment.body, fragment.body_line, fragment.file):
            text.add(_indent(_substitute_labels(line, labels), body_indent + (_INDENT if wrapped else "")), origin)
        if wrapped:
            text.add(f"{body_indent}end")
    if hoisted:
        body_indent = body_indent[: -len(_INDENT)]
        text.add(f"{body_indent}end")

    for line, origin in part_two:
        text.add(_indent(_substitute_labels(line, labels), inner), origin)
    text.add(f"{pad}end")
    if depth:
        text.add("end")


def _indent(line: str, pad: str) -> str:
    return pad + line if line.strip() else ""


def _split_preamble(preamble: PreambleDef | None) -> tuple[list, list, int]:
    """The preamble's code before and after its ``@guard-end`` (each line with its origin), and how far in the
    marker was indented relative to the rest -- which is how far in the fragments' code goes."""
    if preamble is None:
        return [], [], 0
    lines = preamble.body
    marker = preamble.guard_index
    all_code = [(l, i) for i, l in enumerate(lines) if l.strip() and not _is_annotation(l)]
    indent = min((len(l) - len(l.lstrip()) for l, _ in all_code), default=0)
    extra = max(0, len(lines[marker]) - len(lines[marker].lstrip()) - indent) if marker is not None else 0
    before = lines if marker is None else lines[:marker]
    after = [] if marker is None else lines[marker + 1:]
    return (
        _code_lines(before, preamble.body_line, preamble.file),
        _code_lines(after, preamble.body_line + (marker + 1 if marker is not None else 0), preamble.file),
        extra,
    )


# -- hand-written slots ---------------------------------------------------------------------------------


def _hand_used_slots(model: SemanticModel) -> set[tuple[str, str, int]]:
    """Every slot the hand-written code names (``global.number[3]``, ``current_player.timer[0]``, a ``declare``), so
    allocation leaves them alone."""
    found: set[tuple[str, str, int]] = set()
    regions = [block.lines for block in model.blocks.values()]
    regions += [f.body for f in model.fragments] + [p.body for p in model.preambles.values()]
    for lines in regions:
        try:
            script = parse("\n".join(lines))
        except (MegaloLexError, MegaloParseError):
            continue
        for node in walk(script):
            if isinstance(node, VariableDeclaration):
                found.add((node.scope, node.type, node.index))
            elif isinstance(node, Index):
                try:
                    reference = _variable_reference(node)
                except UnsupportedDeclaration:
                    continue
                if reference is not None:
                    found.add(reference)
    return found


# -- the link -------------------------------------------------------------------------------------------


def link(folder: Path, *, write: bool = True) -> LinkResult:
    """Links ``folder``'s script project. See the module docstring; with ``write=False`` nothing is touched."""
    project = load_project(folder)
    result = LinkResult(ok=False, diagnostics=list(project.diagnostics), project=project)
    if project.errors:
        return result

    model = build_model(project)
    result.diagnostics += model.diagnostics + lint(model)
    if result.errors:
        return result

    manifest = project.manifest
    allocation = allocate(model.storage, model.bitfields, manifest.pins, _hand_used_slots(model))
    result.diagnostics += allocation.diagnostics

    settings_path = folder / new_project.SETTINGS_DIRNAME / "script_settings.json"
    current = _load_settings(settings_path, result)
    previous_map = read_link_map(folder)
    plan = plan_resources(model.resources, current, _previous_resources(previous_map))
    result.diagnostics += plan.diagnostics
    if result.errors:
        return result

    text, declarations, triggers, fusion = _assemble(project, model, allocation, plan, result)
    if result.errors:
        return result

    result.compiled = text.rendered
    result.declarations = declarations
    result.link_map = _link_map(project, allocation, plan, triggers, fusion, text)
    counters = previous_map.get("budget", {}).get("counters") if isinstance(previous_map.get("budget"), dict) else None
    if counters:  # measured on the built variant by the last compile (record_counters); a relink doesn't discard it
        result.link_map["budget"]["counters"] = counters
    result.settings_changed = plan.changed
    result.ok = True
    if write:
        _write(folder, result, plan)
    return result


def _load_settings(path: Path, result: LinkResult) -> ScriptSettings:
    if not path.is_file():
        return ScriptSettings()
    try:
        return settings_io._load_script_settings_strict(path)
    except ValueError as exc:  # never guess: overwriting a settings file we couldn't read would lose it
        result.diagnostics.append(
            ProjectDiagnostic(severity="error", code="settings-invalid", message=str(exc), file="../settings/script_settings.json")
        )
        return ScriptSettings()


def read_link_map(folder: Path) -> dict:
    """``build/link_map.json`` as the last link wrote it (with the counters the last build measured), or ``{}``."""
    try:
        data = json.loads((folder / new_project.BUILD_DIRNAME / LINK_MAP_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _previous_resources(previous: dict) -> dict[str, dict]:
    resources = previous.get("resources", {})
    return resources if isinstance(resources, dict) else {}


class _Rendered(_Text):
    @property
    def rendered(self) -> str:
        return "\n".join(self.lines).rstrip("\n") + "\n"


def _assemble(
    project: ScriptProject, model: SemanticModel, allocation: Allocation, plan: ResourcePlan, result: LinkResult
) -> tuple[_Rendered, str, list[_Trigger], dict]:
    text = _Rendered()
    profile = project.profile
    flags = ",".join(sorted(profile.flags)) if profile else ""
    name = (project.manifest.project.name if project.manifest else None) or project.folder.name
    text.add(f"-- in-reach build: {name}  profile={profile.name if profile else 'none'}  flags={flags or '-'}")
    text.add("-- Auto-generated and non-editable. Edit script/ and rebuild.")
    text.blank()

    declaration_lines: list[str] = []
    for key in sorted(allocation.declarations, key=lambda k: (_SCOPE_ORDER[k[0]], _TYPE_ORDER[k[1]], k[2])):
        d = allocation.declarations[key]
        line = f"declare {key[0]}.{key[1]}[{key[2]}]"
        if d.priority:
            line += f" with network priority {d.priority}"
        if d.default is not None:
            line += f" = {d.default}"
        declaration_lines.append(line)
    alias_lines: list[str] = []
    for name_, slot in allocation.slots.items():
        alias_lines.append(f"alias {name_} = {slot.concrete}")
        for flag, value in allocation.flags.get(name_, []):
            alias_lines.append(f"alias {flag} = {value}")
    for name_, info in plan.resources.items():
        alias_lines.append(f"alias {name_} = {info.alias_value}")

    for line in declaration_lines:
        text.add(line)
    text.blank()
    for line in alias_lines:
        text.add(line)
    declarations = "\n".join([*declaration_lines, "", *alias_lines]).strip("\n") + "\n"

    triggers: list[_Trigger] = []
    fusion_report: dict[str, list] = {"groups": [], "declined": []}
    for block in project.order:
        text.blank()
        loaded = project.blocks.get(block)
        code = model.blocks.get(block)
        if code is not None:  # a block only fragments contribute to needs no heading: each trigger names it
            where = f" ({loaded.file.path})" if loaded is not None and loaded.file is not None else ""
            text.add(f"-- {block}{where}")
            for line, origin in _code_lines(code.lines, 1, code.file):
                text.add(_substitute_labels(line, plan.labels), origin)
        fusion = plan_fusion(block, model.fragments_of(block), model.preambles, alias_lines, _code_text)
        result.diagnostics += fusion.diagnostics
        fusion_report["groups"] += fusion.fused
        fusion_report["declined"] += fusion.declined
        for group in fusion.groups:
            text.blank()
            first = group.fragments[0]
            trigger = _Trigger(block=block, fragments=group.fragments, hoisted=group.hoisted)
            triggers.append(trigger)
            preamble = model.preambles.get(first.preamble) if first.preamble else None
            _emit_trigger(text, trigger, preamble, plan.labels, result.diagnostics)
    return text, declarations, triggers, fusion_report


def _link_map(
    project: ScriptProject, allocation: Allocation, plan: ResourcePlan, triggers: list[_Trigger], fusion: dict, text: _Text
) -> dict:
    profile = project.profile
    budget: dict[str, dict] = {}
    for (scope, type_), used in sorted(allocation.used.items(), key=lambda kv: (_SCOPE_ORDER[kv[0][0]], _TYPE_ORDER[kv[0][1]])):
        budget[f"{scope}.{type_}"] = {"cap": POOL_SIZES[scope][type_], "used": used}
    for kind, (attr, _, table) in {"traits": ("scripted_player_traits", "", "script_traits"), "options": ("scripted_options", "", "script_option"), "widgets": ("scripted_hud_widgets", "", "script_widget")}.items():
        used = len(getattr(plan.settings, attr))
        if used:
            budget[kind] = {"cap": _SCRIPT_TABLES[table][2], "used": used}
    if plan.labels:
        budget["labels"] = {"cap": 16, "used": len(set(plan.labels.values()))}

    return {
        "profile": profile.name if profile else None,
        "flags": sorted(profile.flags) if profile else [],
        "storage": {
            name: {
                "slot": slot.concrete, "owner": allocation.owners[name],
                **({"kind": slot.owner} if slot.owner else {}),
            }
            for name, slot in allocation.slots.items()
        },
        "resources": {name: _resource_entry(info) for name, info in plan.resources.items()},
        "labels": dict(plan.labels),
        "budget": budget,
        "order": list(project.order),
        "temporaries": [
            {"block": t.block, "fragments": [f.id for f in t.fragments], **t.temporaries} for t in triggers if t.temporaries
        ],
        "fusion": fusion,
        "source_lines": text.source_lines(),
    }


def _resource_entry(info) -> dict:
    entry = {"kind": info.kind, "index": info.index, "owner": info.owner, "digest": info.digest}
    text = {key: value for key, value in (("name", info.label), ("desc", info.note)) if value}
    if info.values:
        text["values"] = list(info.values)
    if text:
        entry["text"] = text  # what the compile writes into the strings table for this entry
    return entry


def _write(folder: Path, result: LinkResult, plan: ResourcePlan) -> None:
    build = folder / new_project.BUILD_DIRNAME
    build.mkdir(parents=True, exist_ok=True)
    outputs = {
        build / COMPILED_FILENAME: result.compiled,
        build / DECLARATIONS_FILENAME: result.declarations,
        build / LINK_MAP_FILENAME: json.dumps(result.link_map, indent=2) + "\n",
    }
    for path, content in outputs.items():
        if not path.is_file() or path.read_text(encoding="utf-8") != content:  # untouched if unchanged: no VCS churn
            path.write_text(content, encoding="utf-8")
            result.written.append(path)
    if plan.changed:
        target = folder / new_project.SETTINGS_DIRNAME / "script_settings.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        schema = folder / new_project.SCHEMA_DIRNAME / "script_settings.schema.json"
        settings_io.dump_script_settings(plan.settings, target, schema if schema.is_file() else None)
        result.written.append(target)


def record_counters(folder: Path, counts: dict) -> list[ProjectDiagnostic]:
    """Adds the built variant's trigger/condition/action/string counts to ``build/link_map.json`` (``budget.counters``)
    and returns an IR012 warning for each that is within 10% of its engine cap. ``counts`` is the native
    ``get_full_size_data().counts``. Does nothing (and returns nothing) if there is no link map to add them to."""
    path = folder / new_project.BUILD_DIRNAME / LINK_MAP_FILENAME
    try:
        link_map = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    counters = {name: {"cap": cap, "used": counts[name]} for name, cap in COUNTER_CAPS.items() if name in counts}
    if "strings" in counts:
        counters["strings"] = {"used": counts["strings"]}
    link_map.setdefault("budget", {})["counters"] = counters
    text = json.dumps(link_map, indent=2) + "\n"
    if path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
    warnings = []
    for name, entry in counters.items():
        cap = entry.get("cap")
        if cap and entry["used"] >= cap * _NEAR_CAP:
            warnings.append(
                ProjectDiagnostic(
                    severity="warning", code="IR012",
                    message=f"the script uses {entry['used']} of the {cap} {name} a variant can hold ({entry['used'] * 100 // cap}%)",
                    file="../build/link_map.json",
                )
            )
    return warnings
