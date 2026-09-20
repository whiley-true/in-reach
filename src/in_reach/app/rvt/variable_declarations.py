"""Variable declarations for :mod:`in_reach.app.rvt.megalo_compiler`: what ``declare global.number[0]
with network priority high = 7`` writes into a variant, and which declarations a script implies just
by using a variable.

A variant stores, per scope (global/player/object/team), how many variables of each type it
allocates and each one's network priority and initial value. Native ``compile_script()`` rebuilds
all of it from the script text: every ``declare`` line is recorded, every variable the script merely
*uses* is implied (its list grows to ``index + 1``, the new entries at network priority ``low`` and
initial value zero), and whatever the variant declared before is discarded. This module does the
same, in two steps so nothing is touched until the whole script has been checked:

* :func:`collect_declarations` -- pure AST -> :class:`DeclarationPlan`;
* :func:`write_declarations` -- applies a plan to a variant through the native bindings.

Anything it can't represent or isn't sure about (an unknown owner in ``<owner>.number[1]``, a
redeclaration, an initial value that isn't a constant/option/team) raises
:class:`UnsupportedDeclaration`, which the compiler turns into a fall-back to the native compiler --
never a silently wrong declaration table.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .megalo_ast.unparse import render_expr
from .megalo_ast.visit import walk

_DECLARABLE_SCOPES = ("global", "player", "object", "team")

# Script-text type name -> native ``VariableType`` member name.
_NATIVE_TYPE_NAMES = {
    "number": "scalar",
    "timer": "timer",
    "team": "team",
    "player": "player",
    "object": "object",
}
_NETWORK_PRIORITIES = ("local", "low", "high")

# ``team[N]`` / ``neutral_team`` / ``no_team`` as ``VariableDeclaration.initial_team`` spells them.
_NO_TEAM = -1
_NEUTRAL_TEAM = 8
_TEAM_COUNT = 8

# A variable's owner scope, from the name of the thing that owns it (``current_player.number[1]``):
# the named-reference identifiers all end in the type of what they refer to (``current_player``,
# ``hud_player``, ``killed_object``, ``neutral_team``).
_OWNER_SUFFIX_SCOPES = {"_player": "player", "_object": "object", "_team": "team"}
# ``global.<type>[N]`` is itself a variable that can own others; only these three types can.
_OWNING_TYPES = ("player", "object", "team")


class UnsupportedDeclaration(Exception):
    """A declaration (or a variable reference implying one) this module won't guess at."""


@dataclass
class InitialValue:
    """A declared initial value, resolved to the form the native bindings take.

    A number or timer is a scope-format string plus index (``"%i"`` and the value, for a constant);
    a team is ``team_code`` alone.
    """

    scope_format: str | None = None
    index: int = 0
    team_code: int | None = None


@dataclass
class SlotDeclaration:
    """One explicit ``declare`` line."""

    priority: str | None = None
    initial: InitialValue | None = None


@dataclass
class DeclarationPlan:
    """What a script says about its variable declarations.

    ``counts`` is the list length wanted per ``(scope, type)`` -- one past the highest slot either
    declared or used. ``explicit`` holds only the slots with a ``declare`` line, keyed by
    ``(scope, type, index)``; every other slot keeps the defaults a freshly grown list has.
    """

    counts: dict[tuple[str, str], int] = field(default_factory=dict)
    explicit: dict[tuple[str, str, int], SlotDeclaration] = field(default_factory=dict)

    def require(self, scope: str, type_name: str, index: int) -> None:
        key = (scope, type_name)
        self.counts[key] = max(self.counts.get(key, 0), index + 1)

    @property
    def script_option_count(self) -> int:
        """How many script options the initial values refer to (``script_option[N]`` needs ``N + 1``)."""
        needed = 0
        for slot in self.explicit.values():
            initial = slot.initial
            if initial is not None and initial.scope_format == "script_option[%i]":
                needed = max(needed, initial.index + 1)
        return needed


def collect_declarations(script, pool_sizes: dict[str, dict[str, int]]) -> DeclarationPlan:
    """Builds the plan for ``script`` (an alias-resolved AST); ``pool_sizes`` is ``scope -> {type:
    size}``.

    Raises:
        UnsupportedDeclaration: for anything this module doesn't handle -- see the module docstring.
    """
    plan = DeclarationPlan()
    for node in walk(script):
        if node.kind == "declare":
            _record_declare(plan, node, pool_sizes)
    for node in walk(script):
        reference = _variable_reference(node)
        if reference is None:
            continue
        scope, type_name, index = reference
        _check_in_range(scope, type_name, index, pool_sizes)
        plan.require(scope, type_name, index)
    return plan


def _check_in_range(scope: str, type_name: str, index: int, pool_sizes: dict[str, dict[str, int]]) -> None:
    size = pool_sizes[scope][type_name]
    if not 0 <= index < size:
        raise UnsupportedDeclaration(f"{scope}.{type_name}[{index}] is out of range (pool size {size})")


