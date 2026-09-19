"""``Script`` AST -> Megalo script text, the reverse of ``parser.py``. Renders canonical RVT-
decompiler-style formatting (3-space indent, ``"\\r\\n"`` line endings -- matching
:mod:`in_reach.app.rvt.decompile`'s own convention once normalized to a bare ``"\\n"`` on write, see
that module's own comment on why -- a blank line between top-level items, a trailing space after
``"then"``).

Ported verbatim from a prior prototype (``D:\\whileyRepos\\sort\\mega-ide``, PROMPT.md: "we want a
fromm scratch compiler then") -- see ``nodes.py``'s own module docstring for the full port note.

This module is also a "build Python, get script text back out" mechanism: build a ``Script`` (or
any node) directly in Python -- no text parsing involved -- and ``unparse()`` it straight to Megalo
source, ready for ``compile_script()``/:mod:`in_reach.app.rvt.megalo_compiler`.

``altif``/``alt`` clauses (``nodes.IfStatement``, the richer dialect's real "else if"/"else" -- see
``nodes.py``'s docstring for why not literal ``else``/``elseif``) are rendered the same "if ... then
" style as the leading ``if``, and a bare ``alt`` header (no trailing space, matching ``do``) --
this is an invented-here convention, not something to cross-check against ``decompile_script()``,
since the decompiler itself never emits ``altif``/``alt`` at all (it always flattens to sequential
sibling ``if``s -- see ``IfStatement``'s own docstring).

Does NOT re-emit ``Script.comments`` -- see ``nodes.Comment``'s own docstring for why comments are a
flat, position-independent list rather than nodes woven into the tree at an exact point ``unparse()``
could re-insert them at.
"""
from __future__ import annotations

from .nodes import Expression, Script, Statement

INDENT = "   "  # 3 spaces -- matches the decompiler's own indent step exactly


def unparse(script: Script) -> str:
    declarations = [s for s in script.body if s.kind in ("declare", "alias")]
    statements = [s for s in script.body if s.kind not in ("declare", "alias")]

    lines: list[str] = [""]  # leading blank line -- every fixture (including an empty script,
    # which is nothing *but* this line) starts this way; see this module's docstring.
    for decl in declarations:
        lines.extend(_render_statement(decl))
    if declarations and statements:
        lines.append("")
    for i, stmt in enumerate(statements):
        if i > 0:
            lines.append("")
        lines.extend(_render_statement(stmt))

    return "\r\n".join(lines) + "\r\n"


def _render_declaration(decl) -> str:
    text = f"declare {decl.scope}.{decl.type}[{decl.index}]"
    if decl.priority is not None:
        text += f" with network priority {decl.priority}"
    if decl.value is not None:
        text += f" = {render_expr(decl.value)}"
    return text


def _indent(lines: list[str]) -> list[str]:
    return [INDENT + line if line else line for line in lines]


def _render_block(body: list[Statement]) -> list[str]:
    out: list[str] = []
    for stmt in body:
        out.extend(_render_statement(stmt))
    return out


def _render_statement(stmt: Statement) -> list[str]:
    if stmt.kind == "declare":
        return [_render_declaration(stmt)]
    if stmt.kind == "alias":
        return [f"alias {stmt.name} = {render_expr(stmt.value)}"]
    if stmt.kind == "assign":
        return [f"{render_expr(stmt.target)} {stmt.op} {render_expr(stmt.value)}"]
    if stmt.kind == "expr_stmt":
        return [render_expr(stmt.expr)]
    if stmt.kind == "if":
        lines = [f"if {render_expr(stmt.condition)} then "]
        lines.extend(_indent(_render_block(stmt.body)))
        for clause in stmt.altif_clauses:
            lines.append(f"altif {render_expr(clause.condition)} then ")
            lines.extend(_indent(_render_block(clause.body)))
        if stmt.alt_body is not None:
            lines.append("alt")
            lines.extend(_indent(_render_block(stmt.alt_body)))
        lines.append("end")
        return lines
    if stmt.kind == "do":
        lines = ["do"]
        lines.extend(_indent(_render_block(stmt.body)))
        lines.append("end")
        return lines
    if stmt.kind == "for_each":
        header = f"for each {stmt.selector}"
        if stmt.label is not None:
            header += f" with label {render_expr(stmt.label)}"
        if stmt.randomly:
            header += " randomly"
        header += " do"
        lines = [header]
        lines.extend(_indent(_render_block(stmt.body)))
        lines.append("end")
        return lines
    if stmt.kind == "on":
        inner = _render_statement(stmt.body)
        return [f"on {stmt.event}: {inner[0]}", *inner[1:]]
    if stmt.kind == "function":
        lines = [f"function {stmt.name}()"]
        lines.extend(_indent(_render_block(stmt.body)))
        lines.append("end")
        return lines
    raise ValueError(f"unknown statement kind {stmt.kind!r}")


def render_expr(expr: Expression) -> str:
    if expr.kind == "int":
        return str(expr.value)
    if expr.kind == "percent":
        return f"{expr.value}%"
    if expr.kind == "string":
        return f'"{expr.value}"'
    if expr.kind == "identifier":
        return expr.name
    if expr.kind == "member":
        return f"{render_expr(expr.target)}.{expr.name}"
    if expr.kind == "index":
        return f"{render_expr(expr.target)}[{render_expr(expr.index)}]"
    if expr.kind == "call":
        return f"{render_expr(expr.target)}({', '.join(render_expr(a) for a in expr.args)})"
    if expr.kind == "unary":
        return f"not {render_expr(expr.operand)}"
    if expr.kind == "binary":
        return f"{render_expr(expr.left)} {expr.op} {render_expr(expr.right)}"
    raise ValueError(f"unknown expression kind {expr.kind!r}")
