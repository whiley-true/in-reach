"""A from-scratch Megalo script(text) -> native-object compiler (PROMPT.md: "we want a fromm
scratch compiler then").

## Why this exists

``mp.compile_script()`` (the native compiler bound into ``_reachvarianttool``) makes its own
non-configurable decision about whether a nested ``if`` block compiles as an "inline trigger" or an
ordinary separate nested trigger (``bInlineIfs``, hardcoded ``true`` in ``compiler.cpp``, not exposed
through this app's binding) -- confirmed directly by reading that C++ source and by reproducing it:
recompiling a real, playable, completely unedited ``.bin`` can silently change its trigger/action
counts (25 triggers/92 actions -> 19/91 for the ``juggernaut`` fixture; 1013 -> 1052 actions for a
real user map, enough to blow through the engine's 1024-action cap on a script that was already
correct). There is no config knob for this -- the fix has to be a compiler that decides trigger
structure itself rather than asking the native one to decide it after the fact.

This module builds real ``Trigger``/``Condition``/``Action``/``OpcodeArgValue`` objects directly via
the native construction API (``MultiplayerData.add_trigger()``, ``Condition()``/``Action()``,
``.function =``, ``add_argument()``, ``CodeBlock.add_opcode()``) -- bypassing ``compile_script()``'s
text parsing and its own inlining decision entirely. See ``tests/app/rvt/
test_megalo_engine_ast_bindings.py`` for the direct evidence every construction primitive here is
built on (every one of them confirmed to persist correctly through a real save/reload before this
module was written, not assumed).

## Scope of this pass

A real, but still bounded, subset. Anything outside it raises :class:`UnsupportedConstruct`; the
caller (:mod:`in_reach.app.rvt.compile`) catches it and falls back to ``mp.compile_script(source)``
unchanged, so nothing outside this slice regresses.

Supported:

- Variable references across every scope this engine actually has a pool for --
  ``global``/``player``/``object``/``team``/``temporaries``, plus the ``current_player``/
  ``current_object``/``current_team`` self-references, plus ``team[N]`` (a specific team constant,
  0-7) and the ``no_player``/``no_object``/``no_team``/``none`` null constants.
- A property chained off an already-resolved variable value (``global.player[4].biped``,
  ``current_player.team``, ...). These can't be built by clone-and-retarget at all -- confirmed
  directly that a property's ``.which`` value opaquely packs *both* the owning variable's own slot
  and the property together, with no derivable formula (see ``_build_opaque_variable_arg``'s own
  docstring) -- so they're matched by exact literal text against a real example already present
  somewhere in the variant's own script instead. Only reaches whatever exact chains the variant's
  own script already uses somewhere; a chain it never uses at all is still
  :class:`UnsupportedConstruct`, not a crash.
- Plain integer literals.
- Assignment, including every compound operator (``=``/``+=``/``-=``/``*=``/``/=``/``%=``).
- ``if`` conditions: any of ``==``/``!=``/``<``/``>``/``<=``/``>=`` comparisons and/or boolean
  function-style condition calls (e.g. ``current_object.is_of_type(x)``), each optionally negated
  with ``not``, combined with ``and``/``or`` -- but only up to what the engine's own flat ``or_group``
  model can express directly (AND across groups, OR within one group -- confirmed against RCC
  Onslaught v13.bin's own already-compiled conditions): a top-level ``and``-chain where any conjunct
  may itself be a flat ``or``-chain. An ``and`` *nested inside* an ``or`` (e.g. ``(a and b) or c``)
  would need CNF distribution to fit that flat model and isn't supported yet. No ``altif``/``alt``
  clauses, no ``|`` flag-combination.
- ``for each object|player|team do ... end`` loops, including ``for each object with label N do``
  (``N`` an int label index, or a string matched against a real forge label's own name -- see
  ``mark_trigger_forge_label()``'s own docstring in the native source for the block_type/forge_label
  pairing this needs).
- Any call whose target action/condition function has ``mapping.type == function`` (i.e. renders as
  ``<context>.<name>(<args>)`` or a bare ``<name>(<args>)``) -- covers a large, genuinely general
  slice of real actions/conditions (``is_of_type``, ``get_distance_to``, ``delete``, ``rand``,
  ``attach_to``, etc.) without hand-listing each one, including a ``Vector3``-typed argument slot
  written as three bare call-syntax numbers (e.g. ``attach_to``'s own ``offset``, confirmed directly
  against ``Vector3Argument.x``/``.y``/``.z``). Any *other* multi-value collapsing this compiler
  doesn't know about is still caught safely by the positional-argument-count check, rather than
  silently miscompiling.
- ``declare`` statements are parsed and validated (scope/type/index in range) but otherwise treated
  as a no-op -- Megalo's own real semantics for these are compile-time bookkeeping (network
  replication priority/initial-value hints), not a runtime opcode; not reproducing the priority/
  initial-value metadata is a real, deliberate limitation of this pass, not an oversight.
- ``function <name>() ... end`` top-level, named, multi-caller subroutines and bare ``<name>()``
  calls to them (void only -- real Megalo functions don't return a value, so a call to one is only
  valid as its own statement, never assigned or used as a condition). Compiled in two passes: every
  function gets its own subroutine trigger allocated *before* any body is compiled, so forward
  references and functions calling each other both resolve regardless of declaration order.
- ``on <event>: <statement>`` for ``init``/``local init``/``host migration``/``object death``/
  ``local``/``pregame`` (matching ``TriggerEntryType``'s own event members) -- top level only, real
  Megalo has no nested event bindings.

Not supported (raises :class:`UnsupportedConstruct`): ``alias``, ``|`` flag-combination, nested calls
used as a sub-expression of another call/condition, and anything not listed above.

## Constructing variable references: clone-and-retarget

``Variable``-family types (``ScalarVariable`` etc.) have no constructor at all
(``TypeError: No constructor defined!``), and ``Variable.scope`` has no setter -- there is no way to
build a freely-scoped variable reference from nothing. What *does* work, confirmed directly: cloning
an existing, real variable reference (``.clone()``) and retargeting its ``.index`` (writable, unlike
``.scope``) -- both for a real variable slot (``global.number[N]``) and, less obviously, for an
integer *literal*: a plain int like the ``1`` in ``current_player.number[0] = 1`` is *also* an
``AnyVariable``-wrapped ``ScalarVariable``, just with a different, readonly "constant" scope (format
``"%i"`` instead of ``"%w.number[%i]"``) whose own ``.index`` doubles as the literal's numeric value
rather than a pool slot -- same clone-then-retarget mechanism, just a different template source.

Templates are self-sourced from the *same* variant being compiled (see :func:`_scan_templates`) --
deliberately not a bundled reference ``.bin`` (sidesteps any question about redistribution rights
over someone else's gametype), and more correct besides: a project's own script always has real
examples of whatever variable kinds it actually uses, in the exact engine-version/format this compile
targets. Different argument *slots* expect different concrete classes for what looks like "the same"
reference (e.g. a generic assign/compare operand is ``AnyVariable``-wrapped, but a slot specifically
typed for an object is a bare ``ObjectVariable`` with no wrapper) -- templates are keyed by
``(argument slot's own typeinfo internal_name, normalized reference shape)`` so the clone always
matches what that exact slot expects, not just what the reference conceptually means. If a needed
template genuinely isn't present anywhere in the variant's own script, that's
:class:`UnsupportedConstruct`, not a crash.

Retargeting an ``ObjectVariable``/``PlayerVariable``/``TeamVariable`` needs a different field than a
``ScalarVariable``/``TimerVariable`` does, and using the wrong one is a genuine, confirmed native
binding gap, not a guess: these types don't use ``.index`` as their pool slot at all (``scope.
has_index`` is ``False`` for them) -- they use ``.which``, a lookup value into a fixed engine enum
that also holds the self/null markers, offset from the pool slot by a fixed-but-undocumented amount
per type (confirmed empirically: ``global.object[N]`` -> ``which = N + 1``; ``global.player[N]`` ->
``which = N + 17``). Setting ``.index`` on one of these instead reads back as set but silently
doesn't affect what actually saves/decompiles. :func:`_retarget` derives the right offset from the
template itself rather than hardcoding it per type (see its own docstring) and still verifies every
retarget by decompiling the result and confirming the index actually changed -- this compiler would
rather raise :class:`UnsupportedConstruct` than risk emitting silently-wrong bytecode for some other
argument type this reasoning doesn't cover.

Per-scope pool sizes (confirmed in ``TO_IMPLEMENT_(LATEST).md``'s own "Storage pools" table, itself
read from the vendored ``variables_and_scopes.cpp``) are checked before ever handing an index to the
engine -- an out-of-range index silently clamps rather than erroring at the engine level, not
guessed at.

## Enum-style constants: brute-force reverse lookup

Named constants used as call arguments (``is_of_type(plasma_cannon)``, ``attach_to(..., relative)``)
resolve through a real, if unglamorous, mechanism: construct one fresh instance of the argument's own
type via ``typeinfo.create()`` (confirmed to work for these -- unlike ``Variable``, these DO have a
real default constructor), then try ``.value = 0, 1, 2, ...`` until ``.decompile(variant)`` produces
the exact identifier text wanted (or raises, meaning the value range has been exhausted). This
binding exposes no name -> value table directly for these argument families, so this is the general
mechanism available without hand-enumerating every one -- confirmed directly against a real
``is_of_type(plasma_cannon)`` usage (index 170 in the ``_object_type`` family) before being written.

## Constructing nested triggers: entry_type=subroutine / block_type

Confirmed by reading ``compiler.cpp``'s own ``Block::compile()``: *every* block nested inside another
non-root block gets ``entryType = subroutine`` unconditionally, or the engine would tick it
independently *in addition to* running it via "Run Nested Trigger" -- a real double-execution bug.
Neither ``Trigger.entry_type`` nor ``Trigger.block_type`` had a setter in the native binding (not
even in the upstream source this was ported from) and ``bind_trigger_as_event()`` explicitly can't
set 'subroutine' either -- a genuine binding gap, not a workaround-able one, closed by adding
``MultiplayerData.mark_trigger_as_subroutine()``/``mark_trigger_block_type()`` to ``bindings.cpp`` and
rebuilding the bundled ``.pyd`` (see those methods' own docstrings in the native source). Every nested
``if``/``for each`` body this module builds is always its own ordinary subroutine trigger -- never
inline -- which is what actually closes the ``bInlineIfs`` gap: this compiler never delegates that
decision to the native compiler at all. ``for each`` loops always get their own trigger too (even at
the top level, where the native compiler would instead set block_type directly on the containing
trigger) -- less minimal, but uniformly correct and much simpler to implement once.

## Failure must not leave partial state

``MultiplayerData`` has no way to remove or clear an individual ``Trigger`` once added -- only
``add_trigger()`` (append-only). If this module raises :class:`UnsupportedConstruct` partway through
a compile, the ``variant`` object passed in may already carry partially-built triggers that can never
be un-added. **The caller must discard that ``variant`` entirely and load a fresh one** before falling
back to ``mp.compile_script(source)`` -- reusing the same, now-partially-mutated object is not safe.
See :mod:`in_reach.app.rvt.compile`'s own fallback for the reload this requires.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .megalo_ast import parse
from .megalo_ast.lexer import MegaloLexError
from .megalo_ast.parser import MegaloParseError
from .megalo_ast.unparse import render_expr

# scope -> {type: pool size}, straight from TO_IMPLEMENT_(LATEST).md's "Storage pools" table
# ("temporary (per-trigger scratch)" there is spelled "temporaries" in real Megalo source text).
_POOL_SIZES: dict[str, dict[str, int]] = {
    "global": {"number": 12, "timer": 8, "team": 8, "player": 8, "object": 16},
    "player": {"number": 8, "timer": 4, "team": 4, "player": 4, "object": 4},
    "object": {"number": 8, "timer": 4, "team": 2, "player": 4, "object": 4},
    "team": {"number": 8, "timer": 4, "team": 4, "player": 4, "object": 6},
    "temporaries": {"number": 10, "timer": 0, "team": 6, "player": 3, "object": 8},
}
_TEAM_CONSTANT_COUNT = 8  # team[0..7] -- Halo Reach's own fixed team count, not a per-scope pool.
_SELF_SCOPE_ALIAS = {"current_player": "player", "current_object": "object", "current_team": "team"}
_BARE_CONSTANT_NAMES = frozenset(
    {"current_player", "current_object", "current_team", "no_player", "no_object", "no_team", "none"}
)

# Confirmed empirically against real, already-compiled opcodes (not guessed) -- juggernaut.bin for
# "="/"=="/"!=", RCC Onslaught v13.bin (a real, complex, user-supplied gametype) for "<"/">"/"<="/
# ">=" and every compound assignment operator. Modify Variable's/Compare's third argument
# ("operator") is a plain int.
_ASSIGN_OPERATOR_VALUES = {"+=": 0, "-=": 1, "*=": 2, "/=": 3, "=": 4, "%=": 5}
_COMPARE_OPERATOR_VALUES = {"<": 0, ">": 1, "==": 2, "<=": 3, ">=": 4, "!=": 5}

_FOR_EACH_BLOCK_TYPES = {"object", "player", "team"}  # -> TriggerBlockType.for_each_<kind>

# "on <event>:" text -> TriggerEntryType member name -- confirmed against RCC Onslaught v13.bin's
# own real "on init:"/"on local:" usage; the rest match TriggerEntryType's own naming 1:1.
_EVENT_ENTRY_TYPES = {
    "init": "on_init",
    "local init": "on_local_init",
    "host migration": "on_host_migration",
    "object death": "on_object_death",
    "local": "local",
    "pregame": "pregame",
}

_ENUM_BRUTE_FORCE_LIMIT = 4096


class UnsupportedConstruct(Exception):
    """Raised for anything outside this compiler's supported subset (see module docstring) -- a
    parse error, a statement/expression kind not yet implemented, a variable reference this compiler
    doesn't support, an out-of-range index, or a template this variant's own script doesn't have an
    example of to source from. The caller must treat ``variant`` as possibly already partially
    mutated and reload a fresh one before falling back to the native compiler -- see this module's
    own "Failure must not leave partial state" docs.
    """


def _decompiled_key(rvt, arg, text: str) -> str:
    """``"team.object[3]"`` -> ``"team.object[]"``; ``"current_player"`` unchanged (no index to
    normalize away); a literal-constant-scope variable (the ``1`` in ``current_player.number[0] =
    1`` -- confirmed earlier this session to be an ``AnyVariable``-wrapped ``ScalarVariable`` with a
    readonly "%i"-format scope, not a plain int argument type) -> the fixed key ``"INT_LITERAL"``
    regardless of its actual value, since the value itself varies per compile and can't be part of a
    stable template key."""
    inner = arg.variable if hasattr(arg, "variable") else arg
    if isinstance(inner, rvt.ScalarVariable) and inner.scope.format == "%i":
        return "INT_LITERAL"
    m = re.fullmatch(r"(.+)\[-?\d+\]", text)
    return f"{m.group(1)}[]" if m else text


@dataclass
class _Templates:
    # {(argument slot's typeinfo.internal_name, normalized reference shape): template arg}
    variables: dict[tuple[str, str], object] = field(default_factory=dict)
    # {(typeinfo.internal_name, exact decompiled text): template arg} -- see _build_variable_arg's
    # "opaque literal match" fallback for why this exists alongside the normalized dict above.
    literal_variables: dict[tuple[str, str], object] = field(default_factory=dict)
    trigger_ref: object | None = None


def _scan_templates(rvt, variant, mp) -> _Templates:
    """Sources real, already-valid argument instances from ``mp``'s own existing script to
    clone-and-retarget from -- see module docstring's "Constructing variable references" section for
    why this is self-sourced rather than bundled. Only scans each opcode's own direct arguments, not
    inside nested ``MegaloScopeArgument``/inline-trigger sub-opcodes -- a real, if minor, gap (see
    module docstring).
    """
    templates = _Templates()
    for ti in range(mp.trigger_count):
        trigger = mp.trigger(ti)
        for oi in range(trigger.opcode_count):
            opcode = trigger.opcode(oi)
            function = opcode.function
            arg_infos = function.arguments
            argument_count = min(opcode.argument_count, len(arg_infos))
            for ai in range(argument_count):
                arg = opcode.argument(ai)
                if templates.trigger_ref is None and isinstance(arg, rvt.TriggerArgument):
                    templates.trigger_ref = arg
                    continue
                try:
                    text = arg.decompile(variant)
                except Exception:  # noqa: BLE001 -- some argument kinds can't decompile in isolation
                    continue
                typeinfo_name = arg_infos[ai].typeinfo.internal_name
                templates.variables.setdefault((typeinfo_name, _decompiled_key(rvt, arg, text)), arg)
                templates.literal_variables.setdefault((typeinfo_name, text), arg)
    return templates


def _retarget(variant, template_arg, index: int):
    """Clones ``template_arg`` and retargets it to ``index``.

    Confirmed directly by reading the vendored engine source (``opcode_arg_types/variables/base.h``'s
    own big "MEGALO VARIABLES" comment block) -- there are genuinely two different encodings, not
    one: a scalar/timer slot (``global.number[3]``) uses ``.index`` directly as the pool slot, but an
    object/player/team slot (``global.object[3]``) instead uses ``.which`` -- a *lookup value* into a
    fixed, engine-defined enum that also contains the self/null markers (``current_object``,
    ``no_object``, ...), not the raw pool slot number itself. ``.index`` genuinely doesn't exist for
    these (``scope.has_index`` is ``False``) -- confirmed setting it reads back as set but silently
    doesn't affect what decompiles/saves, a real native binding gap, not a Python-side mistake (spot
    checked through a real save/reload, not just in memory).

    The good news: for an ordinary top-level pool reference (not a self/null marker), ``.which`` is
    confirmed to be the pool slot plus a fixed, per-type offset (``global.object[N]`` -> ``which = N +
    1``; ``global.player[N]`` -> ``which = N + 17``) -- not documented anywhere, but empirically
    linear and consistent within a type. Rather than hardcode those two numbers (and guess at every
    other variable type's own offset), the offset is derived from the template itself: it already
    carries a real ``(text-index, which)`` pair, so ``offset = template.which - text_index`` and the
    new ``which = offset + index`` generalizes to every object/player/team-style type without
    needing to know its specific offset in advance.

    Every retarget is still verified by decompiling the clone and confirming the index actually
    changed, regardless of which field was written -- raising :class:`UnsupportedConstruct` instead
    of trusting a property's own read-back, in case some other argument type has a similar gap this
    reasoning doesn't cover.
    """
    original_text = template_arg.decompile(variant)
    # An indexed reference ("team.object[3]") expects "...[{index}]" after retargeting; a bare
    # literal-scope constant (format "%i", decompiles as a plain digit with no brackets at all, see
    # module docstring's "Constructing variable references" section) expects just str(index).
    m = re.fullmatch(r"(.+)\[(-?\d+)\]", original_text)
    expected_text = f"{m.group(1)}[{index}]" if m else str(index)

    clone = template_arg.clone()
    inner = clone.variable if hasattr(clone, "variable") else clone
    if m is not None and not inner.scope.has_index and inner.scope.has_which:
        original_index = int(m.group(2))
        inner.which = (inner.which - original_index) + index
    else:
        inner.index = index
    try:
        text = clone.decompile(variant)
    except Exception:  # noqa: BLE001 -- treat "can't even decompile" the same as "didn't take"
        text = None
    if text != expected_text:
        raise UnsupportedConstruct(
            "this argument slot's variable reference can't be safely retargeted to a different "
            "index -- confirmed a native binding limitation for this specific argument type"
        )
    return clone


def _normalize_ast_ref(expr) -> tuple[str, int | None] | None:
    """AST expression -> ``(normalized shape key, index or None)``, matching :func:`_decompiled_key`
    exactly, or ``None`` if ``expr`` isn't a reference shape this compiler resolves at all (not
    "unsupported reference", just "not a reference -- try something else with it")."""
    if expr.kind == "int":
        return "INT_LITERAL", expr.value
    if expr.kind == "identifier" and expr.name in _BARE_CONSTANT_NAMES:
        return expr.name, None
    if expr.kind == "index" and expr.index.kind == "int":
        n = expr.index.value
        target = expr.target
        if target.kind == "identifier" and target.name == "team":
            return "team[]", n
        if target.kind == "member" and target.target.kind == "identifier":
            prefix = target.target.name
            if prefix in _POOL_SIZES or prefix in _SELF_SCOPE_ALIAS:
                return f"{prefix}.{target.name}[]", n
    if expr.kind == "member" and expr.target.kind == "identifier":
        # A singular, non-array-indexed property, e.g. "current_player.team" (confirmed directly:
        # scope.format == "%w.team", no "[%i]" suffix at all -- a player has exactly one team, not
        # an array of them). No index to retarget or range-check; clone the template as-is, same as
        # a bare constant keyword.
        prefix = expr.target.name
        if prefix in _POOL_SIZES or prefix in _SELF_SCOPE_ALIAS:
            return f"{prefix}.{expr.name}", None
    return None


def _pool_size_for_key(key: str) -> int | None:
    if key == "team[]":
        return _TEAM_CONSTANT_COUNT
    m = re.fullmatch(r"([a-z_]+)\.([a-z]+)\[\]", key)
    if not m:
        return None
    prefix, type_name = m.groups()
    scope = _SELF_SCOPE_ALIAS.get(prefix, prefix)
    return _POOL_SIZES.get(scope, {}).get(type_name)


def _find_function(rvt, *, name: str | None = None, primary_name: str | None = None, condition: bool):
    count = rvt.condition_function_count() if condition else rvt.action_function_count()
    get = rvt.condition_function if condition else rvt.action_function
    for i in range(count):
        f = get(i)
        if name is not None and f.name == name:
            return f
        if primary_name is not None and f.mapping.type.name == "function" and f.mapping.primary_name == primary_name:
            return f
    return None


class _Compiler:
    def __init__(self, rvt, variant):
        self._rvt = rvt
        self._variant = variant
        self._mp = variant.multiplayer
        self._templates = _scan_templates(rvt, variant, self._mp)
        self._enum_cache: dict[tuple[str, str], int] = {}
        self._functions: dict[str, int] = {}  # name -> its own pre-allocated subroutine trigger index
        self._modify_variable = self._require_action("Modify Variable")
        self._compare = self._require_condition("Compare")
        self._run_nested_trigger = self._require_action("Run Nested Trigger")

    def _require_action(self, name: str):
        f = _find_function(self._rvt, name=name, condition=False)
        if f is None:
            raise UnsupportedConstruct(f"engine has no action function named {name!r}")
        return f

    def _require_condition(self, name: str):
        f = _find_function(self._rvt, name=name, condition=True)
        if f is None:
            raise UnsupportedConstruct(f"engine has no condition function named {name!r}")
        return f

    def compile(self, script) -> None:
        # Two passes: allocate every named function's own subroutine trigger FIRST (so a call to a
        # function declared later in the file, or one function calling another, both resolve
        # correctly), then compile bodies -- the top-level trigger's own content, then each
        # function's own body against the now-fully-populated name table.
        function_decls = [s for s in script.body if s.kind == "function"]
        for decl in function_decls:
            if decl.name in self._functions:
                raise UnsupportedConstruct(f"duplicate function declaration {decl.name!r}")
            self._mp.add_trigger()
            index = self._mp.trigger_count - 1
            self._mp.mark_trigger_as_subroutine(index)
            self._functions[decl.name] = index

        event_triggers = [s for s in script.body if s.kind == "on"]
        top = self._mp.add_trigger()
        other_statements = [s for s in script.body if s.kind not in ("function", "on")]
        self._compile_statements(other_statements, top)

        for decl in function_decls:
            self._compile_statements(decl.body, self._mp.trigger(self._functions[decl.name]))

        for event_stmt in event_triggers:
            self._compile_event_trigger(event_stmt)

    def _compile_event_trigger(self, stmt) -> None:
        # "on <event>: <statement>" is top-level only -- real Megalo has no nested event bindings.
        entry_type = _EVENT_ENTRY_TYPES.get(stmt.event)
        if entry_type is None:
            raise UnsupportedConstruct(f"event {stmt.event!r} is not supported yet")
        self._mp.add_trigger()
        index = self._mp.trigger_count - 1
        self._mp.bind_trigger_as_event(index, getattr(self._rvt.TriggerEntryType, entry_type))
        self._compile_statement(stmt.body, self._mp.trigger(index))

    def _compile_statements(self, statements, trigger) -> None:
        for stmt in statements:
            self._compile_statement(stmt, trigger)

    def _compile_statement(self, stmt, trigger) -> None:
        if stmt.kind == "assign":
            self._compile_assign(stmt, trigger)
        elif stmt.kind == "if":
            self._compile_if(stmt, trigger)
        elif stmt.kind == "expr_stmt":
            self._compile_call_statement(stmt.expr, trigger, out_target=None)
        elif stmt.kind == "for_each":
            self._compile_for_each(stmt, trigger)
        elif stmt.kind == "do":
            self._compile_nested_body(stmt.body, trigger)
        elif stmt.kind == "declare":
            self._compile_declare(stmt)
        else:
            raise UnsupportedConstruct(f"statement kind {stmt.kind!r} is not supported yet")

    # -- variable/constant reference resolution -----------------------------------------------

    def _build_variable_arg(self, expr, typeinfo):
        ref = _normalize_ast_ref(expr)
        if ref is None:
            return self._build_opaque_variable_arg(expr, typeinfo)
        key, index = ref
        pool_size = _pool_size_for_key(key)
        if pool_size is not None and not (0 <= (index or 0) < pool_size):
            shown = key.replace("[]", f"[{index}]")
            raise UnsupportedConstruct(f"{shown} is out of range (pool size {pool_size})")
        template = self._templates.variables.get((typeinfo.internal_name, key))
        if template is None:
            if key == "INT_LITERAL":
                # A plain int literal isn't only ever a literal-scope Variable -- some enum-typed
                # slots (e.g. an object type the decompiler has no friendly name for, confirmed a
                # real case: "place_at_me(280, ...)") use a bare number directly instead. Let the
                # caller's own enum-resolution fallback have a try before giving up.
                return None
            raise UnsupportedConstruct(
                f"this variant's own script has no existing {key!r}-shaped reference in a "
                f"{typeinfo.internal_name!r}-typed argument slot to source a template from"
            )
        return template.clone() if index is None else _retarget(self._variant, template, index)

    def _build_opaque_variable_arg(self, expr, typeinfo):
        """A reference shape this compiler doesn't structurally parse -- most importantly, a
        property chained off an already-resolved variable value (``global.player[4].biped``).
        Confirmed directly (not assumed): a ``.biped``-style property's ``.which`` value packs
        *both* the owning variable's own slot and the property together into one opaque number with
        no derivable formula (e.g. ``global.player[4].biped`` decompiles correctly with ``which=21,
        index=0`` -- "4" appears nowhere retrievable) -- so this can't be resolved via
        clone-and-retarget at all. Instead it's matched by *exact* literal text against a real
        example already present somewhere in the variant's own script (see ``_Templates.
        literal_variables``) and cloned as-is, no retargeting. If the variant doesn't already
        reference this exact chain somewhere, it's :class:`UnsupportedConstruct` via the caller's
        own fallback (returning ``None`` here), not a crash.
        """
        try:
            text = render_expr(expr)
        except ValueError:
            return None
        template = self._templates.literal_variables.get((typeinfo.internal_name, text))
        return template.clone() if template is not None else None

    def _build_enum_arg(self, expr, typeinfo):
        if expr.kind == "int":
            # Some enum-typed slots use a bare number directly for a value the decompiler has no
            # friendly name for (confirmed a real case: object type 280 in "place_at_me(280, ...)")
            # -- verified the same way as _retarget(), not trusted blindly.
            trial = typeinfo.create()
            try:
                trial.value = expr.value
                text = trial.decompile(self._variant)
            except Exception:  # noqa: BLE001
                return None
            return trial if text == str(expr.value) else None
        if expr.kind != "identifier":
            return None
        cache_key = (typeinfo.internal_name, expr.name)
        cached = self._enum_cache.get(cache_key)
        if cached is not None:
            trial = typeinfo.create()
            trial.value = cached
            return trial
        trial = typeinfo.create()
        for k in range(_ENUM_BRUTE_FORCE_LIMIT):
            trial.value = k
            try:
                text = trial.decompile(self._variant)
            except Exception:  # noqa: BLE001 -- signals "value out of range for this enum family"
                break
            if text == expr.name:
                self._enum_cache[cache_key] = k
                return trial
        return None

    def _build_forge_label_arg(self, expr, typeinfo):
        # ForgeLabelArgument.value has no setter at all -- confirmed a real binding gap, fixed the
        # same way as Trigger.forgeLabel (see mark_trigger_forge_label()'s own docstring): a
        # dedicated set_value(mp, label_index) method. "none" needs no lookup at all -- a freshly
        # create()'d instance already decompiles as "none" by default (confirmed directly).
        if typeinfo.internal_name != "_forge_label":
            return None
        if expr.kind == "identifier" and expr.name == "none":
            return typeinfo.create()
        if expr.kind in ("int", "string"):
            arg = typeinfo.create()
            arg.set_value(self._mp, self._resolve_forge_label_index(expr))
            return arg
        return None

    def _build_argument(self, expr, typeinfo):
        built = self._build_forge_label_arg(expr, typeinfo)
        if built is not None:
            return built
        built = self._build_variable_arg(expr, typeinfo)
        if built is not None:
            return built
        built = self._build_enum_arg(expr, typeinfo)
        if built is not None:
            return built
        raise UnsupportedConstruct(
            f"no way to build a {typeinfo.internal_name!r} argument from expression kind {expr.kind!r}"
        )

    def _build_trigger_ref(self, child_index: int):
        if self._templates.trigger_ref is None:
            raise UnsupportedConstruct(
                "this variant's own script has no existing 'Run Nested Trigger' call to source a "
                "template from"
            )
        arg = self._templates.trigger_ref.clone()
        arg.value = child_index
        return arg

    # -- declare (validated, no-op) ------------------------------------------------------------

    def _compile_declare(self, stmt) -> None:
        if stmt.scope not in _POOL_SIZES:
            raise UnsupportedConstruct(f"declare scope {stmt.scope!r} is not supported yet")
        pool_size = _POOL_SIZES[stmt.scope].get(stmt.type)
        if pool_size is None or not (0 <= stmt.index < pool_size):
            raise UnsupportedConstruct(
                f"declare {stmt.scope}.{stmt.type}[{stmt.index}] is out of range (pool size {pool_size})"
            )
        # Real Megalo semantics for `declare` are compile-time-only bookkeeping (network replication
        # priority/initial-value hints) -- see module docstring's own "declare" bullet for why this
        # is deliberately a no-op beyond validation, not a partial implementation.

    # -- assignment -----------------------------------------------------------------------------

    def _compile_assign(self, stmt, trigger) -> None:
        if stmt.op not in _ASSIGN_OPERATOR_VALUES:
            raise UnsupportedConstruct(f"assignment operator {stmt.op!r} is not supported yet")
        if stmt.value.kind == "call":
            if stmt.op != "=":
                raise UnsupportedConstruct(
                    f"a call result can only be plain-assigned ('='), not {stmt.op!r}"
                )
            self._compile_call_statement(stmt.value, trigger, out_target=stmt.target)
            return

        target_arg = self._build_argument(stmt.target, self._modify_variable.arguments[0].typeinfo)
        value_arg = self._build_argument(stmt.value, self._modify_variable.arguments[1].typeinfo)

        action = self._rvt.Action()
        action.function = self._modify_variable
        action.add_argument(target_arg)
        action.add_argument(value_arg)
        operator_arg = self._modify_variable.arguments[2].typeinfo.create()
        operator_arg.value = _ASSIGN_OPERATOR_VALUES[stmt.op]
        action.add_argument(operator_arg)
        trigger.add_opcode(action)

    # -- generic function-mapped call dispatch (actions and conditions) -------------------------

    def _split_call_target(self, expr):
        """``obj.method(...)`` -> ``(obj_expr, "method")``; ``method(...)`` (no context) ->
        ``(None, "method")``; anything else -> ``None`` (not a resolvable call target)."""
        if expr.kind == "member":
            return expr.target, expr.name
        if expr.kind == "identifier":
            return None, expr.name
        return None

    def _compile_call_statement(self, expr, trigger, *, out_target) -> None:
        if expr.kind != "call":
            raise UnsupportedConstruct(f"expression kind {expr.kind!r} is not a supported call statement")
        split = self._split_call_target(expr.target)
        if split is None:
            raise UnsupportedConstruct("this call's target shape is not supported yet")
        context_expr, method_name = split

        if context_expr is None and method_name in self._functions:
            # A call to a named, top-level `function ... end` declaration (see compile()'s own
            # two-pass allocation) -- these are void, real Megalo has no way to return a value from
            # one, so this is only ever valid as a bare call statement.
            if out_target is not None:
                raise UnsupportedConstruct(f"function {method_name!r} has no result to assign")
            if expr.args:
                raise UnsupportedConstruct(f"function {method_name!r} takes no arguments")
            call_action = self._rvt.Action()
            call_action.function = self._run_nested_trigger
            call_action.add_argument(self._build_trigger_ref(self._functions[method_name]))
            trigger.add_opcode(call_action)
            return

        function = _find_function(self._rvt, primary_name=method_name, condition=False)
        if function is None:
            raise UnsupportedConstruct(f"no action function found for call {method_name!r}")
        action = self._emit_function_opcode(function, context_expr, expr.args, out_target=out_target, is_condition=False)
        trigger.add_opcode(action)

    def _build_vector3_argument(self, xyz_exprs, typeinfo):
        values = []
        for e in xyz_exprs:
            if e.kind != "int":
                raise UnsupportedConstruct("Vector3 call-syntax components must be plain integer literals")
            values.append(e.value)
        vec = typeinfo.create()
        vec.x, vec.y, vec.z = values
        return vec

    def _emit_function_opcode(self, function, context_expr, call_args, *, out_target, is_condition: bool):
        arg_infos = function.arguments
        context_index = function.mapping.arg_context
        out_index = next((i for i, a in enumerate(arg_infos) if a.is_out_variable), None)

        if (context_index != -1) != (context_expr is not None):
            raise UnsupportedConstruct(f"{function.name!r} call-context shape doesn't match its own mapping")
        if (out_index is not None) != (out_target is not None):
            raise UnsupportedConstruct(
                f"{function.name!r} {'requires' if out_index is not None else 'has no'} a result to assign"
            )

        positional_indices = [i for i in range(len(arg_infos)) if i != context_index and i != out_index]
        # A Vector3-typed slot is one opcode argument but three call-syntax values (e.g. attach_to's
        # "offset", written "0, 0, -2") -- confirmed directly (Vector3Argument.x/y/z, constructible
        # via typeinfo.create()), see module docstring.
        expected_call_arg_count = sum(
            3 if arg_infos[i].typeinfo.internal_name == "_vector3" else 1 for i in positional_indices
        )
        if expected_call_arg_count != len(call_args):
            raise UnsupportedConstruct(
                f"{function.name!r} expects {expected_call_arg_count} call argument(s), got {len(call_args)} "
                "(a multi-value argument type collapsed into several call-syntax values isn't supported "
                "for this shape yet)"
            )

        opcode = self._rvt.Condition() if is_condition else self._rvt.Action()
        opcode.function = function
        call_arg_cursor = 0
        for i in range(len(arg_infos)):
            if i == context_index:
                opcode.add_argument(self._build_argument(context_expr, arg_infos[i].typeinfo))
            elif i == out_index:
                opcode.add_argument(self._build_argument(out_target, arg_infos[i].typeinfo))
            elif arg_infos[i].typeinfo.internal_name == "_vector3":
                opcode.add_argument(
                    self._build_vector3_argument(call_args[call_arg_cursor : call_arg_cursor + 3], arg_infos[i].typeinfo)
                )
                call_arg_cursor += 3
            else:
                opcode.add_argument(self._build_argument(call_args[call_arg_cursor], arg_infos[i].typeinfo))
                call_arg_cursor += 1
        return opcode

    # -- if / conditions --------------------------------------------------------------------------

    def _next_or_group(self, trigger) -> int:
        # or_group is the one field the engine's own save-time regeneration never touches -- the
        # caller's responsibility (confirmed via test_or_group_and_action_index_on_a_condition and
        # test_condition_construction_gates_the_action_that_follows_it in
        # test_megalo_engine_ast_bindings.py). Each ANDed conjunct gets its own group.
        existing = [
            trigger.opcode(i).or_group
            for i in range(trigger.opcode_count)
            if isinstance(trigger.opcode(i), self._rvt.Condition)
        ]
        return (max(existing) + 1) if existing else 0

    def _split_conjuncts(self, expr) -> list:
        if expr.kind == "binary" and expr.op == "and":
            return [*self._split_conjuncts(expr.left), *self._split_conjuncts(expr.right)]
        return [expr]

    def _split_disjuncts(self, expr) -> list:
        if expr.kind == "binary" and expr.op == "or":
            return [*self._split_disjuncts(expr.left), *self._split_disjuncts(expr.right)]
        return [expr]

    def _compile_term(self, expr, trigger, *, or_group: int) -> None:
        """A single condition opcode -- one ``==``/``!=``/``<``/``>``/``<=``/``>=`` comparison or
        boolean condition-function call, optionally ``not``-negated. ``or_group`` is passed in
        (never computed here) so a whole flat OR-chain of terms (see :func:`_split_disjuncts`) can
        share the one group real Megalo's own bytecode uses for "any of these" -- confirmed directly
        against RCC Onslaught v13.bin's own already-compiled conditions, not guessed: real siblings
        that share an ``or_group`` are exactly its own ``a or b`` pairs/chains."""
        inverted = False
        while expr.kind == "unary" and expr.op == "not":
            inverted = not inverted
            expr = expr.operand

        if expr.kind == "binary" and expr.op in _COMPARE_OPERATOR_VALUES:
            left_arg = self._build_argument(expr.left, self._compare.arguments[0].typeinfo)
            right_arg = self._build_argument(expr.right, self._compare.arguments[1].typeinfo)
            condition = self._rvt.Condition()
            condition.function = self._compare
            condition.add_argument(left_arg)
            condition.add_argument(right_arg)
            operator_arg = self._compare.arguments[2].typeinfo.create()
            operator_arg.value = _COMPARE_OPERATOR_VALUES[expr.op]
            condition.add_argument(operator_arg)
        elif expr.kind == "call":
            split = self._split_call_target(expr.target)
            if split is None:
                raise UnsupportedConstruct("this condition call's target shape is not supported yet")
            context_expr, method_name = split
            function = _find_function(self._rvt, primary_name=method_name, condition=True)
            if function is None:
                raise UnsupportedConstruct(f"no condition function found for call {method_name!r}")
            condition = self._emit_function_opcode(
                function, context_expr, expr.args, out_target=None, is_condition=True
            )
        elif expr.kind == "binary" and expr.op == "and":
            # "(a and b) or c" needs CNF distribution ((a or c) and (b or c)) to fit the engine's
            # flat "AND across or_groups, OR within one" model -- not supported yet, see module
            # docstring's "or"/"|" limitation.
            raise UnsupportedConstruct("'and' mixed with 'or' at the same condition level is not supported yet")
        else:
            raise UnsupportedConstruct(f"expression kind {expr.kind!r} is not supported as a condition yet")

        condition.inverted = inverted
        condition.or_group = or_group
        trigger.add_opcode(condition)

    def _compile_if(self, stmt, trigger) -> None:
        if stmt.altif_clauses or stmt.alt_body is not None:
            raise UnsupportedConstruct("'altif'/'alt' clauses are not supported yet")
        for conjunct in self._split_conjuncts(stmt.condition):
            or_group = self._next_or_group(trigger)
            for term in self._split_disjuncts(conjunct):
                self._compile_term(term, trigger, or_group=or_group)
        self._compile_nested_body(stmt.body, trigger)

    # -- for each ------------------------------------------------------------------------------

    def _resolve_forge_label_index(self, label_expr) -> int:
        if label_expr.kind == "int":
            index = label_expr.value
        elif label_expr.kind == "string":
            matches = [
                i
                for i in range(self._mp.forge_label_count)
                if self._mp.forge_label(i).name is not None
                and self._mp.forge_label(i).name.get_content(self._rvt.Language.english) == label_expr.value
            ]
            if len(matches) != 1:
                raise UnsupportedConstruct(f"no unique forge label named {label_expr.value!r} in this variant")
            index = matches[0]
        else:
            raise UnsupportedConstruct(f"forge label expression kind {label_expr.kind!r} is not supported yet")
        if not (0 <= index < self._mp.forge_label_count):
            raise UnsupportedConstruct(
                f"forge label index {index} is out of range (this variant has {self._mp.forge_label_count})"
            )
        return index

    def _compile_for_each(self, stmt, trigger) -> None:
        if stmt.selector not in _FOR_EACH_BLOCK_TYPES:
            raise UnsupportedConstruct(f"'for each {stmt.selector}' is not supported yet")
        if stmt.label is not None and stmt.selector != "object":
            raise UnsupportedConstruct("'with label ...' is only supported for 'for each object' yet")
        if stmt.randomly and stmt.selector != "player":
            raise UnsupportedConstruct("'randomly' is only supported for 'for each player' yet")

        if stmt.label is not None:
            self._compile_nested_body(stmt.body, trigger, forge_label_index=self._resolve_forge_label_index(stmt.label))
            return
        block_type_name = "for_each_player_randomly" if stmt.randomly else f"for_each_{stmt.selector}"
        block_type = getattr(self._rvt.TriggerBlockType, block_type_name)
        self._compile_nested_body(stmt.body, trigger, block_type=block_type)

    def _compile_nested_body(self, body, trigger, *, block_type=None, forge_label_index=None) -> None:
        """Builds ``body`` as its own subroutine trigger (always a real, separate ``Trigger`` --
        never inline, see module docstring for why this is exactly what closes the bInlineIfs gap)
        and calls it from ``trigger`` via "Run Nested Trigger"."""
        child = self._mp.add_trigger()
        child_index = self._mp.trigger_count - 1
        self._mp.mark_trigger_as_subroutine(child_index)
        if forge_label_index is not None:
            self._mp.mark_trigger_forge_label(child_index, forge_label_index)
        elif block_type is not None:
            self._mp.mark_trigger_block_type(child_index, block_type)
        self._compile_statements(body, child)

        call_action = self._rvt.Action()
        call_action.function = self._run_nested_trigger
        call_action.add_argument(self._build_trigger_ref(child_index))
        trigger.add_opcode(call_action)


def compile_script(rvt, variant, source: str) -> None:
    """Compiles ``source`` directly into ``variant``'s multiplayer script via native construction
    (no call into ``mp.compile_script()`` at all), or raises :class:`UnsupportedConstruct` for
    anything outside this compiler's supported subset (see module docstring). ``variant`` may be
    partially mutated when this raises -- see module docstring's "Failure must not leave partial
    state".
    """
    try:
        script = parse(source)
    except (MegaloLexError, MegaloParseError) as exc:
        raise UnsupportedConstruct(f"parse error: {exc}") from exc
    _Compiler(rvt, variant).compile(script)
