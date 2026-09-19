"""A synthetic, from-scratch pool of argument templates for :mod:`in_reach.app.rvt.megalo_compiler`.

## Why this exists

The in-house compiler builds every variable reference by cloning a real, already-compiled example out
of the target variant's own script and retargeting its index (see that module's docstring, "Constructing
variable references: clone-and-retarget" -- the native binding has no constructor for a ``Variable`` at
all). A variant started from a real ``.bin`` always has plenty of examples; the packaged *blank*
variants have none, so a script written from scratch against one fell back to the native compiler for
nearly everything (measured: 2 of 426 real scripts compiled in-house against a blank base, vs 425 of
426 against their own).

This module manufactures the missing examples: a script made entirely of small statements that each
put one reference shape into one argument slot, compiled once by the *native* compiler (which needs no
templates) into throwaway variants that :func:`~in_reach.app.rvt.megalo_compiler.compile_script` then
scans exactly like a variant's own script. Nothing here is copied from any game variant -- the shape
tables below are the engine's own storage layout (``megalo_compiler._POOL_SIZES``) plus the names of
its built-in properties, and every statement is generated from them.

## What is (and isn't) covered

- One exemplar of every index-free shape in each argument family the compiler looks templates up
  for (``_any_variable``/``object``/``timer``/``team``/``player``/``_player_or_group``), retargeted by
  the compiler for any index.
- Every *chained* reference (``global.object[3].number[2]``) in exact text: the engine packs the
  owner's slot and the member together in one opaque value with no derivable formula, so a chain can
  only be cloned from an identical one (see ``_build_opaque_variable_arg``), never retargeted -- hence
  the full cross product of owner slot x member slot, the bulk of the pool.
- Not covered: a per-player stat on any owner but ``current_player`` (``global.player[3].script_stat[1]``)
  and a team's stat -- neither can be built directly, and no statement can produce one (native
  compilation rejects a stat that doesn't exist, and the base has none). Those still need an
  example in the base variant's own script. Forge labels, widgets, trait sets, options and
  ``current_player.script_stat[N]`` need nothing from here: the compiler creates the entries and
  builds the references itself (see ``megalo_compiler._ensure_table_entries``), and a timer rate is
  found by search (``TimerRateArgument.value`` is writable).
"""
from __future__ import annotations

from collections.abc import Iterator

from .megalo_compiler import _POOL_SIZES

# What a shape's *value* is, which decides what it can be assigned to / used as a receiver of.
_NUMBER, _TIMER, _OBJECT, _PLAYER, _TEAM = "number", "timer", "object", "player", "team"

#: One local stand-in per value type, for the *other* side of an assignment: `A = B` needs both sides
#: to be the same type, and the exemplar under test is the only side that matters.
_ANCHOR = {
    _NUMBER: "global.number[0]",
    _TIMER: "global.timer[0]",
    _OBJECT: "global.object[0]",
    _PLAYER: "global.player[0]",
    _TEAM: "global.team[0]",
}

#: ``prefix -> scope`` for the ``current_*``/``temporaries`` spellings ``megalo_compiler`` resolves.
_SELF_PREFIXES = {
    "global": "global",
    "current_player": "player",
    "current_object": "object",
    "current_team": "team",
    "temporaries": "temporaries",
}

#: Index-free shapes that aren't ``<prefix>.<type>[N]`` at all: the engine's own singleton
#: properties and null/self constants, each with the type of value it holds. (Names only -- the
#: engine's own vocabulary, see ``MEGALO_OFFICIAL_REFERENCE.md``.)
_PLAIN_SHAPES: dict[str, tuple[str, ...]] = {
    _NUMBER: (
        "current_object.spawn_sequence", "current_player.score", "current_player.rating",
        "current_team.score", "game.current_round", "game.loadout_cam_time", "game.round_limit",
        "game.round_time_limit", "game.score_to_win", "game.sudden_death_time",
        "game.symmetry", "game.teams_enabled",
    ),
    _TIMER: ("game.grace_period_timer", "game.round_timer", "game.sudden_death_timer"),
    _OBJECT: ("current_object", "current_player.biped", "killed_object", "no_object"),
    _PLAYER: ("current_player",),
    _TEAM: ("current_team", "current_object.team", "current_player.team", "neutral_team"),
}

#: Only meaningful in a "player or group" slot (and, for the nulls, nowhere with a value type).
_GROUP_ONLY = ("all_players", "no_player", "no_team")

