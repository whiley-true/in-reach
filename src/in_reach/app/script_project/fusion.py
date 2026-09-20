"""Fusion: adjacent fragments with the same loop, gate and preamble become one trigger (``TO_IMPLEMENT`` §7).

Two fragments that both start ``for each player do`` cost two triggers, and each repeats its preamble. Fused, they are
one ``for each player do`` -- the preamble once, then each fragment's body inside its own guards. That is only the same
program when running A for every player and *then* B for every player does what A-then-B for each player does, which
holds when nothing in the group writes state another member reads on a different iteration. This module decides that.

What is fused, and what is not:

* **Adjacent only.** Fragments are candidates when they are neighbours in a block's resolved order -- predictable
  output, and ``after``/``before`` already control it.
* **Same shape.** Same ``@loop``, the same ``@gate`` and the same ``@preamble`` (or none).
* **``@fusion never``** keeps a fragment on its own; ``@fusion subroutine`` is not implemented and is treated as ``never``
  (with a warning) -- lowering a preamble to an engine subroutine is unverified, see ``next_steps.md``.
* **``@fusion force:<group>``** fuses adjacent fragments of the same group without the legality analysis below (they
  must still share loop, gate and preamble, or it is an error). A forced group the analysis would have declined is
  reported as IR018.
* **Legality.** Each fragment (with its preamble, which every fragment inherits) has the storage it reads and writes,
  found by :func:`analyse`. Two fragments conflict if one writes what the other reads or writes, unless both accesses
  are to the current iteration's own state (``current_player.*`` and friends, outside any nested loop). The analysis is
  conservative: anything it cannot classify declines the merge rather than risk it -- a wrong merge is silent, a
  declined one is only slower, and ``@fusion force`` overrides. A preamble that writes anything but temporaries is
  never fused, since fusing runs it once instead of once per trigger.
* **Hoisting.** A guard every fragment in a fused group shares is tested once, around all of them, provided nothing
  in the group writes what it reads.

Every merge and every refusal is recorded (``link_map.json``'s ``fusion``), the refusals with their reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from in_reach.app.rvt.megalo_ast import (
    MegaloAliasError,
    MegaloLexError,
    MegaloParseError,
    parse,
    render_expr,
    resolve_aliases,
)
from in_reach.app.rvt.megalo_ast.annotations import GuardAnnotation
from in_reach.app.rvt.megalo_ast.nodes import (
    Assignment,
    BinaryOp,
    Call,
    DoBlock,
    ExprStatement,
    ForEach,
    FunctionDeclaration,
    Identifier,
    IfStatement,
    Index,
    IntLiteral,
    Member,
    Script,
    UnaryOp,
)

from .diagnostics import ProjectDiagnostic
from .model import Fragment, PreambleDef

_LOCAL_ROOTS = {"current_player": "player", "current_object": "object", "current_team": "team"}
_POINTER_TYPES = frozenset({"player", "object", "team"})
#: Names that stand for a fixed thing rather than mutable state.
_CONSTANT_ROOTS = frozenset({
    "script_option", "script_widget", "script_traits", "script_stat", "no_player", "no_object", "no_team", "none",
    "everyone", "allies", "enemies", "noone",
})

# A cell: the storage a piece of code touches (``player.number[0]``, ``global.number[1]``, ``game.round_time``), and
# whether it is the current iteration's own.
Cell = tuple[str, bool]


@dataclass
class Access:
    reads: set[Cell] = field(default_factory=set)
    writes: set[Cell] = field(default_factory=set)

    def merge(self, other: Access) -> None:
        self.reads |= other.reads
        self.writes |= other.writes


class Unanalysable(Exception):
    """A fragment's code this module can't parse or resolve; the merge is declined with the reason."""


# -- cells ---------------------------------------------------------------------------------------------


def _chain(expr) -> tuple[str | None, list[tuple[str, str]]]:
    parts: list[tuple[str, str]] = []
    while True:
        if isinstance(expr, Member):
            parts.append(("m", expr.name))
            expr = expr.target
        elif isinstance(expr, Index):
            parts.append(("i", str(expr.index.value) if isinstance(expr.index, IntLiteral) else "?"))
            expr = expr.target
        else:
            break
    parts.reverse()
    return (expr.name if isinstance(expr, Identifier) else None), parts


def _cell(expr, nested: bool) -> Cell | None:
    """The storage ``expr`` names, or ``None`` if it names no state (a constant, a temporary, a literal)."""
    root, parts = _chain(expr)
    if root is None or root in _CONSTANT_ROOTS:
        return None
    if root in _LOCAL_ROOTS:
        base, local = _LOCAL_ROOTS[root], not nested
    elif root == "temporaries":
        base, local = "temporaries", True
    elif root == "team":
        base, local = "team", False
        if parts and parts[0][0] == "i":
            parts = parts[1:]  # which team: not told apart, so two different teams are treated as one cell
    else:
        base, local = root, False

    key = base
    pending: str | None = None  # a pointer-typed slot or property just named: the next member is on what it points at
    for kind, value in parts:
        if kind == "i":
            key += f"[{value}]"
        elif pending is not None:
            base, local, key, pending = pending, False, pending, None
            key += f".{value}"
            if value in _POINTER_TYPES:
                pending = value
        elif value == "biped" and base == "player":
            base, key = "object", "object"  # a player's own biped goes with them
        else:
            key += f".{value}"
            if value in _POINTER_TYPES:
                pending = value
    if key == "temporaries" or (base == "temporaries" and local):
        return None
    return key, local


def _add_reads(expr, nested: bool, out: set[Cell]) -> None:
    if isinstance(expr, (Member, Index)):
        cell = _cell(expr, nested)
        if cell is not None:
            out.add(cell)
        node = expr
        while isinstance(node, (Member, Index)):  # an index that is itself an expression
            if isinstance(node, Index):
                _add_reads(node.index, nested, out)
            node = node.target
    elif isinstance(expr, Identifier):
        cell = _cell(expr, nested)
        if cell is not None:
            out.add(cell)
    elif isinstance(expr, Call):
        target = expr.target
        _add_reads(target.target if isinstance(target, Member) else target, nested, out)
        for argument in expr.args:
            _add_reads(argument, nested, out)
    elif isinstance(expr, BinaryOp):
        _add_reads(expr.left, nested, out)
        _add_reads(expr.right, nested, out)
    elif isinstance(expr, UnaryOp):
        _add_reads(expr.operand, nested, out)


def _walk_statements(statements, nested: bool, access: Access) -> None:
    for statement in statements:
        if isinstance(statement, Assignment):
            written = _cell(statement.target, nested)
            if written is not None:
                access.writes.add(written)
                if statement.op != "=":
                    access.reads.add(written)
            _add_reads(statement.value, nested, access.reads)
        elif isinstance(statement, ExprStatement):
            expr = statement.expr
            if isinstance(expr, Call):
                receiver = expr.target.target if isinstance(expr.target, Member) else expr.target
                acted_on = _cell(receiver, nested) if isinstance(receiver, (Member, Index, Identifier)) else None
                if acted_on is None and isinstance(receiver, Identifier) and receiver.name in ("game", "global"):
                    acted_on = (receiver.name, False)
                if acted_on is not None:
                    access.writes.add(acted_on)
                    access.reads.add(acted_on)
            _add_reads(expr, nested, access.reads)
        elif isinstance(statement, IfStatement):
            _add_reads(statement.condition, nested, access.reads)
            _walk_statements(statement.body, nested, access)
            for clause in statement.altif_clauses:
                _add_reads(clause.condition, nested, access.reads)
                _walk_statements(clause.body, nested, access)
            _walk_statements(statement.alt_body or [], nested, access)
        elif isinstance(statement, DoBlock):
            _walk_statements(statement.body, nested, access)
        elif isinstance(statement, ForEach):
            _walk_statements(statement.body, True, access)  # inside a nested loop nothing is the iteration's own
        elif isinstance(statement, FunctionDeclaration):
            _walk_statements(statement.body, True, access)


def analyse(alias_lines: list[str], conditions: list, code: str) -> Access:
    """Reads and writes of ``code`` and the ``conditions`` (expressions tested before it), with ``alias_lines``
    resolved first so a name means the slot it was allocated."""
    try:
        script = parse("\n".join(alias_lines) + "\n" + code)
        body = list(script.body)
        for condition in conditions:  # a condition is a read, never an action
            body.append(IfStatement(span=condition.span, condition=condition, body=[]))
        resolved = resolve_aliases(Script(body=body))
    except (MegaloLexError, MegaloParseError, MegaloAliasError) as exc:
        raise Unanalysable(str(exc)) from None
    access = Access()
    _walk_statements(resolved.body, False, access)
    return access


# -- conflicts -----------------------------------------------------------------------------------------


def _conflict(a: Access, b: Access) -> str | None:
    """A human reason two fragments can't share a loop, or ``None`` if they can."""
    for written, other, verb in ((a.writes, b, "reads"), (b.writes, a, "reads")):
        for key, local in sorted(written):
            for read_key, read_local in other.reads:
                if read_key == key and not (local and read_local):
                    return f"one writes {key}, which the other {verb}"
    for key, local in sorted(a.writes):
        for other_key, other_local in b.writes:
            if other_key == key and not (local and other_local):
                return f"both write {key}"
    return None


