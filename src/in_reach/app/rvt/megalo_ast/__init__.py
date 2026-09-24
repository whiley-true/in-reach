"""``in_reach.app.rvt.megalo_ast`` -- a traversable Python AST for Megalo script text
(``script/output.mgl``). Ported from a prior prototype
(``D:\\whileyRepos\\sort\\mega-ide``, PROMPT.md: "we want a fromm scratch compiler then") -- see
``nodes.py``'s module docstring for the full port note, and ``engine.py``'s for the sibling
engine-bound half this package also carries. :mod:`in_reach.app.rvt.megalo_compiler` is built on
top of both.

Typical use::

    from in_reach.app.rvt.megalo_ast import parse, unparse, walk

    script = parse(script_text)         # -> nodes.Script
    text = unparse(script)              # -> Megalo source text, ready for compile_script()
    for node in walk(script):           # depth-first traversal, e.g. for syntax highlighting
        ...
"""
from .aliases import RESERVED_NAMES, MegaloAliasError, resolve_aliases
from .engine import (
    EngineActionStatement, EngineArgument, EngineAst, EngineDoBlock, EngineForEachBlock,
    EngineIfStatement, EngineInlineBlock, EngineOpcode, EngineRawStatement, EngineStatement,
    EngineTrigger, EngineTriggerCallStatement, extract_triggers,
)
from .lexer import MegaloLexError
from .nodes import (
    AliasDeclaration, Assignment, BinaryOp, Call, Comment, DoBlock, ElseIfClause, EventTrigger,
    Expression, ExprStatement, ForEach, FunctionDeclaration, Identifier, IfStatement, Index,
    IntLiteral, Member, PercentLiteral, Script, SourceSpan, Statement, StringLiteral, UnaryOp,
    VariableDeclaration,
)
from .annotations import (
    Annotation, AnnotationDiagnostic, Annotations, parse_annotations,
)
from .parser import MegaloParseError, parse, parse_expression
from .unparse import render_expr, unparse
from .visit import find_at, iter_children, walk

__all__ = [
    "parse", "parse_expression", "unparse", "render_expr", "walk", "iter_children", "find_at",
    "parse_annotations", "Annotations", "Annotation", "AnnotationDiagnostic",
    "resolve_aliases", "MegaloAliasError", "RESERVED_NAMES",
    "MegaloLexError", "MegaloParseError",
    "Script", "SourceSpan", "Expression", "Statement",
    "IntLiteral", "PercentLiteral", "StringLiteral", "Identifier", "Member", "Index", "Call",
    "UnaryOp", "BinaryOp", "VariableDeclaration", "AliasDeclaration", "Assignment",
    "ExprStatement", "IfStatement", "ElseIfClause", "DoBlock", "ForEach", "EventTrigger",
    "FunctionDeclaration", "Comment",
    "extract_triggers", "EngineAst", "EngineTrigger", "EngineOpcode", "EngineArgument",
    "EngineStatement", "EngineActionStatement", "EngineIfStatement", "EngineDoBlock",
    "EngineInlineBlock", "EngineForEachBlock", "EngineTriggerCallStatement", "EngineRawStatement",
]