#: Owners a chain can hang off, as ``(spelling with {n}, how many, what kind of thing it holds)``.
#: Only *top-level* ones: the engine allows a reference to go at most two levels deep (confirmed
#: against the native compiler: ``global.object[0].number[0]`` is fine, ``current_team.player[0].
#: number[0]`` is rejected with "can only go two levels deep"), and ``current_*.<type>[n]`` is already
#: one level in. ``temporaries.object[n]`` and ``team[n]`` are top-level, so they chain.
_CHAIN_OWNERS: tuple[tuple[str, int, str], ...] = (
    ("global.object[{n}]", _POOL_SIZES["global"]["object"], _OBJECT),
    ("global.player[{n}]", _POOL_SIZES["global"]["player"], _PLAYER),
    ("global.team[{n}]", _POOL_SIZES["global"]["team"], _TEAM),
    ("team[{n}]", 8, _TEAM),
    ("neutral_team", 1, _TEAM),  # no index: `neutral_team.object[1]`, the one team constant with a name
    ("killed_object", 1, _OBJECT),
    ("temporaries.object[{n}]", _POOL_SIZES["temporaries"]["object"], _OBJECT),
)

#: Owners that are already one level deep (so nothing but a trailing ``.biped`` may follow the player
#: they hold), as ``(spelling, scope whose player pool sizes the index)``.
_DEEP_BIPED_OWNERS = (
    ("current_team", "team"), ("current_object", "object"), ("current_player", "player"),
)

#: A chain's own tails per owner kind, from the engine's per-scope pool sizes: ``(member, type,
#: how many)``. Kind -> the scope whose pools it carries.
_KIND_SCOPE = {_OBJECT: "object", _PLAYER: "player", _TEAM: "team"}
#: Singular (non-array) properties on top of the arrays.
_KIND_PROPERTIES: dict[str, tuple[tuple[str, str], ...]] = {
    _OBJECT: (("spawn_sequence", _NUMBER), ("team", _TEAM)),
    _PLAYER: (("biped", _OBJECT), ("team", _TEAM), ("score", _NUMBER), ("rating", _NUMBER)),
    _TEAM: (("score", _NUMBER),),
}

#: How each value type is exercised as an *argument slot* of its own (not just as one side of an
#: ``=``): an action or condition whose sole argument is that type. ``{s}`` is the exemplar.
_RECEIVER_FORMS = {
    _OBJECT: "{s}.delete()",
    _TIMER: "{s}.reset()",
    _TEAM: "{s}.set_co_op_spawning(true)",
    _NUMBER: "global.object[0].set_invincibility({s})",
    # A condition, so it needs an ``if`` -- and the body can't be empty: the native compiler drops an
    # empty ``if`` entirely, so there'd be no opcode left to scan the argument out of.
    _PLAYER: "if {s}.is_spartan() then\n   global.number[0] = 1\nend",
    # A "player or group" slot takes a player or a team (or all/none of them).
    "player_or_group": 'game.show_message_to({s}, none, "x")',
}

#: Native caps per variant: max_actions 1024, max_triggers 320 (see TO_IMPLEMENT's "Engine-resource /
#: counter caps"), kept under with headroom. A statement is either "plain" (an action, packed
#: together with the others into one ``do`` block = one trigger) or "top" (a condition or loop, which
#: has to be its own top-level trigger -- see :func:`scripts`).
_ACTION_BUDGET = 900
_TRIGGER_BUDGET = 250
#: A top-level ``if``/``for each`` costs its own trigger plus about three opcodes (condition, the
#: nested-trigger call, the body statement).
_TOP_ACTION_COST = 3


def _chain_shapes() -> Iterator[tuple[str, str]]:
    """``(exact text, value type)`` for every chained reference this pool covers."""
    for spelling, count, kind in _CHAIN_OWNERS:
        scope = _KIND_SCOPE[kind]
        for n in range(count):
            owner = spelling.format(n=n)
            for member, member_type in (("number", _NUMBER), ("timer", _TIMER), ("object", _OBJECT),
                                        ("player", _PLAYER), ("team", _TEAM)):
                for m in range(_POOL_SIZES[scope][member]):
                    yield f"{owner}.{member}[{m}]", member_type
            for prop, prop_type in _KIND_PROPERTIES[kind]:
                yield f"{owner}.{prop}", prop_type
            # The one exception to the two-levels rule: a trailing ``.biped`` doesn't count as a level
            # (confirmed against the native compiler), so a player held *in* a slot can still reach
            # its biped -- ``global.object[0].player[0].biped`` is everywhere in real scripts.
            for m in range(_POOL_SIZES[scope]["player"]):
                yield f"{owner}.player[{m}].biped", _OBJECT
    for spelling, scope in _DEEP_BIPED_OWNERS:
        for n in range(_POOL_SIZES[scope]["player"]):
            yield f"{spelling}.player[{n}].biped", _OBJECT


def _normalized_shapes() -> Iterator[tuple[str, str]]:
    """``(text with index 0, value type)`` for every ``<prefix>.<type>[N]`` shape the compiler
    normalizes -- one exemplar each, since the compiler retargets the index."""
    for prefix, scope in _SELF_PREFIXES.items():
        for member_type, size in _POOL_SIZES[scope].items():
            if size > 0:
                yield f"{prefix}.{member_type}[0]", member_type
    yield "team[0]", _TEAM
    # Only meaningful inside a HUD widget, but the compiler accepts (and needs a template for) them
    # anywhere -- confirmed against the native compiler.
    yield "hud_player.number[0]", _NUMBER
    yield "hud_player.timer[0]", _TIMER