def _record_declare(plan: DeclarationPlan, stmt, pool_sizes: dict[str, dict[str, int]]) -> None:
    if stmt.scope not in _DECLARABLE_SCOPES:
        raise UnsupportedDeclaration(f"declare scope {stmt.scope!r} is not supported")
    if stmt.type not in _NATIVE_TYPE_NAMES:
        raise UnsupportedDeclaration(f"declare type {stmt.type!r} is not supported")
    _check_in_range(stmt.scope, stmt.type, stmt.index, pool_sizes)

    key = (stmt.scope, stmt.type, stmt.index)
    if key in plan.explicit:
        raise UnsupportedDeclaration(f"{stmt.scope}.{stmt.type}[{stmt.index}] is declared more than once")

    if stmt.priority is not None:
        if stmt.priority not in _NETWORK_PRIORITIES:
            raise UnsupportedDeclaration(f"{stmt.priority!r} is not a network priority")
        if stmt.type == "timer":
            raise UnsupportedDeclaration("a timer has no network priority")

    initial = None
    if stmt.value is not None:
        initial = _resolve_initial(stmt.type, stmt.value)

    plan.explicit[key] = SlotDeclaration(priority=stmt.priority, initial=initial)
    plan.require(stmt.scope, stmt.type, stmt.index)


def _resolve_initial(type_name: str, value) -> InitialValue:
    if type_name == "team":
        return InitialValue(team_code=_team_code(value))
    if type_name in ("number", "timer"):
        return _scalar_initial(value)
    raise UnsupportedDeclaration(f"a {type_name} variable has no initial value")


def _team_code(value) -> int:
    if value.kind == "identifier" and value.name == "no_team":
        return _NO_TEAM
    if value.kind == "identifier" and value.name == "neutral_team":
        return _NEUTRAL_TEAM
    if (
        value.kind == "index"
        and value.target.kind == "identifier"
        and value.target.name == "team"
        and value.index.kind == "int"
        and 0 <= value.index.value < _TEAM_COUNT
    ):
        return value.index.value
    raise UnsupportedDeclaration(f"{render_expr(value)!r} is not a constant team")


def _scalar_initial(value) -> InitialValue:
    if value.kind == "int":
        return InitialValue(scope_format="%i", index=value.value)
    if (
        value.kind == "index"
        and value.target.kind == "identifier"
        and value.target.name == "script_option"
        and value.index.kind == "int"
    ):
        return InitialValue(scope_format="script_option[%i]", index=value.index.value)
    if value.kind == "member" and value.target.kind == "identifier":
        # A built-in value with no index, e.g. ``game.loadout_cam_time``: its scope's format string
        # is its own text.
        return InitialValue(scope_format=render_expr(value), index=0)
    raise UnsupportedDeclaration(f"{render_expr(value)!r} is not a supported initial value")


def _variable_reference(node) -> tuple[str, str, int] | None:
    """``(scope, type, index)`` for a ``<owner>.<type>[N]`` node that names a declarable variable,
    ``None`` for anything else (including a temporary, which is never declared)."""
    if node.kind != "index" or node.index.kind != "int":
        return None
    member = node.target
    if member.kind != "member" or member.name not in _NATIVE_TYPE_NAMES:
        return None
    scope = _owning_scope(member.target)
    if scope is None:
        raise UnsupportedDeclaration(f"can't tell which scope {render_expr(node)!r} belongs to")
    if scope == "temporaries":
        return None
    return scope, member.name, node.index.value


def _owning_scope(owner) -> str | None:
    """The scope a variable lives in, given what it hangs off (``global``, ``current_player``,
    ``global.object[2]``, ``team[0]``, ...)."""
    if owner.kind == "identifier":
        if owner.name in ("global", "temporaries"):
            return owner.name
        for suffix, scope in _OWNER_SUFFIX_SCOPES.items():
            if owner.name.endswith(suffix):
                return scope
        return None
    if owner.kind != "index":
        return None
    target = owner.target
    if target.kind == "identifier" and target.name == "team":
        return "team"
    if (
        target.kind == "member"
        and target.target.kind == "identifier"
        and target.target.name == "global"
        and target.name in _OWNING_TYPES
    ):
        return target.name
    return None


def write_declarations(rvt, multiplayer, plan: DeclarationPlan) -> None:
    """Replaces ``multiplayer``'s variable declarations with ``plan``'s.

    Raises:
        UnsupportedDeclaration: if the native bindings reject an initial value (an unknown built-in,
            say). The declarations are left half-written; the compiler's own "failure must not leave
            partial state" rule (a fresh variant for the fall-back) covers that.
    """
    for scope in _DECLARABLE_SCOPES:
        multiplayer.variable_declarations(_native_scope(rvt, scope)).clear()

    for (scope, type_name), count in plan.counts.items():
        declarations = multiplayer.variable_declarations(_native_scope(rvt, scope))
        declarations.grow_to(_native_type(rvt, type_name), count)

    for (scope, type_name, index), slot in plan.explicit.items():
        declarations = multiplayer.variable_declarations(_native_scope(rvt, scope))
        declaration = declarations.get(_native_type(rvt, type_name), index)
        if slot.priority is not None:
            declaration.networking = getattr(rvt.VariableNetworkPriority, slot.priority)
        if slot.initial is not None:
            _write_initial(declaration, slot.initial)


def _write_initial(declaration, initial: InitialValue) -> None:
    if initial.team_code is not None:
        declaration.initial_team = initial.team_code
        return
    try:
        declaration.initial_number.set_scope_by_format(initial.scope_format, initial.index)
    except RuntimeError as exc:
        raise UnsupportedDeclaration(f"unsupported initial value {initial.scope_format!r}") from exc


def _native_scope(rvt, scope: str):
    return getattr(rvt.VariableScope, scope)  # `global` is a keyword, so no attribute syntax for all four


def _native_type(rvt, type_name: str):
    return getattr(rvt.VariableType, _NATIVE_TYPE_NAMES[type_name])
