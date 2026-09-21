"""Compile-time ``alias`` resolution -- an AST -> AST pass that substitutes every use of an
``alias <name> = <value>`` with ``<value>`` itself and drops the declarations, so anything downstream
(:mod:`in_reach.app.rvt.megalo_compiler`, and any future linker/lowering pass) only ever sees
concrete expressions.

Why this is its own pass rather than a compiler feature: ``alias`` is pure naming. It never reaches
the engine (``decompile_script()`` shows the aliased expression, never the alias name), so there's
nothing for a compiler to *do* with one beyond looking it up -- and a compiler that didn't know that
used to fall back to the native ``compile_script()`` for any script using one, which is the very
non-idempotent inlining behaviour :mod:`~in_reach.app.rvt.megalo_compiler` exists to avoid. Doing it
here, on the tree, also means a future linker can allocate storage slots and emit plain ``alias``
declarations without ever forcing that fallback.

Semantics, every one confirmed against the native ``compile_script()`` (not assumed):

- Sequential, block-scoped: an alias is visible from its declaration to the end of its own
  enclosing block (``if``/``altif``/``alt``/``do``/``for each``/``function``/``on`` body, or the
  top level), including inside nested blocks and later ``function`` bodies. One declared inside an
  ``if`` body is *not* visible after its ``end``.
- An inner alias shadows an outer one of the same name; redeclaring a name in the same scope simply
  rebinds it (last declaration wins, no error).
- An alias's own value is resolved against the aliases already in scope when it's declared, so an
  alias of an alias works (natively only when declared inside a block, not at the top level -- this
  pass accepts both, see below).
- Names the engine already owns (see :data:`RESERVED_NAMES`) can't be aliased.

Deliberately more permissive than native in two known ways, since native is stricter for reasons
that look like its own quirks rather than language rules: it rejects an alias as the very first
token of an ``if`` condition (``if n == 1 then`` fails, ``if global.number[1] == n then`` works),
and an alias-of-an-alias at the top level. A script relying on either compiles here but not when
pasted into RVT itself -- if that parity ever matters, tighten it here, in one place.
"""
from __future__ import annotations

from .nodes import (
    AliasDeclaration, Assignment, BinaryOp, Call, DoBlock, ElseIfClause, EventTrigger, Expression,
    ExprStatement, ForEach, FunctionDeclaration, Identifier, IfStatement, Index, Member, Script,
    SourceSpan, Statement, UnaryOp, VariableDeclaration,
)

#: Names native rejects as an alias name ("already in use by the ... value" / "Typename ... cannot
#: be used as the name of an alias"). Not exhaustive -- there's no table of every engine-owned name
#: to check against -- so a name outside this set that native would still reject compiles here; the
#: aim is catching the common collisions with a clear error, not mirroring native's whole namespace.
RESERVED_NAMES = frozenset({
    "global", "player", "object", "team", "temporaries", "number", "timer",
    "current_player", "current_object", "current_team",
    "no_player", "no_object", "no_team", "none",
    "game", "script_option", "script_widget", "script_traits", "script_stat",
})

_Scope = dict[str, Expression]


class MegaloAliasError(ValueError):
    """An ``alias`` declaration this pass can't accept (a reserved name). The message carries the
    1-based source line. Distinct from :class:`~in_reach.app.rvt.megalo_ast.parser.MegaloParseError`
    -- the text parsed fine; it's the *meaning* that's wrong."""


def resolve_aliases(script: Script) -> Script:
    """Returns a copy of ``script`` with every alias substituted and every
    :class:`~in_reach.app.rvt.megalo_ast.nodes.AliasDeclaration` removed. ``script`` itself is
    never mutated. A script with no aliases comes back structurally identical.

    Raises:
        MegaloAliasError: If an alias is declared under a name in :data:`RESERVED_NAMES`.
    """
    return script.model_copy(update={"body": _resolve_block(script.body, {})})


def _resolve_block(statements: list[Statement], enclosing: _Scope) -> list[Statement]:
    scope = dict(enclosing)  # a new block: its own declarations must not leak back out
    out: list[Statement] = []
    for stmt in statements:
        out.extend(_resolve_statement(stmt, scope))
    return out