# -- planning -------------------------------------------------------------------------------------------


@dataclass
class Group:
    fragments: list[Fragment]
    hoisted: list[GuardAnnotation] = field(default_factory=list)
    forced: str | None = None


@dataclass
class FusionPlan:
    groups: list[Group] = field(default_factory=list)
    fused: list[dict] = field(default_factory=list)
    declined: list[dict] = field(default_factory=list)
    diagnostics: list[ProjectDiagnostic] = field(default_factory=list)


def _mode(fragment: Fragment) -> tuple[str, str | None]:
    if fragment.fusion is None:
        return "auto", None
    return fragment.fusion.mode, fragment.fusion.group


def _shape(fragment: Fragment) -> tuple:
    return (fragment.loop, render_expr(fragment.gate.condition) if fragment.gate else None, fragment.preamble)


def _shape_difference(a: Fragment, b: Fragment) -> str | None:
    if a.loop != b.loop:
        return f"different loops ({a.loop} and {b.loop})"
    if _shape(a)[1] != _shape(b)[1]:
        return "different gates"
    if a.preamble != b.preamble:
        return f"different preambles ({a.preamble or 'none'} and {b.preamble or 'none'})"
    return None


def _provided_aliases(preamble: PreambleDef | None) -> list[str]:
    """``alias name = temporaries.type[i]`` for what ``preamble`` provides: names that are scratch, never shared state."""
    if preamble is None:
        return []
    next_index: dict[str, int] = {}
    lines = []
    for variable in preamble.provides:
        index = next_index.get(variable.type, 0)
        next_index[variable.type] = index + 1
        lines.append(f"alias {variable.name} = temporaries.{variable.type}[{index}]")
    return lines


