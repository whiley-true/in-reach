"""Putting a project's blocks in order (``TO_IMPLEMENT`` §6.1).

The blocks (``SETUP``, ``HILL_PASS``, ...) form a graph: ``project.toml``'s ``[blocks].order`` is a chain, and
each module adds edges -- the blocks it contributes to must come after its ``after`` blocks and before its
``before`` blocks. :func:`order_blocks` sorts the graph. A block that no edge places relative to anything is
put where it ranks: by its position in ``[blocks].order`` if it is listed, else after every listed block, in
the order it was first seen -- so the result is the same every time for the same project, which is what keeps a
relink from shuffling a build's diff.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass


@dataclass(frozen=True)
class Edge:
    """``before`` runs before ``after``. ``source`` names where the constraint came from, for error messages
    (``"project.toml [blocks].order"``, ``"module hill_buff [order]"``)."""

    before: str
    after: str
    source: str


def order_blocks(
    blocks: list[str], listed: list[str], edges: list[Edge]
) -> tuple[list[str], list[Edge] | None]:
    """Sorts ``blocks`` (given in first-seen order) under ``edges``.

    ``listed`` is ``[blocks].order``, used to rank blocks that no edge decides between. Returns
    ``(order, cycle)``: ``cycle`` is ``None`` for a valid ordering, otherwise the edges that go round in a
    circle, and ``order`` is then a best effort (the blocks that could be placed, then the rest by rank).
    """
    rank = {name: index for index, name in enumerate(listed)}
    for name in blocks:
        rank.setdefault(name, len(listed) + len(rank))

    successors: dict[str, list[Edge]] = {name: [] for name in blocks}
    waiting: dict[str, int] = {name: 0 for name in blocks}
    for edge in edges:
        successors[edge.before].append(edge)
        waiting[edge.after] += 1

    ready = [(rank[name], name) for name in blocks if waiting[name] == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        _, name = heapq.heappop(ready)
        order.append(name)
        for edge in successors[name]:
            waiting[edge.after] -= 1
            if waiting[edge.after] == 0:
                heapq.heappush(ready, (rank[edge.after], edge.after))

    if len(order) == len(blocks):
        return order, None
    stuck = sorted((name for name in blocks if name not in order), key=lambda name: rank[name])
    return order + stuck, _find_cycle(stuck, successors)


def _find_cycle(stuck: list[str], successors: dict[str, list[Edge]]) -> list[Edge]:
    """Edges forming a cycle among ``stuck`` blocks (in rank order).

    A block is stuck if it sits on a cycle *or* only waits on one, so the search can't start at just any of
    them: first the blocks with no way forward inside the set are pruned (repeatedly -- pruning one can strand
    the block before it), which leaves only blocks that each have an edge onward, and walking those edges must
    come back round to a block already visited."""
    remaining = set(stuck)
    pruned = True
    while pruned:
        pruned = False
        for name in list(remaining):
            if not any(edge.after in remaining for edge in successors[name]):
                remaining.discard(name)
                pruned = True

    node = next(name for name in stuck if name in remaining)
    path: list[Edge] = []
    seen_at: dict[str, int] = {}
    while node not in seen_at:
        seen_at[node] = len(path)
        edge = next(e for e in successors[node] if e.after in remaining)
        path.append(edge)
        node = edge.after
    return path[seen_at[node]:]
