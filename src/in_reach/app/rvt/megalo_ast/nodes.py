"""AST node types for Megalo script text (``script/output.txt`` -- RVT's own decompiler output, see
:mod:`in_reach.app.rvt.decompile`'s module docstring).
:func:`in_reach.app.rvt.megalo_ast.parser.parse` builds a :class:`Script` out of these;
:func:`in_reach.app.rvt.megalo_ast.unparse.unparse` renders one back to text.

Ported from a prior prototype (``D:\\whileyRepos\\sort\\mega-ide``, PROMPT.md: "we want a fromm
scratch compiler then" -- its own ``AST.md`` has the full design rationale/validation history this
docstring summarizes) verbatim, since it's already-built, already-tested code with no in-reach-
specific dependency at all.

This is deliberately NOT a binding onto ``_reachvarianttool``'s own C++ trigger/condition/action
classes (see :mod:`in_reach.app.rvt.megalo_ast.engine` for that binding) -- this module is the
separate, sibling text-side grammar. It covers Megalo script source text as a whole -- both what
``GameVariant.decompile_script()`` actually emits (declarations/for-each/do/if/on-event blocks,
sequential sibling ``if``s, no comments) AND the richer hand-authorable dialect ``compile_script()``
also accepts (comments, ``alias``, ``alt``/``altif`` -- confirmed directly via ``compile_script()``,
see below), since a user hand-editing ``script/output.txt`` before recompiling it can use either. A
plain recursive-descent parser over this text is enough to get a real, traversable object tree
without needing the C++ AST binding for it.

**``else``/``elseif`` do NOT work** despite being reserved words -- confirmed directly by compiling
one through ``compile_script()``: it fails with "Word \\"else\\" is reserved for potential future
use as a keyword. It cannot appear here." (``compiler.cpp``'s own ``is_keyword()`` comment says
exactly this: ``// reserved``, with no ``_handleKeyword_Else``/``_handleKeyword_ElseIf`` ever wired
up in ``__get_handler_for_keyword()``). The real, currently-working equivalent is ``alt``/``altif``
(``if <cond> then <body> [altif <cond> then <body>]* [alt <body>] end`` -- see :class:`IfStatement`
below), confirmed compiling successfully the same way.

Every node carries ``span`` (1-based line, 0-based column, matching how editors address positions)
so this doubles as the foundation for syntax-highlighting/debugging tooling -- a node found by
walking the tree can be mapped straight back to the exact text range that produced it.

Nodes are plain pydantic models (same convention as :mod:`in_reach.app.rvt.models`) with a ``kind``
discriminator field so ``Expression``/``Statement`` can be modeled as pydantic discriminated unions
-- this is what makes ``Script.model_dump_json()``/``model_validate_json()`` work out of the box for
the heterogeneous node lists, and is why every node class here is named for ``kind``'s value rather
than following a shared base-class-per-role pattern.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class SourceSpan(BaseModel):
    """1-based line numbers (matching how a human/editor reads ``script/output.txt``), 0-based
    columns. ``end_*`` is exclusive, i.e. one past the last character of the node's own text -- the
    same convention as Python's own slice semantics."""

    start_line: int
    start_col: int
    end_line: int
    end_col: int


class ASTNode(BaseModel):
    span: SourceSpan


# ---- Expressions --------------------------------------------------------------------------------


class IntLiteral(ASTNode):
    kind: Literal["int"] = "int"
    value: int  # sign is folded in here (e.g. -1) -- see parser.py's lexer docstring for why


class PercentLiteral(ASTNode):
    kind: Literal["percent"] = "percent"
    value: int  # the integer before "%" (e.g. -100 for "-100%"), not divided down to a fraction


class StringLiteral(ASTNode):
    kind: Literal["string"] = "string"
    value: str  # raw text between the quotes, escapes NOT interpreted -- see parser.py's lexer


class Identifier(ASTNode):
    kind: Literal["identifier"] = "identifier"
    name: str  # a bare name: current_player, no_object, team, sphere, script_option, ...


