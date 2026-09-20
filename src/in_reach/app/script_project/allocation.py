"""Giving every declared storage name a slot (``TO_IMPLEMENT`` §4.1, §4.2, §6 step 4).

Code says ``@pnumber p_hud_count``; the engine has ``player.number[0]`` to ``player.number[7]``. This decides which,
and what each slot is declared as. Allocation is **stable**: names are placed in the order they are declared and
each takes the lowest free slot, so an unchanged project always relinks to the same slots.

Rules:

* **Pools.** A slot is ``scope.type[index]``; each pool has the engine's own capacity (``POOL_SIZES``). A pool that
  runs out is an error naming the pool and the name that tipped it.
* **Slots the code already uses.** Hand-written ``global.number[3]`` or ``current_player.timer[0]`` is reserved:
  nothing is allocated over it.
* **Pins.** ``project.toml``'s ``[pins]`` (``"p_hud_count" = "player.number[0]"``) fix a name to a slot, checked
  against its declaration.
* **Kinds share object slots.** No object is ever two kinds, so ``carrier.c_role`` and ``weapon.w_level`` may both
  be ``object.number[0]``; each kind (and each team, for team storage) gets its own numbering from 0.
* **A shared slot has one declared default.** Only a variable with ``owns_default=true`` may set the default of a
  slot other kinds share, and two kinds can't both own the same slot's default -- the second is placed elsewhere.
  Without an owner, a slot's default is a single candidate's, or none if several disagree.
* **Bitfields** are one object number holding the flags, each flag an alias for a power of two (bit 15 reserved).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from in_reach.app.rvt.megalo_ast import render_expr
from in_reach.app.rvt.megalo_ast.annotations import BitfieldAnnotation, StorageAnnotation
from in_reach.app.rvt.megalo_compiler import _POOL_SIZES as POOL_SIZES

from .diagnostics import ProjectDiagnostic
from .model import Declared

_PIN = re.compile(r"(global|player|object|team)\.(number|object|player|team|timer)\[(\d+)\]")
_PRIORITY_RANK = {"local": 0, "low": 1, "high": 2}
_TEAM_OWNER = re.compile(r"team([0-7])")


@dataclass(frozen=True)
class Slot:
    scope: str
    type: str
    index: int
    owner: str | None = None  # the kind (object storage) or team (team storage) it belongs to

    @property
    def pool(self) -> tuple[str, str]:
        return (self.scope, self.type)

    @property
    def concrete(self) -> str:
        """What an alias for this variable is set to. Per-player and per-object storage is ``player.number[0]``,
        used as ``current_player.name``; a team's is a specific team's slot."""
        if self.scope == "team":
            match = _TEAM_OWNER.fullmatch(self.owner or "")
            team = f"team[{match[1]}]" if match else "team"
            return f"{team}.{self.type}[{self.index}]"
        return f"{self.scope}.{self.type}[{self.index}]"


@dataclass
class SlotDeclaration:
    """What ``declare`` says about a slot: only ever the priority/default some name asked for."""

    priority: str | None = None
    default: str | None = None  # rendered expression


@dataclass
class Allocation:
    slots: dict[str, Slot] = field(default_factory=dict)
    owners: dict[str, str] = field(default_factory=dict)  # name -> the module/file that declared it
    declarations: dict[tuple[str, str, int], SlotDeclaration] = field(default_factory=dict)
    used: dict[tuple[str, str], int] = field(default_factory=dict)  # pool -> how many slots (highest index + 1)
    flags: dict[str, list[tuple[str, int]]] = field(default_factory=dict)  # bitfield -> [(flag alias, value)]
    diagnostics: list[ProjectDiagnostic] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(d.severity == "error" for d in self.diagnostics)


@dataclass
class _Variable:
    name: str
    scope: str
    type: str
    owner: str | None
    priority: str | None
    default: str | None
    owns_default: bool
    declared: Declared
    is_bitfield: bool = False


def _variables(storage: list[Declared], bitfields: list[Declared]) -> list[_Variable]:
    found: list[_Variable] = []
    for declared in storage:
        a = declared.annotation
        if isinstance(a, StorageAnnotation):
            found.append(
                _Variable(
                    a.name, a.scope, a.type, a.owner, a.priority,
                    render_expr(a.default) if a.default is not None else None, a.owns_default, declared,
                )
            )
    for declared in bitfields:
        a = declared.annotation
        if isinstance(a, BitfieldAnnotation):
            found.append(_Variable(a.name, "object", "number", a.owner, None, None, False, declared, is_bitfield=True))
    return found


def allocate(
    storage: list[Declared],
    bitfields: list[Declared],
    pins: dict[str, str],
    reserved: set[tuple[str, str, int]],
) -> Allocation:
    """Allocates ``storage`` and ``bitfields`` (as :class:`~.model.SemanticModel` lists them). ``reserved`` is every
    slot the hand-written code already uses."""
    result = Allocation()
    variables = _variables(storage, bitfields)
    by_name = {v.name: v for v in variables}

    def error(variable: _Variable, message: str) -> None:
        a = variable.declared.annotation
        result.diagnostics.append(
            ProjectDiagnostic(severity="error", code="alloc", message=message, file=variable.declared.file, line=a.span.start_line)
        )

    parsed_pins = _parse_pins(pins, by_name, result)

    # (scope, type) -> group -> the indexes that group already uses. Global and player storage is one group.
    taken: dict[tuple[str, str], dict[str | None, set[int]]] = {}
    default_owner: dict[tuple[str, str, int], str | None] = {}  # slot -> group that owns its default
    sharers: dict[tuple[str, str, int], list[_Variable]] = {}

    # A pin wins over auto-placement, wherever the pinned name is declared: reserve every pinned slot first, so
    # nothing else is placed on it.
    for variable in variables:
        pinned_index = parsed_pins.get(variable.name)
        if pinned_index is not None:
            taken.setdefault((variable.scope, variable.type), {}).setdefault(variable.owner, set()).add(pinned_index)

    for variable in variables:
        if variable.name in result.slots:
            continue  # a duplicate name is IR006's to report; the first one keeps the slot
        pool = (variable.scope, variable.type)
        capacity = POOL_SIZES[variable.scope][variable.type]
        group = variable.owner
        used = taken.setdefault(pool, {}).setdefault(group, set())
        blocked = used | {i for (s, t, i) in reserved if (s, t) == pool}

        pinned = parsed_pins.get(variable.name)
        if pinned is not None:
            index = pinned
        else:
            index = next(
                (
                    i for i in range(capacity)
                    if i not in blocked and _can_own(variable, (variable.scope, variable.type, i), default_owner)
                ),
                None,
            )
            if index is None:
                error(
                    variable,
                    f"{pool[0]}.{pool[1]} is full ({capacity} slots): {variable.name} "
                    f"({variable.declared.owner}) has nowhere to go",
                )
                continue

        used.add(index)
        key = (variable.scope, variable.type, index)
        slot = Slot(variable.scope, variable.type, index, group)
        result.slots[variable.name] = slot
        result.owners[variable.name] = variable.declared.owner
        sharers.setdefault(key, []).append(variable)
        if variable.owns_default:
            default_owner[key] = group
        result.used[pool] = max(result.used.get(pool, 0), index + 1)
        if variable.is_bitfield:
            a = variable.declared.annotation
            result.flags[variable.name] = [(f"flag_{flag}", 1 << bit) for bit, flag in enumerate(a.flags)]

    for key, group in sharers.items():
        declaration = _declaration(key, group, result)
        if declaration.priority is not None or declaration.default is not None:
            result.declarations[key] = declaration
    for reserved_slot in reserved:  # the code's own slots count toward the pool too
        pool = reserved_slot[:2]
        if reserved_slot[0] in POOL_SIZES and reserved_slot[1] in POOL_SIZES[reserved_slot[0]]:
            result.used[pool] = max(result.used.get(pool, 0), reserved_slot[2] + 1)
    return result


def _can_own(variable: _Variable, key: tuple[str, str, int], default_owner: dict[tuple[str, str, int], str | None]) -> bool:
    """A variable that owns its slot's default can't go where another group already owns it."""
    if not variable.owns_default:
        return True
    return key not in default_owner or default_owner[key] == variable.owner


def _declaration(key: tuple[str, str, int], sharers: list[_Variable], result: Allocation) -> SlotDeclaration:
    """The priority and default a slot is declared with, given the variables sharing it."""
    priorities = [v.priority for v in sharers if v.priority is not None]
    priority = max(priorities, key=_PRIORITY_RANK.__getitem__) if priorities else None
    if key[1] == "timer":
        priority = None  # a timer has no network priority

    with_default = [v for v in sharers if v.default is not None]
    owners = [v for v in with_default if v.owns_default]
    default: str | None
    if owners:
        default = owners[0].default
    elif len(with_default) == 1 or (with_default and len({v.default for v in with_default}) == 1 and len(sharers) == len(with_default)):
        default = with_default[0].default
    else:
        default = None
        if len(with_default) > 1:
            names = ", ".join(v.name for v in with_default)
            first = with_default[0]
            result.diagnostics.append(
                ProjectDiagnostic(
                    severity="warning", code="default-ambiguous",
                    message=f"{names} share {key[0]}.{key[1]}[{key[2]}] and each set a default, so it has none",
                    file=first.declared.file, line=first.declared.annotation.span.start_line,
                    hint="give exactly one of them owns_default=true",
                )
            )
    if any(v.default is not None and v.default != default for v in sharers) and default is not None:
        ignored = next(v for v in sharers if v.default is not None and v.default != default)
        result.diagnostics.append(
            ProjectDiagnostic(
                severity="warning", code="default-ignored",
                message=f"{ignored.name}'s default is ignored: it shares its slot with a variable that owns the default",
                file=ignored.declared.file, line=ignored.declared.annotation.span.start_line,
            )
        )
    return SlotDeclaration(priority=priority, default=default)


def _parse_pins(pins: dict[str, str], by_name: dict[str, _Variable], result: Allocation) -> dict[str, int]:
    parsed: dict[str, int] = {}
    holders: dict[tuple[str, str, int, str | None], str] = {}
    for name, value in pins.items():
        variable = by_name.get(name)
        match = _PIN.fullmatch(value)
        if variable is None:
            result.diagnostics.append(
                ProjectDiagnostic(severity="warning", code="pin-unused", message=f"[pins] names {name}, which nothing declares",
                                  file="project.toml", hint="check the spelling")
            )
            continue
        line = variable.declared.annotation.span.start_line
        if match is None:
            result.diagnostics.append(
                ProjectDiagnostic(severity="error", code="pin-invalid", message=f"pin {name} = {value!r} isn't a slot like player.number[0]",
                                  file="project.toml")
            )
            continue
        scope, type_, index = match[1], match[2], int(match[3])
        if (scope, type_) != (variable.scope, variable.type):
            result.diagnostics.append(
                ProjectDiagnostic(
                    severity="error", code="pin-mismatch",
                    message=f"{name} is {variable.scope}.{variable.type} storage, but is pinned to {value}",
                    file="project.toml",
                )
            )
            continue
        if index >= POOL_SIZES[scope][type_]:
            result.diagnostics.append(
                ProjectDiagnostic(severity="error", code="pin-invalid", message=f"{value} is past the end of the pool ({POOL_SIZES[scope][type_]} slots)",
                                  file="project.toml")
            )
            continue
        holder_key = (scope, type_, index, variable.owner)
        if holder_key in holders:
            result.diagnostics.append(
                ProjectDiagnostic(severity="error", code="pin-conflict", message=f"{name} and {holders[holder_key]} are pinned to the same slot, {value}",
                                  file="project.toml")
            )
            continue
        holders[holder_key] = name
        parsed[name] = index
    return parsed