def _plain_shapes() -> Iterator[tuple[str, str]]:
    for value_type, names in _PLAIN_SHAPES.items():
        for name in names:
            yield name, value_type


def _statements_for(shape: str, value_type: str) -> Iterator[tuple[str, str]]:
    """``(statement, cost class)`` exercising ``shape`` in every argument family it can occupy."""
    yield f"{_ANCHOR[value_type]} = {shape}", "plain"  # the "_any_variable" family (and its own type's)
    form = _RECEIVER_FORMS.get(value_type)
    if form is not None:
        yield form.format(s=shape), "top" if form.startswith("if") else "plain"
    if value_type in (_PLAYER, _TEAM):
        yield _RECEIVER_FORMS["player_or_group"].format(s=shape), "plain"


def statements() -> list[tuple[str, str]]:
    """Every ``(statement, cost class)`` in this pool, deterministically ordered, duplicates removed."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for shapes in (_plain_shapes(), _normalized_shapes(), _chain_shapes()):
        for shape, value_type in shapes:
            for statement, cost in _statements_for(shape, value_type):
                if statement not in seen:
                    seen.add(statement)
                    out.append((statement, cost))
    # Not shapes at all, but examples the compiler also clones from: a bare integer literal in each
    # kind of slot that takes one, and a real "Run Nested Trigger" call (what a ``for each`` compiles
    # to) -- neither exists in a blank variant, and both are needed by nearly every script.
    for statement, cost in (
        ("global.number[0] = 1", "plain"),
        ("global.object[0].set_invincibility(1)", "plain"),
        # The null constants: assignable like any value, but (unlike ``no_object``) they have no
        # members, so none of the receiver forms above apply to them -- see ``_GROUP_ONLY``.
        ("global.player[0] = no_player", "plain"),
        ("global.team[0] = no_team", "plain"),
        # Nested on purpose: a *top-level* ``for each`` sets a block type on its own trigger instead
        # of calling a nested one, so only the inner loop yields a "Run Nested Trigger" opcode.
        ("for each player do\n   for each object do\n      global.number[0] = 1\n   end\nend", "top"),
    ):
        if statement not in seen:
            seen.add(statement)
            out.append((statement, cost))
    for shape in _GROUP_ONLY:
        statement = _RECEIVER_FORMS["player_or_group"].format(s=shape)
        if statement not in seen:
            seen.add(statement)
            out.append((statement, "plain"))
    return out


def scripts() -> list[str]:
    """The pool as Megalo script text, split into as few scripts as fit the engine's per-variant caps.

    Plain statements share one ``on init: do`` block (one trigger, however many statements). A
    condition or loop can't: the native compiler only leaves an ``if``'s condition in its trigger's
    own opcode list -- where :func:`~in_reach.app.rvt.megalo_compiler._scan_templates` can find it --
    when nothing follows it in the same trigger (confirmed by experiment: the same ``if`` followed by
    any other statement is nested inside an inline scope instead, which the scan doesn't enter). So
    each one is its own top-level statement, i.e. its own trigger.
    """
    chunks: list[tuple[list[str], list[str]]] = [([], [])]
    actions = 0
    for statement, cost in statements():
        plain, top = chunks[-1]
        weight = 1 if cost == "plain" else _TOP_ACTION_COST
        if actions + weight > _ACTION_BUDGET or (cost == "top" and len(top) >= _TRIGGER_BUDGET):
            plain, top = [], []
            chunks.append((plain, top))
            actions = 0
        (plain if cost == "plain" else top).append(statement)
        actions += weight
    out = []
    for plain, top in chunks:
        lines = [line for statement in plain for line in statement.split("\n")]
        block = "on init: do\n" + "\n".join("   " + line for line in lines) + "\nend\n" if plain else ""
        out.append(block + "".join(statement + "\n" for statement in top))
    return out


def build_variants(rvt) -> list:
    """Compiles each of :func:`scripts` (natively, against the packaged blank multiplayer variant --
    which needs no templates to do it) and returns the resulting variants, ready to hand to
    :func:`~in_reach.app.rvt.megalo_compiler.compile_script` as its ``template_pool``.

    Raises:
        RuntimeError: If the native compiler rejects one of the generated scripts. That's a bug in
            this module's own tables (see ``tests/app/rvt/test_template_source.py``, which compiles
            them all), never something a user's script can cause.
    """
    from in_reach.app.blank_variant import resolve_blank_variant

    base = str(resolve_blank_variant(firefight=False))
    variants = []
    for script in scripts():
        variant = rvt.load(base)
        result = variant.multiplayer.compile_script(script)
        if not result.success:
            problems = [m.text for m in list(result.fatal_errors) + list(result.errors)]
            raise RuntimeError(f"template pool failed to compile natively: {problems[:3]}")
        variants.append(variant)
    return variants