class Member(ASTNode):
    """``target.name`` -- property/method access, e.g. ``current_player.biped``."""

    kind: Literal["member"] = "member"
    target: Expression
    name: str


class Index(ASTNode):
    """``target[index]`` -- e.g. ``global.number[0]``, ``team[0]``, ``script_option[2]``."""

    kind: Literal["index"] = "index"
    target: Expression
    index: Expression


class Call(ASTNode):
    """``target(args...)`` -- e.g. ``send_incident(a, b, c)``, ``current_object.delete()``."""

    kind: Literal["call"] = "call"
    target: Expression
    args: list[Expression] = Field(default_factory=list)


class UnaryOp(ASTNode):
    kind: Literal["unary"] = "unary"
    op: Literal["not"]
    operand: Expression


class BinaryOp(ASTNode):
    kind: Literal["binary"] = "binary"
    op: Literal["and", "or", "|", "==", "!=", "<", ">", "<=", ">="]
    left: Expression
    right: Expression


Expression = Annotated[
    Union[IntLiteral, PercentLiteral, StringLiteral, Identifier, Member, Index, Call, UnaryOp, BinaryOp],
    Field(discriminator="kind"),
]


# ---- Statements -----------------------------------------------------------------------------------


class VariableDeclaration(ASTNode):
    """``declare <scope>.<type>[<index>] [with network priority <priority>] [= <value>]``."""

    kind: Literal["declare"] = "declare"
    scope: str  # global | player | object | team
    type: str  # number | object | player | team | timer
    index: int
    priority: str | None = None
    value: Expression | None = None


class AliasDeclaration(ASTNode):
    """``alias <name> = <value>`` -- the hand-authorable dialect's local name for an expression
    (confirmed compiling via ``compile_script()``; ``decompile_script()`` never emits one -- it's a
    compile-time-only convenience, resolved away in the compiled output, so a name declared this way
    decompiles back as whatever it was aliased to, not the alias name itself). Uses of the alias
    elsewhere in the source parse as an ordinary ``Identifier`` with that name -- this grammar
    doesn't resolve aliases (same "no semantic analysis, just structure" scope as everything else
    here); :func:`~in_reach.app.rvt.megalo_ast.aliases.resolve_aliases` is the separate pass that
    does."""

    kind: Literal["alias"] = "alias"
    name: str
    value: Expression


class Assignment(ASTNode):
    kind: Literal["assign"] = "assign"
    op: Literal["=", "+=", "-=", "*=", "/=", "%="]
    target: Expression
    value: Expression


class ExprStatement(ASTNode):
    """A call used as a bare statement, e.g. ``current_object.delete()`` on its own line."""

    kind: Literal["expr_stmt"] = "expr_stmt"
    expr: Expression


class ElseIfClause(ASTNode):
    """One ``altif <condition> then <body>`` clause attached to an :class:`IfStatement` -- see that
    class's docstring for why ``altif``, not ``elseif``. Not itself a member of the ``Statement``
    union (it can only appear as one of ``IfStatement.altif_clauses``, never standalone), but still
    carries ``kind`` so the generic ``walk()``/``iter_children()`` traversal in ``visit.py`` finds it
    like any other node."""

    kind: Literal["altif"] = "altif"
    condition: Expression
    body: list[Statement] = Field(default_factory=list)


class IfStatement(ASTNode):
    """``if <condition> then <body> [altif <condition> then <body>]* [alt <body>] end``. Decompiled
    text only ever produces the bare ``if ... then ... end`` form (sequential sibling ``if``s
    instead of chaining) -- ``altif_clauses``/``alt_body`` are empty/``None`` for anything parsed
    from decompiler output, and only populated when parsing the richer hand-authorable dialect.
    ``alt`` is Megalo's real "else" -- literal ``else``/``elseif`` are reserved words that don't
    actually compile (see this module's own docstring for how that was confirmed) -- ``altif`` is
    "else if". Per the compiler's own rule, at most one ``alt`` may appear, and only as the last
    clause (an ``altif`` can't follow an ``alt``)."""

    kind: Literal["if"] = "if"
    condition: Expression
    body: list[Statement] = Field(default_factory=list)
    altif_clauses: list[ElseIfClause] = Field(default_factory=list)
    alt_body: list[Statement] | None = None