def plan_fusion(
    block: str, fragments: list[Fragment], preambles: dict[str, PreambleDef], alias_lines: list[str], code_of
) -> FusionPlan:
    """Groups ``block``'s ``fragments`` (already in order). ``code_of(lines, first_line, file)`` turns a fragment's or
    preamble's source lines into the code that will be emitted (annotations dropped)."""
    plan = FusionPlan()
    accesses: dict[str, Access | Unanalysable] = {}

    def access_of(fragment: Fragment) -> Access:
        cached = accesses.get(fragment.id)
        if isinstance(cached, Unanalysable):
            raise cached
        if cached is not None:
            return cached
        try:
            preamble = preambles.get(fragment.preamble) if fragment.preamble else None
            result = Access()
            aliases = alias_lines + _provided_aliases(preamble)
            if preamble is not None:
                result.merge(analyse(aliases, [], code_of(preamble.body, preamble.body_line, preamble.file)))
            conditions = [g.condition for g in fragment.guards] + ([fragment.gate.condition] if fragment.gate else [])
            result.merge(analyse(aliases, conditions, code_of(fragment.body, fragment.body_line, fragment.file)))
        except Unanalysable as exc:
            accesses[fragment.id] = exc
            raise
        accesses[fragment.id] = result
        return result

    def preamble_effects(fragment: Fragment) -> str | None:
        """Why the fragment's preamble can't run once instead of once per trigger, if it can't."""
        preamble = preambles.get(fragment.preamble) if fragment.preamble else None
        if preamble is None:
            return None
        try:
            only = analyse(alias_lines + _provided_aliases(preamble), [], code_of(preamble.body, preamble.body_line, preamble.file))
        except Unanalysable as exc:
            return f"preamble {preamble.name} couldn't be analysed ({exc})"
        changed = sorted(key for key, _ in only.writes)
        return f"preamble {preamble.name} writes {', '.join(changed)}" if changed else None

    def decline(current: list[Fragment], candidate: Fragment, reason: str) -> None:
        plan.declined.append({"block": block, "fragments": [current[-1].id, candidate.id], "reason": reason})

    def can_join(current: Group, candidate: Fragment) -> str | None:
        """``None`` if ``candidate`` may join ``current``, otherwise why not."""
        last = current.fragments[-1]
        mode, force_group = _mode(candidate)
        last_mode, last_group = _mode(last)
        if "never" in (mode, last_mode):
            return "@fusion never"
        if "subroutine" in (mode, last_mode):
            return "@fusion subroutine isn't implemented, so the fragment is kept on its own"
        if (mode == "force" or last_mode == "force") and (mode != last_mode or force_group != last_group):
            return "not in the same @fusion force group"
        difference = _shape_difference(last, candidate)
        if difference:
            return difference
        if current.forced is not None:
            return None
        effects = preamble_effects(candidate)
        if effects:
            return effects
        try:
            candidate_access = access_of(candidate)
            for member in current.fragments:
                reason = _conflict(access_of(member), candidate_access)
                if reason:
                    return f"{member.id} and {candidate.id}: {reason}"
        except Unanalysable as exc:
            return f"the code couldn't be analysed ({exc})"
        return None

    for fragment in fragments:
        mode, force_group = _mode(fragment)
        if mode == "subroutine":
            plan.diagnostics.append(
                ProjectDiagnostic(
                    severity="warning", code="fusion-subroutine", file=fragment.file, line=fragment.fusion.span.start_line,
                    message=f"@fusion subroutine on {fragment.id} isn't implemented; it is kept as its own trigger",
                )
            )
        current = plan.groups[-1] if plan.groups else None
        if current is not None:
            reason = can_join(current, fragment)
            if reason is None:
                current.fragments.append(fragment)
                continue
            if mode == "force" and _mode(current.fragments[-1]) == ("force", force_group):
                plan.diagnostics.append(
                    ProjectDiagnostic(
                        severity="error", code="fusion-force-incompatible", file=fragment.file, line=fragment.fusion.span.start_line,
                        message=f"{fragment.id} can't be fused into force:{force_group} with {current.fragments[-1].id}: {reason}",
                    )
                )
            decline(current.fragments, fragment, reason)
        plan.groups.append(Group([fragment], forced=force_group if mode == "force" else None))

    for group in plan.groups:
        if len(group.fragments) < 2:
            continue
        _hoist(group, access_of, alias_lines)
        if group.forced is not None:
            _check_forced(group, access_of, plan)
        first = group.fragments[0]
        preamble = preambles.get(first.preamble) if first.preamble else None
        entry = {
            "trigger": block,
            "fragments": [f.id for f in group.fragments],
            "loop": first.loop,
            "saved": {"triggers": len(group.fragments) - 1},
        }
        if preamble is not None:
            entry["preamble"] = preamble.name
            entry["saved"]["preambles"] = len(group.fragments) - 1
        if group.forced is not None:
            entry["forced"] = group.forced
        if group.hoisted:
            entry["hoisted_guards"] = [render_expr(g.condition) for g in group.hoisted]
        plan.fused.append(entry)
    return plan


