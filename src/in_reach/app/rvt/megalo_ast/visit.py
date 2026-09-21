"""Generic traversal over the AST -- works over any node type without a per-node-type visitor
table: every node is a plain pydantic model, so children are just "every field value that's itself
a node (or a list of them)", found by introspecting ``__dict__`` rather than hand-listing each node
class's child fields (keeps this file correct automatically as ``nodes.py`` grows).

Ported verbatim from a prior prototype (``D:\\whileyRepos\\sort\\mega-ide``, PROMPT.md: "we want a
fromm scratch compiler then") -- see ``nodes.py``'s own module docstring for the full port note.
"""
from __future__ import annotations

from typing import Iterator

from pydantic import BaseModel

from .nodes import SourceSpan


def _is_node(value: object) -> bool:
    return isinstance(value, BaseModel) and hasattr(value, "kind")


def iter_children(node: BaseModel) -> Iterator[BaseModel]:
    """Every direct child node of ``node``, in field-declaration order. Skips ``span`` (position
    metadata, not part of the tree shape) and any field that isn't itself a node or a list of nodes
    (e.g. ``VariableDeclaration.scope``, a plain str)."""
    for field_name, value in node.__dict__.items():
        if field_name == "span":
            continue
        if _is_node(value):
            yield value
        elif isinstance(value, list):
            for item in value:
                if _is_node(item):
                    yield item


def walk(node: BaseModel) -> Iterator[BaseModel]:
    """Depth-first, pre-order: ``node`` itself, then each child's own ``walk()`` in order. This is
    the ordering a source-text-shaped tree like this one wants for most uses (e.g. syntax
    highlighting a file top to bottom) -- see this module's own docstring."""
    yield node
    for child in iter_children(node):
        yield from walk(child)


def _span_size(span: SourceSpan) -> tuple[int, int]:
    return (span.end_line - span.start_line, span.end_col - span.start_col)


def _span_contains(span: SourceSpan, line: int, col: int) -> bool:
    if line < span.start_line or line > span.end_line:
        return False
    if line == span.start_line and col < span.start_col:
        return False
    if line == span.end_line and col >= span.end_col:
        return False
    return True


def find_at(root: BaseModel, line: int, col: int) -> BaseModel | None:
    """The most specific (smallest-span) node whose source range contains ``(line, col)`` -- 1-based
    line, 0-based col, matching ``SourceSpan``'s own convention. Returns ``None`` outside every
    node's range -- e.g. for mapping a click or a compiler-reported error position back to the AST
    node it came from."""
    best: BaseModel | None = None
    for node in walk(root):
        span = getattr(node, "span", None)
        if span is not None and _span_contains(span, line, col):
            if best is None or _span_size(span) <= _span_size(best.span):
                best = node
    return best