class DoBlock(ASTNode):
    kind: Literal["do"] = "do"
    body: list[Statement] = Field(default_factory=list)


class ForEach(ASTNode):
    """``for each <selector> [with label <label>] [randomly] do <body> end``. ``label``/``randomly``
    can appear in either order in source; this always re-renders label before randomly (see
    ``unparse.py``) -- a harmless canonicalization, not a semantic difference."""

    kind: Literal["for_each"] = "for_each"
    selector: str  # player | object | team
    label: Expression | None = None  # IntLiteral or StringLiteral in practice
    randomly: bool = False
    body: list[Statement] = Field(default_factory=list)


class EventTrigger(ASTNode):
    """``on <event>: <statement>`` -- e.g. ``on pregame: do ... end``, ``on init: if ... then ...
    end``. ``event`` is the literal space-joined event name (e.g. "host migration") -- this grammar
    doesn't need to know the fixed set of valid Megalo event names, it just captures whatever
    identifiers precede the colon."""

    kind: Literal["on"] = "on"
    event: str
    body: Statement


class FunctionDeclaration(ASTNode):
    """``function <name>() <body> end`` -- a named, top-level, multi-caller subroutine (e.g. real
    decompiled ``function trigger_5()for each object do ... end ... end``). Only ever appears at
    ``Script.body``'s own top level, never nested -- real Megalo has no local/nested functions.
    Uses of ``<name>()`` elsewhere parse as an ordinary :class:`Call` with an :class:`Identifier`
    target (same "no semantic analysis, just structure" scope as everywhere else in this grammar --
    resolving a call to the function it names, vs. a built-in action/condition, is left to whatever
    consumes this tree)."""

    kind: Literal["function"] = "function"
    name: str
    body: list[Statement] = Field(default_factory=list)


Statement = Annotated[
    Union[
        VariableDeclaration, AliasDeclaration, Assignment, ExprStatement, IfStatement, DoBlock,
        ForEach, EventTrigger, FunctionDeclaration,
    ],
    Field(discriminator="kind"),
]


class Comment(ASTNode):
    """A ``-- text`` line comment (see ``lexer.py``) -- ``text`` is everything after ``--`` up to
    (not including) the newline, unstripped. NOT part of the ``Statement`` union or woven into the
    tree at its exact syntactic position -- comments carry no executable meaning and can occur
    between any two tokens (trailing on a line of real code, or standalone on their own line), so
    modeling them as a flat, ``span``-tagged list on ``Script`` instead is both simpler to parse and
    a better fit for the actual use case (a syntax highlighter colors comment spans directly against
    the *original* text using their own ``span``, independent of the statement tree -- it doesn't
    need them positioned inside it). The tradeoff: ``unparse()`` does not re-emit comments -- see
    its own docstring."""

    kind: Literal["comment"] = "comment"
    text: str


class Script(BaseModel):
    """The whole of a decompiled ``script/output.txt`` (or hand-authored source in the richer
    dialect). Top-level ``body`` mixes variable/alias declarations and top-level statements in
    source order -- top-level statements are each their own always-ticking trigger (Megalo has no
    single implicit "main" block; every top-level statement in the decompiled text runs every tick
    on its own), and ``on <event>: ...`` statements are event-bound triggers -- see
    :class:`EventTrigger`. ``comments`` is a flat, unordered-relative-to-``body`` list -- see
    :class:`Comment`'s own docstring for why."""

    kind: Literal["script"] = "script"
    body: list[Statement] = Field(default_factory=list)
    comments: list[Comment] = Field(default_factory=list)


for _cls in (
    Member, Index, Call, UnaryOp, BinaryOp,
    VariableDeclaration, AliasDeclaration, Assignment, ExprStatement, ElseIfClause, IfStatement,
    DoBlock, ForEach, EventTrigger, FunctionDeclaration, Comment, Script,
):
    _cls.model_rebuild()