def _hoist(group: Group, access_of, alias_lines: list[str]) -> None:
    """Guards every fragment shares, tested once around them all -- unless something in the group writes what one
    reads (a fragment's own write could change a later fragment's answer)."""
    if len(group.fragments) < 2:
        return
    common = [render_expr(g.condition) for g in group.fragments[0].guards]
    for fragment in group.fragments[1:]:
        have = {render_expr(g.condition) for g in fragment.guards}
        common = [text for text in common if text in have]
    if not common:
        return
    try:
        written = {key for fragment in group.fragments for key, _ in access_of(fragment).writes}
    except Unanalysable:
        return
    for guard in group.fragments[0].guards:
        text = render_expr(guard.condition)
        if text not in common or any(render_expr(h.condition) == text for h in group.hoisted):
            continue
        try:
            reads = {key for key, _ in analyse(alias_lines, [guard.condition], "").reads}
        except Unanalysable:
            continue
        if reads & written:
            continue
        group.hoisted.append(guard)


def _check_forced(group: Group, access_of, plan: FusionPlan) -> None:
    """IR018: a forced group the analysis would have declined."""
    try:
        for index, member in enumerate(group.fragments):
            for other in group.fragments[index + 1:]:
                reason = _conflict(access_of(member), access_of(other))
                if reason:
                    plan.diagnostics.append(
                        ProjectDiagnostic(
                            severity="warning", code="IR018", file=other.file, line=other.line,
                            message=f"force:{group.forced} fuses {member.id} and {other.id}, but {reason}",
                            hint="fusing them changes the order state is read and written across iterations",
                        )
                    )
                    return
    except Unanalysable:
        return