def _resolve_statement(stmt: Statement, scope: _Scope) -> list[Statement]:
    if isinstance(stmt, AliasDeclaration):
        if stmt.name in RESERVED_NAMES:
            raise MegaloAliasError(f"line {stmt.span.start_line}: {stmt.name!r} can't be used as an alias name")
        scope[stmt.name] = _resolve_expr(stmt.value, scope)
        return []
    if isinstance(stmt, VariableDeclaration):
        value = _resolve_expr(stmt.value, scope) if stmt.value is not None else None
        return [stmt.model_copy(update={"value": value})]
    if isinstance(stmt, Assignment):
        return [stmt.model_copy(update={
            "target": _resolve_expr(stmt.target, scope), "value": _resolve_expr(stmt.value, scope),
        })]
    if isinstance(stmt, ExprStatement):
        return [stmt.model_copy(update={"expr": _resolve_expr(stmt.expr, scope)})]
    if isinstance(stmt, IfStatement):
        return [stmt.model_copy(update={
            "condition": _resolve_expr(stmt.condition, scope),
            "body": _resolve_block(stmt.body, scope),
            "altif_clauses": [
                ElseIfClause(
                    span=clause.span,
                    condition=_resolve_expr(clause.condition, scope),
                    body=_resolve_block(clause.body, scope),
                )
                for clause in stmt.altif_clauses
            ],
            "alt_body": None if stmt.alt_body is None else _resolve_block(stmt.alt_body, scope),
        })]
    if isinstance(stmt, DoBlock):
        return [stmt.model_copy(update={"body": _resolve_block(stmt.body, scope)})]
    if isinstance(stmt, ForEach):
        # `label` is never touched: the grammar only accepts a literal int/string there, so an
        # alias can't appear in it.
        return [stmt.model_copy(update={"body": _resolve_block(stmt.body, scope)})]
    if isinstance(stmt, FunctionDeclaration):
        return [stmt.model_copy(update={"body": _resolve_block(stmt.body, scope)})]
    if isinstance(stmt, EventTrigger):
        return [stmt.model_copy(update={"body": _resolve_event_body(stmt.body, scope)})]
    return [stmt]


def _resolve_event_body(body: Statement, scope: _Scope) -> Statement:
    # `on <event>: <statement>` takes exactly one statement, but a lone `alias` there resolves to
    # nothing at all -- an empty `do` block keeps the node's shape valid rather than dropping it.
    resolved = _resolve_block([body], scope)
    if len(resolved) == 1:
        return resolved[0]
    return DoBlock(span=body.span, body=resolved)


def _resolve_expr(expr: Expression, scope: _Scope) -> Expression:
    if isinstance(expr, Identifier):
        value = scope.get(expr.name)
        return expr if value is None else _at(value, expr.span)
    if isinstance(expr, Member):
        target = _resolve_expr(expr.target, scope)
        nested = _nested_variable(scope.get(expr.name))
        if nested is not None:
            # `alias p_n = player.number[0]` used as `current_player.p_n`: native reads that as
            # `current_player.number[0]`, so the alias names a variable *of whatever it is used on*.
            type_name, index = nested
            member = Member(target=target, name=type_name, span=expr.span)
            return Index(target=member, index=_at(index, expr.span), span=expr.span)
        return expr.model_copy(update={"target": target})
    if isinstance(expr, Index):
        return expr.model_copy(update={
            "target": _resolve_expr(expr.target, scope), "index": _resolve_expr(expr.index, scope),
        })
    if isinstance(expr, Call):
        # A bare `name(...)` callee is a function/action name, which lives in its own namespace --
        # never an alias, even if one happens to share its spelling.
        target = expr.target if isinstance(expr.target, Identifier) else _resolve_expr(expr.target, scope)
        return expr.model_copy(update={"target": target, "args": [_resolve_expr(a, scope) for a in expr.args]})
    if isinstance(expr, UnaryOp):
        return expr.model_copy(update={"operand": _resolve_expr(expr.operand, scope)})
    if isinstance(expr, BinaryOp):
        return expr.model_copy(update={
            "left": _resolve_expr(expr.left, scope), "right": _resolve_expr(expr.right, scope),
        })
    return expr  # int/percent/string literals


#: Scopes whose variables belong to something (a player, an object, a team) -- so an alias for one is used as
#: ``owner.alias``. ``global`` and ``temporaries`` stand alone and are substituted like any other alias.
_OWNED_SCOPES = frozenset({"player", "object", "team"})


def _nested_variable(value: Expression | None) -> tuple[str, Expression] | None:
    """``("number", <0>)`` for an alias value shaped ``player.number[0]`` (or ``object.``/``team.``), else ``None``."""
    if (
        isinstance(value, Index)
        and isinstance(value.target, Member)
        and isinstance(value.target.target, Identifier)
        and value.target.target.name in _OWNED_SCOPES
    ):
        return value.target.name, value.index
    return None


def _at(expr: Expression, span: SourceSpan) -> Expression:
    """A copy of ``expr`` (an alias's already-resolved value) re-stamped with the *use site's*
    ``span`` throughout, so a compiler error about a substituted expression points at the line the
    user actually wrote it on, not at the ``alias`` declaration."""
    update: dict[str, object] = {"span": span}
    if isinstance(expr, Member):
        update["target"] = _at(expr.target, span)
    elif isinstance(expr, Index):
        update["target"] = _at(expr.target, span)
        update["index"] = _at(expr.index, span)
    elif isinstance(expr, Call):
        update["target"] = _at(expr.target, span)
        update["args"] = [_at(a, span) for a in expr.args]
    elif isinstance(expr, UnaryOp):
        update["operand"] = _at(expr.operand, span)
    elif isinstance(expr, BinaryOp):
        update["left"] = _at(expr.left, span)
        update["right"] = _at(expr.right, span)
    return expr.model_copy(update=update)
