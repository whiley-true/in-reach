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
  with ``not``, combined with any mix of ``and``/``or`` up to one level of nesting (e.g.
  ``a and b or c``, a real case confirmed in RCC Onslaught v13.bin) -- converted to the CNF shape the
  engine's own flat ``or_group`` model actually needs (AND across groups, OR within one group) via
  real distribution when a disjunct is itself an AND-chain, not just left as unsupported (see
  ``_compile_condition``'s own docstring). A condition complex enough to need a second level of
  distribution (e.g. an explicitly-parenthesized ``or`` nested inside an ``and`` that's itself inside
  an ``or``) isn't supported yet. No ``altif``/``alt`` clauses, no ``|`` flag-combination.
- ``for each object|player|team do ... end`` loops, including ``for each object with label N do``
  (``N`` an int label index, or a string matched against a real forge label's own name -- see
  ``mark_trigger_forge_label()``'s own docstring in the native source for the block_type/forge_label
  pairing this needs).
- Any call whose target action/condition function has ``mapping.type == function`` (i.e. renders as
  ``<context>.<name>(<args>)`` or a bare ``<name>(<args>)``, including a "decorative" no-real-object
  prefix like ``game.end_round()`` -- confirmed directly that ``mapping.arg_context`` has more than
  one negative "no context" sentinel, -1 *and* -2, both meaning "don't build an argument from this",
  not just -1) -- covers a large, genuinely general slice of real actions/conditions (``is_of_type``,
  ``get_distance_to``, ``delete``, ``rand``, ``attach_to``, ``set_shape``, etc.) without hand-listing
  each one, including three multi-value/composite argument classes collapsed into several bare
  call-syntax values: a ``Vector3`` (always 3 values, e.g. ``attach_to``'s own ``offset``, confirmed
  directly against ``Vector3Argument.x``/``.y``/``.z``), a ``Shape`` (a *variable* number of values
  depending on its own first one -- ``none``/``sphere``/``cylinder``/``box`` take 0/1/3/4 more,
  confirmed against the official reference's "set_boundary" syntax and real ``set_shape(...)`` calls
  in RCC Onslaught v13.bin, see ``_build_shape_argument``'s own docstring), and a player-set argument
  (e.g. ``set_waypoint_visibility``'s own argument -- a composite with no plain ``.value`` at all,
  confirmed to crash the generic enum fallback -- takes 1 value for the 4 simple forms
  (``no_one``/``everyone``/``allies``/``enemies``), 3 for a specific player (``mod_player, <player>,
  <0-or-1>``, confirmed a real case in RCC Onslaught v13.bin), see
  ``_build_player_set_argument``'s own docstring). Any *other* multi-value
  collapsing this compiler doesn't know about is still caught safely by the call-argument-count
  check, rather than silently miscompiling. Two more real quirks this general dispatch accounts for,
  neither a general rule (most functions need neither): a function whose real call-syntax argument
  order doesn't match its own metadata order at all (``_CALL_ARGUMENT_ORDER_OVERRIDES``, a small
  lookup table of confirmed real cases -- e.g. "Get Random Object With Label"/"Play Sound"), and a
  genuine overload where two different real functions share the same ``primary_name`` (confirmed a
  real case: ``add_weapon`` names both "Add Weapon to Player" and "Add Weapon To Biped" -- resolved
  by preferring whichever candidate's own non-context/non-out argument count matches the actual
  call, see ``_find_function``'s own docstring).
- ``declare`` statements are parsed and validated (scope/type/index in range) but otherwise treated
  as a no-op -- Megalo's own real semantics for these are compile-time bookkeeping (network
  replication priority/initial-value hints), not a runtime opcode; not reproducing the priority/
  initial-value metadata is a real, deliberate limitation of this pass, not an oversight.
- A property read/write as a *direct* assignment RHS/LHS (``X = current_player.biped.health``,
  ``current_player.biped.shields = 200``/``+= 50``/etc). Despite looking exactly like a plain
  variable read/assignment, a property isn't a stored variable at all -- each one is its own
  dedicated action with ``mapping.type == "property_get"``/``"property_set"`` (e.g. "Get Object
  Health"/"Modify Object Shields"), confirmed real cases in RCC Onslaught v13.bin (see
  ``_find_property_function``'s own docstring). Not supported as a general sub-expression (e.g.
  inside a comparison, or as a call argument) -- that would need a temporary variable to hold the
  read result before it could be used, which this pass doesn't allocate.
- A quoted string literal as a format-string call argument (e.g. ``set_objective_text("...")``) --
  a real, persistent entry added to the variant's own string table (``mp.script_strings.add_new()``,
  confirmed constructible -- unlike most argument types this module touches, which have no
  constructor at all -- reusing a real, already-present string with the exact same text before ever
  adding a new one, since the table's own capacity is fixed and confirmed a real case recompiling
  RCC Onslaught v13.bin's own script unedited exhausted it otherwise), including up to 2 ``%n``
  (number)/``%p`` (player) replacement tokens (e.g. ``"...%n points to win."``, ``"%p's drop pod
  crushed %p"``, both real cases in RCC Onslaught v13.bin), each consuming one extra call-syntax
  value for its own source. Any other placeholder character (``%t``/``%o``/etc -- the engine's own
  ``OpcodeStringTokenType`` enum has team/object/timer members too) isn't supported yet -- no
  confirmed real example to build that part of the mapping from, see
  ``_build_format_string_argument``'s own docstring.
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

## Constructing nested triggers: inline scopes, and entry_type=subroutine / block_type

An ``if``/``do`` body is built *inline* -- embedded directly into its parent's own opcode list via
"Run Inline Nested Trigger" (``MegaloScopeArgument.data``, a full ``CodeBlock`` -- confirmed
constructible and round-trips through a real save/reload, see ``test_construct_inline_trigger_with_a_
nested_action_persists_through_save_reload`` in ``test_megalo_engine_ast_bindings.py``) -- costing no
trigger slot at all, rather than as a separate ``Trigger``. This is *not* a reversion to the original
``bInlineIfs`` bug: that bug was never about inlining itself, it was that the native compiler's
inlining decision can't be reconstructed from a decompile/recompile round trip (decompiled text loses
whichever way it went). This module's own choice is a fixed rule over the parsed AST -- always inline
an ``if``/``do`` body -- so recompiling the exact same source always produces the exact same
structure; the source is what's authoritative, not a guess. See :func:`_Compiler._compile_nested_body`
for the real motivation this was added for (a large, deeply-nested script hitting the engine's own
``Limits::max_triggers`` when every nested body cost a real trigger -- confirmed a real, previously-
blocking case: RCC Onslaught v13.bin's full script).

``for each`` loops still need a real, separate subroutine ``Trigger`` -- block_type/forge_label only
exist on one, an inline scope has neither -- and so do named ``function`` declarations, since they
need to be reachable by index from more than one call site, which an inline scope (embedded at
exactly one place) can't provide. Confirmed by reading ``compiler.cpp``'s own ``Block::compile()``:
*every* such real nested trigger gets ``entryType = subroutine`` unconditionally, or the engine would
tick it independently *in addition to* running it via "Run Nested Trigger" -- a real double-execution
bug. Neither ``Trigger.entry_type`` nor ``Trigger.block_type`` had a setter in the native binding (not
even in the upstream source this was ported from) and ``bind_trigger_as_event()`` explicitly can't
set 'subroutine' either -- a genuine binding gap, not a workaround-able one, closed by adding
``MultiplayerData.mark_trigger_as_subroutine()``/``mark_trigger_block_type()`` to ``bindings.cpp`` and
rebuilding the bundled ``.pyd`` (see those methods' own docstrings in the native source). ``for each``
loops always get their own trigger even at the top level (where the native compiler would instead set
block_type directly on the containing trigger) -- less minimal, but uniformly correct and much
simpler to implement once.

## Failure must not leave partial state

``compile()`` calls ``MultiplayerData.clear_triggers()`` as its own first action, replacing the
variant's own script wholesale (see ``clear_triggers()``'s own native docstring -- mirrors what
``compile_script()`` itself does at the start of every compile: without this, ``add_trigger()``
(append-only, no way to remove or clear an individual ``Trigger``) would silently build a second,
redundant copy of the script on top of whatever the variant was loaded with, confirmed a real,
previously-blocking bug -- see ``_scan_templates()``'s own docstring for why every template it
retains is cloned at scan time, *before* this runs, rather than held as a live reference into the
triggers it's about to destroy). Beyond that point, though, there's still no way to *partially* undo
a compile already in progress -- if this module raises :class:`UnsupportedConstruct` partway through,
the ``variant`` object passed in may already carry a partially-built script. **The caller must
discard that ``variant`` entirely and load a fresh one** before falling back to
``mp.compile_script(source)`` -- reusing the same, now-partially-mutated object is not safe. See
:mod:`in_reach.app.rvt.compile`'s own fallback for the reload this requires.

## Fixed: an intermittent native crash scanning-then-clearing the same triggers

``_build_format_string_argument``'s own ``typeinfo.create()`` call used to intermittently (~10-20%
of the time, worse under heavier allocation load in the same process) fail with ``RuntimeError:
Invalid unique_ptr: another instance owns this pointer already`` -- root-caused (not guessed) by
reading pybind11 3.1's own ``smart_holder_from_unique_ptr()`` (``detail/type_caster_base.h``):
whenever a freshly-``new``'d C++ object's address is already present in pybind11's own instance
registry with no "trampoline" to reclaim, it throws exactly this. The registry gets a *stale* entry
whenever a ``reference_internal``-policy binding (``Opcode.argument(i)``, ``.token(i)``, etc. -- and
this module's own ``_scan_templates()`` calls exactly these while scanning every existing opcode
argument) hands out a live Python wrapper for an object, and that object is later destroyed via a
raw, pybind11-unaware C++ ``delete`` (``MultiplayerData.clear_triggers()``'s own
``cobb::indexed_list::clear()`` cascade is exactly this) while the wrapper is still (even
transiently) alive -- confirmed empirically, not just by reading code: scanning a variant's triggers
and never clearing them afterward reproduced 0 failures in 30 attempts; scanning and then clearing
the *same* triggers reproduced the failure on literally the next attempt.

**Fix**: ``_Compiler._scan_copy()`` makes ``_scan_templates()`` scan a separate, throwaway
save-and-reload *copy* of the variant, never ``variant`` itself -- so ``compile()``'s own
``clear_triggers()`` (which only ever touches ``variant``) never destroys anything
``_scan_templates()`` exposed to Python. A related, secondary bug this surfaced (and which is also
fixed): a *reused* string had to come from the same target ``variant``'s own string table, not from
the separate scan copy -- ``_scan_strings()`` accordingly scans ``mp.script_strings`` directly on
the target, not via the trigger-argument walk at all (see its own docstring), since the persistent
string table is untouched by ``clear_triggers()`` regardless.

## Fixed: format-string content was stored un-unescaped

A related but separate bug, also caught by this module's own test suite: ``megalo_ast``'s
``StringLiteral.value`` is deliberately raw, unescaped source text (see ``nodes.py``'s own
docstring), but the real stored bytes a format string compiles into need the *interpreted* escapes
(``\r`` -> a real CR byte, etc.) -- confirmed directly against the native compiler's own string
parsing (``string_scanner::unescape()``) and the decompiler's own inverse (``string_scanner::
escape()``, which re-escapes a literal backslash *already in the stored content*, doubling it on
round-trip if the unescape step was skipped). See :func:`_unescape_string_literal`'s own docstring.
"""
from __future__ import annotations

import itertools
import os
import re
import tempfile
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

# Megalo::Limits::max_conditions/max_actions (limits.h) -- real, hard engine caps on the TOTAL
# condition/action opcode count across the whole script (every trigger and every inline nested
# scope combined, not per-trigger). Unlike Limits::max_triggers (320, guarded at every add_trigger()
# call already), nothing in the native write()/save() path itself checks these before writing --
# confirmed by reading multiplayer.cpp's own write(): it only checks the aggregate BIT budget
# (predicted_size vs. the fixed MPVR content size), never these two count caps. A script that
# exceeds either one saves without any error and produces a file whose own read()-side check
# (multiplayer.cpp, "too_many_opcodes") then deterministically rejects it -- confirmed a real,
# previously-blocking case: RCC Onslaught v13.bin's full script compiles to 1026 actions once every
# if/do body is inlined (see _compile_nested_body's own docstring for why this compiler inlines
# aggressively), just past the 1024 cap, even though its own trigger count (84) is nowhere near
# Limits::max_triggers. Checked once, after compile() finishes building everything (native binding:
# MultiplayerData.get_full_size_data().counts), the same "convert an engine limit into a clean
# UnsupportedConstruct instead of a silently-broken build" treatment _add_trigger() already gives
# Limits::max_triggers.
_MAX_CONDITIONS = 512
_MAX_ACTIONS = 1024
_SELF_SCOPE_ALIAS = {
    "current_player": "player",
    "current_object": "object",
    "current_team": "team",
    # "hud_player" is its own distinct owning-scope ("which") family, not interchangeable with plain
    # "player"/"current_player" -- confirmed directly against a real compiled opcode (RCC Onslaught
    # v13.bin's own "hud_player.number[0]"): a player-scoped scalar variable's .which encodes WHICH
    # player owns the referenced scalar slot, and "hud_player" (the player this HUD widget instance
    # belongs to) is a different fixed .which value than "current_player"'s own -- mapped to itself
    # (not "player") so its own template pool key ("hud_player.number[]") stays separate and never
    # gets cloned-and-retargeted from a "current_player"/"player" template with the wrong owner.
    "hud_player": "hud_player",
}
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

# Confirmed directly (not a general rule -- most functions' call-syntax argument order matches their
# own metadata `arguments` array order exactly, minus context/out, which is why every other function
# used throughout this module needed no such override): a real opcode's own raw argument order always
# matches its metadata order (spot checked against a real "Get Random Object With Label" opcode in
# RCC Onslaught v13.bin -- arg 0/1/2 line up with metadata's exclude/result/label exactly), but this
# one function's *call syntax* -- "get_random_object(<label>, <exclude>)", per the official
# reference's own "get_random_object" entry -- reorders "label" before "exclude" relative to that.
# Maps function name -> the metadata argument indices in real call-syntax order (context/out excluded
# either way, located automatically regardless of this table).
_CALL_ARGUMENT_ORDER_OVERRIDES: dict[str, list[int]] = {
    "Get Random Object With Label": [2, 0],
    # "Play Sound"'s own metadata order is [sound, immediate, who], but its real call syntax --
    # "play_sound_for(<who>, <sound>, <immediate>)", confirmed a real case in RCC Onslaught v13.bin
    # -- puts "who" first. (metadata index 2, then 0, then 1.)
    "Play Sound": [2, 0, 1],
}

# ShapeArgument's own field names (ShapeArgument.radius doubles as "width" for box -- see its own
# native docstring) in call-syntax order, per shape type -- confirmed against the official
# reference's "set_boundary" syntax (the same underlying Shape argument type) and real
# set_shape(...) calls in RCC Onslaught v13.bin. See _Compiler._build_shape_argument.
_SHAPE_TYPE_FIELDS = {
    "none": [],
    "sphere": ["radius"],
    "cylinder": ["radius", "bottom", "top"],
    "box": ["radius", "length", "bottom", "top"],
}

# "%x" placeholder -> OpcodeStringTokenType member name -- confirmed real cases in RCC Onslaught
# v13.bin ("%n" for a number, "%p" for a player); any other placeholder character (team/object/timer
# tokens all exist in the engine's own enum, see OpcodeStringTokenType, but have no confirmed real
# example here to build the mapping from) is deliberately left out, not guessed at.
_FORMAT_STRING_TOKEN_TYPES = {"%n": "number", "%p": "player"}

_METER_TYPE_FIELDS = {
    "none": [],
    "number": ["numerator", "denominator"],
    "timer": ["timer"],
}

# C++ source truth: string_scanner::unescape()'s own _escape_map_entry table
# (helpers/string_scanner.cpp) -- \x/\u (2/4 hex digits) are handled separately in
# _unescape_string_literal, not through this table.
_STRING_ESCAPES = {
    "'": "'",
    '"': '"',
    "?": "?",
    "\\": "\\",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
}


def _unescape_string_literal(text: str) -> str:
    """``megalo_ast``'s own ``StringLiteral.value`` is deliberately raw, unescaped source text (see
    ``nodes.py``'s own docstring: "escapes NOT interpreted") -- the AST layer's job is just to
    capture exactly what's between the quotes, nothing more. But the *real* Megalo bytecode a format
    string (or any other consumed string literal) compiles into needs the actual interpreted bytes,
    not the display form -- confirmed directly by reading the vendored native compiler's own string
    parsing (``helpers/string_scanner.cpp``'s ``string_scanner::extract_string()`` calls
    ``string_scanner::unescape()`` on every quoted string it reads) and its counterpart, the
    decompiler's own rendering (``string_scanner::escape()``, used by ``decompiler.cpp``), which is
    the exact inverse: a real, stored control byte (e.g. 0x0D) renders as the 2-character display
    form ``\\r``, and critically, a literal backslash byte *already in the stored content* also gets
    escaped, rendering as ``\\\\`` -- so storing this module's own AST value verbatim (skipping this
    unescape step entirely) was a real, previously-shipped bug: a source literal containing the
    display form ``\\r\\n`` (4 literal characters, matching how a real embedded newline decompiles)
    got stored as those same 4 literal characters instead of the 2 real CR+LF bytes they represent,
    and then round-tripped back out through the decompiler's own escaping as 8 characters
    (``\\\\r\\\\n``) -- confirmed a real, reproducible case caught by this module's own test suite.
    Matches ``string_scanner::unescape()``'s exact behavior, including its two edge cases: an
    unrecognized ``\\X`` sequence keeps just ``X`` (the backslash is dropped, not preserved), and a
    trailing/incomplete escape (a backslash with nothing after it, or ``\\x``/``\\u`` without enough
    hex digits left) is left as a literal backslash.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch != "\\" or i + 1 >= n:
            out.append(ch)
            i += 1
            continue
        d = text[i + 1]
        if d in ("x", "u"):
            digit_count = 4 if d == "u" else 2
            hex_digits = text[i + 2 : i + 2 + digit_count]
            if len(hex_digits) == digit_count:
                try:
                    out.append(chr(int(hex_digits, 16)))
                    i += 2 + digit_count
                    continue
                except ValueError:
                    pass
            out.append(ch)
            i += 1
            continue
        replacement = _STRING_ESCAPES.get(d)
        if replacement is None:
            out.append(d)
        else:
            out.append(replacement)
        i += 2
    return "".join(out)


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
    # A bare (unwrapped) real literal-scope ScalarVariable, for Variable.copy_from() -- populating an
    # embedded, initially-scope=None Variable member (e.g. ShapeArgument.radius) this binding exposes
    # no constructor/scope-setter for. copy_from() only requires the exact same concrete type match
    # (ScalarVariable == ScalarVariable), not a matching typeinfo family, so this one template covers
    # every such embedded-scalar case regardless of which opcode slot it's used from.
    literal_scalar: object | None = None
    # {english text: real ReachString} -- a fixed-capacity string table (confirmed 112 entries in a
    # real variant) means blindly add_new()-ing a fresh entry for every format-string call would
    # rapidly exhaust it even recompiling a script completely unedited (confirmed a real case: RCC
    # Onslaught v13.bin's own string table is already at capacity) -- reusing a real, already-
    # present string with the exact same text, the same self-sourcing principle as every other
    # template in this class, avoids that for the overwhelmingly common case of a string that's
    # already in the variant somewhere.
    strings: dict[str, object] = field(default_factory=dict)


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
                # Every template retained below is cloned at scan time, not stored as a live
                # reference into this opcode/trigger -- compile() itself clears and rebuilds
                # mp.scriptContent.triggers from scratch (see its own docstring), which genuinely
                # destroys the underlying C++ Trigger/Opcode/Argument objects
                # (cobb::indexed_list::clear() deletes every owned element, confirmed by reading
                # indexed_list.h). A template holding a raw reference into one of those would dangle
                # the moment clear_triggers() runs, well before any template is actually consumed --
                # cloning here decouples the template's lifetime from the trigger it happened to be
                # found in, same as every consumer already does on top of it (_retarget(),
                # _build_trigger_ref(), etc. each .clone() the template again for their own specific
                # use -- cloning a clone is the normal, supported "prototype" pattern, not redundant).
                arg = opcode.argument(ai)
                if templates.trigger_ref is None and isinstance(arg, rvt.TriggerArgument):
                    templates.trigger_ref = arg.clone()
                    continue
                if templates.literal_scalar is None:
                    inner = arg.variable if hasattr(arg, "variable") else arg
                    if isinstance(inner, rvt.ScalarVariable) and inner.scope is not None and inner.scope.format == "%i":
                        templates.literal_scalar = inner.clone()
                if arg_infos[ai].typeinfo.internal_name == "_meter_parameters":
                    # A composite argument's own embedded Variable sub-fields (numerator/denominator/
                    # timer) are otherwise invisible to this flat, top-level-arguments-only scan (see
                    # this function's own docstring) -- confirmed a real, previously-blocking case:
                    # RCC Onslaught v13.bin's own "hud_player.number[0]" (a player-scoped scalar
                    # referring to "whichever player this HUD widget instance belongs to", a
                    # completely different owning scope/which-family than plain "player"/
                    # "current_player" -- confirmed via a direct opcode inspection: its own
                    # ScalarVariable has both has_index and has_which true, format "%w.number[%i]",
                    # unlike a global scalar which only has an index) only ever appears nested inside
                    # its own "Set Meter Parameters" call, nowhere else in the script -- so without
                    # digging in here, there would never be a template to source a "hud_player"-scoped
                    # reference from at all, regardless of how many times the script uses one.
                    for field_name in ("numerator", "denominator", "timer"):
                        field_value = getattr(arg, field_name)
                        try:
                            field_text = field_value.decompile(variant)
                        except Exception:  # noqa: BLE001 -- an unset/default sub-field can't decompile
                            continue
                        field_typeinfo_name = field_value.get_variable_typeinfo().internal_name
                        templates.variables.setdefault(
                            (field_typeinfo_name, _decompiled_key(rvt, field_value, field_text)), field_value.clone()
                        )
                        templates.literal_variables.setdefault((field_typeinfo_name, field_text), field_value.clone())
                try:
                    text = arg.decompile(variant)
                except Exception:  # noqa: BLE001 -- some argument kinds can't decompile in isolation
                    continue
                typeinfo_name = arg_infos[ai].typeinfo.internal_name
                templates.variables.setdefault((typeinfo_name, _decompiled_key(rvt, arg, text)), arg.clone())
                templates.literal_variables.setdefault((typeinfo_name, text), arg.clone())
    return templates


def _scan_strings(rvt, mp) -> dict[str, object]:
    """``{english text: real ReachString}`` for every string already in ``mp``'s own persistent
    string table (``mp.script_strings`` -- a ``ReachStringTable``, a field entirely separate from
    ``scriptContent.triggers``, so untouched by ``clear_triggers()``).

    Deliberately called on the *target* ``variant`` itself (``self._variant``, never the throwaway
    copy ``_scan_templates()`` scans -- see ``_Compiler._scan_copy()``'s own docstring), and
    deliberately iterates the table directly (``len(mp.script_strings)``/``mp.script_strings[i]``,
    both already bound) rather than discovering strings by walking trigger opcodes' own
    ``FormatStringArgument.string`` references the way an earlier version of this function did. Two
    real bugs, now both avoided by construction:

    - Walking opcodes to find strings means visiting ``FormatStringArgument`` opcode arguments via
      ``Opcode.argument(i)`` (``reference_internal``) -- exactly the trigger/argument-exposure
      pattern that made the native crash documented in this module's "Known issue" section possible
      in the first place. Reading the table directly touches no trigger/opcode/argument object at
      all, so it carries none of that risk regardless of when ``clear_triggers()`` runs relative to
      this scan.
    - A ``ReachString`` found by walking the *scan copy*'s own opcodes would belong to that separate
      ``GameVariant``, not to ``self._variant`` -- assigning a cross-object pointer like that into an
      argument actually added to ``self._variant``'s own triggers is its own kind of corruption
      (confirmed a real, reproducible case: after this function's own predecessor was moved to scan
      the safe copy to fix the crash above, format-string round-trips started reading back with
      doubled escape characters -- the string content was being read from memory that belonged to a
      different, unrelated ``GameVariant``). Reading ``mp.script_strings`` directly on the actual
      target variant sidesteps this too: every ``ReachString`` returned already belongs to the same
      object the new argument will be added to.
    """
    strings: dict[str, object] = {}
    table = mp.script_strings
    for i in range(len(table)):
        entry = table[i]
        if not entry.has_content(rvt.Language.english):
            continue
        text = entry.get_content(rvt.Language.english)
        strings.setdefault(text, entry)
    return strings


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


def _find_function(rvt, *, name: str | None = None, primary_name: str | None = None, condition: bool, call_arg_count: int | None = None):
    """``call_arg_count``, when given, disambiguates a genuine overload -- confirmed a real case:
    ``add_weapon`` is shared by both "Add Weapon to Player" (1 non-context argument) and "Add Weapon
    To Biped" (2), only distinguishable by how many call-syntax values are actually given (RCC
    Onslaught v13.bin's own ``current_player.biped.add_weapon(dmr, force)`` needs the 2-argument
    one; matching by name alone, first-found, silently picked the wrong one). Falls back to the
    first match by name if no candidate's own non-context/non-out argument count matches exactly
    (either because ``call_arg_count`` wasn't given, or the real match uses a variable-arity
    argument this shallow count doesn't account for) -- unambiguous for every other function this
    compiler has used all along, which is why this isn't the only/default matching strategy.
    """
    count = rvt.condition_function_count() if condition else rvt.action_function_count()
    get = rvt.condition_function if condition else rvt.action_function
    first_match = None
    for i in range(count):
        f = get(i)
        if name is not None and f.name == name:
            return f
        if primary_name is not None and f.mapping.type.name == "function" and f.mapping.primary_name == primary_name:
            if first_match is None:
                first_match = f
            if call_arg_count is not None:
                positional_count = sum(
                    1
                    for j in range(len(f.arguments))
                    if j != f.mapping.arg_context and not f.arguments[j].is_out_variable
                )
                if positional_count == call_arg_count:
                    return f
    return first_match


def _find_property_function(rvt, variant, primary_name: str, *, kind: str):
    """A property_get/property_set-mapped action (never a condition -- confirmed no condition
    function uses either mapping type) whose own ``mapping.primary_name`` matches -- e.g. "Get
    Object Health" (property_get, primary_name "health", renders as ``<context>.health``) or
    "Modify Object Shields" (property_set, primary_name "shields", renders as ``<context>.shields
    <op> <value>``, its own dedicated action, not the generic "Modify Variable"). ``kind`` is
    ``"property_get"`` or ``"property_set"``.

    Returns ``(function, selector)``. ``selector`` is ``None`` for the ordinary primary_name-matched
    case above. Some property actions instead cover a *family* of properties through one shared
    action, selected per-call by an enum-typed argument rather than by ``mapping.primary_name``
    (confirmed a real case: "Modify Player Grenades" has an empty ``primary_name`` and
    ``mapping.arg_name == 1`` -- its own argument 1, a ``_grenade_type`` enum, supplies the
    property's name per-call: value 0 decompiles as ``frag_grenades``, value 1 as
    ``plasma_grenades``, matching this grammar's own property syntax, e.g.
    ``current_player.frag_grenades -= 1``). For such a candidate, ``selector`` is the resolved
    integer enum value that must be written into ``arguments[mapping.arg_name]`` to select this
    specific property -- found via the same decompile-and-compare brute force ``_build_enum_arg``
    uses for any other named enum value, since verified real title data (see above) confirms
    ``.decompile()`` already renders these as the exact grammar-identifier spelling, underscores and
    all -- no separate name-mangling step needed."""
    for i in range(rvt.action_function_count()):
        f = rvt.action_function(i)
        if f.mapping.type.name == kind and f.mapping.primary_name == primary_name:
            return f, None
    for i in range(rvt.action_function_count()):
        f = rvt.action_function(i)
        m = f.mapping
        if m.type.name != kind or m.primary_name != "" or m.arg_name < 0:
            continue
        selector_arg = f.arguments[m.arg_name].typeinfo.create()
        if not hasattr(selector_arg, "value"):
            continue
        for k in range(_ENUM_BRUTE_FORCE_LIMIT):
            try:
                selector_arg.value = k
                text = selector_arg.decompile(variant)
            except Exception:  # noqa: BLE001 -- signals "value out of range for this enum family"
                break
            if text == primary_name:
                return f, k
    return None, None


class _Compiler:
    def __init__(self, rvt, variant):
        self._rvt = rvt
        self._variant = variant
        self._mp = variant.multiplayer
        self._templates = _scan_templates(rvt, *self._scan_copy(rvt, variant))
        # Strings are scanned separately, directly off the *target* variant's own table -- see
        # _scan_strings()'s own docstring for why that's both safer and correct in a way scanning
        # them as part of the trigger-walk above (on the throwaway copy) isn't.
        self._templates.strings = _scan_strings(rvt, self._mp)
        self._enum_cache: dict[tuple[str, str], int] = {}
        self._functions: dict[str, int] = {}  # name -> its own pre-allocated subroutine trigger index
        self._modify_variable = self._require_action("Modify Variable")
        self._compare = self._require_condition("Compare")
        self._run_nested_trigger = self._require_action("Run Nested Trigger")
        self._run_inline_nested_trigger = self._require_action("Run Inline Nested Trigger")

    @staticmethod
    def _scan_copy(rvt, variant):
        """Returns ``(scan_variant, scan_variant.multiplayer)`` -- a separate, throwaway *copy* of
        ``variant``'s own current bytecode, freshly re-loaded from a temp file, never ``variant``
        itself. See module docstring's "Known issue" section for the full mechanism this avoids:
        ``_scan_templates()`` exposes every argument it visits to Python via a ``reference_internal``
        binding, and ``compile()`` calls ``MultiplayerData.clear_triggers()`` on ``variant`` itself
        immediately afterward, which raw-deletes every Trigger/Opcode/Argument it owns with no
        awareness that pybind11 has live, registered Python wrappers for some of them -- a real,
        reproducible native crash (confirmed empirically: 0/30 failures scanning-then-never-clearing
        a variant vs. reproducing on literally the next attempt once clearing the *same*
        just-scanned objects was reintroduced) when a later allocation reuses a freed address that's
        still marked as owned in pybind11's own instance registry. Scanning a separate copy instead
        means ``clear_triggers()`` never touches anything ``_scan_templates()`` exposed to Python at
        all -- the copy's own eventual garbage collection (whenever that happens, likely well after
        this compile finishes) is decoupled in time from this compile's own allocations, rather than
        happening back-to-back with them. This is called at ``__init__`` time, before ``compile()``
        has mutated ``variant`` at all, so `variant`'s current bytecode is exactly what gets copied.
        """
        fd, path = tempfile.mkstemp(suffix=".bin")
        os.close(fd)
        try:
            variant.save(path)
            scan_variant = rvt.load(path)
        finally:
            os.unlink(path)
        return scan_variant, scan_variant.multiplayer

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

    def _add_trigger(self):
        # Trigger::max_triggers (320) is a real engine-level cap, not a bug -- see
        # _compile_nested_body's own docstring for why this compiler's own "always a real, separate
        # trigger, never inline" strategy costs more triggers than the native compiler's would for
        # the same script (confirmed a real case: RCC Onslaught v13.bin's full script hits exactly
        # this). Converted to UnsupportedConstruct here, the one place every add_trigger() call in
        # this class goes through, so any of them hitting the cap falls back to the native compiler
        # cleanly instead of crashing on an uncaught RuntimeError.
        try:
            return self._mp.add_trigger()
        except RuntimeError as exc:
            raise UnsupportedConstruct(f"ran out of triggers (engine limit 320): {exc}") from exc

    def compile(self, script) -> None:
        # A compile REPLACES the variant's own script, same as the native compiler's own
        # compile_script() (confirmed in its own compiler.cpp: "triggers.clear(); ... entryPoints =
        # this->results.events;") -- not append onto whatever triggers `variant` happened to already
        # carry from however it was loaded. This must run *after* __init__'s own _scan_templates()
        # (which reads the variant's pre-clear script to source real Variable/string templates from)
        # but before any add_trigger() call below. Confirmed a real, previously-blocking bug without
        # this: recompiling RCC Onslaught v13.bin (loaded fresh, so still carrying its own 254
        # previously-compiled triggers) silently built a second, redundant copy of the whole script
        # on top of the first instead of replacing it, hitting Limits::max_triggers (320) almost
        # immediately even though the script's own construct set was otherwise fully supported.
        self._mp.clear_triggers()

        # Two passes: allocate every named function's own subroutine trigger FIRST (so a call to a
        # function declared later in the file, or one function calling another, both resolve
        # correctly), then compile bodies -- the top-level trigger's own content, then each
        # function's own body against the now-fully-populated name table.
        function_decls = [s for s in script.body if s.kind == "function"]
        for decl in function_decls:
            if decl.name in self._functions:
                raise UnsupportedConstruct(f"duplicate function declaration {decl.name!r}")
            self._add_trigger()
            index = self._mp.trigger_count - 1
            self._mp.mark_trigger_as_subroutine(index)
            self._functions[decl.name] = index

        event_triggers = [s for s in script.body if s.kind == "on"]
        top = self._add_trigger()
        other_statements = [s for s in script.body if s.kind not in ("function", "on")]
        # Both bodies below are a freshly-allocated trigger's *entire* content -- nothing else is
        # ever appended afterward -- so each is in tail position from the start (see _compile_if's
        # own docstring).
        self._compile_statements(other_statements, top, tail=True)

        for decl in function_decls:
            self._compile_statements(decl.body, self._mp.trigger(self._functions[decl.name]), tail=True)

        for event_stmt in event_triggers:
            self._compile_event_trigger(event_stmt)

        # See _MAX_CONDITIONS/_MAX_ACTIONS's own docstring: unlike Limits::max_triggers, nothing in
        # the native save path itself catches this, so it must be checked explicitly, after
        # everything above has finished building (this reflects the true total across every trigger
        # and every inline nested scope combined, not just this trigger's own opcode_count).
        counts = self._mp.get_full_size_data().counts
        if counts["conditions"] > _MAX_CONDITIONS:
            raise UnsupportedConstruct(
                f"compiled script needs {counts['conditions']} conditions, only {_MAX_CONDITIONS} allowed"
            )
        if counts["actions"] > _MAX_ACTIONS:
            raise UnsupportedConstruct(
                f"compiled script needs {counts['actions']} actions, only {_MAX_ACTIONS} allowed"
            )

    def _compile_event_trigger(self, stmt) -> None:
        # "on <event>: <statement>" is top-level only -- real Megalo has no nested event bindings.
        entry_type = _EVENT_ENTRY_TYPES.get(stmt.event)
        if entry_type is None:
            raise UnsupportedConstruct(f"event {stmt.event!r} is not supported yet")
        self._add_trigger()
        index = self._mp.trigger_count - 1
        self._mp.bind_trigger_as_event(index, getattr(self._rvt.TriggerEntryType, entry_type))
        # This statement is the entire trigger's own body -- nothing else is ever added to `trigger`
        # afterward, so it's always in tail position (see _compile_if's own docstring).
        self._compile_statement(stmt.body, self._mp.trigger(index), tail=True)

    def _compile_statements(self, statements, trigger, *, tail: bool = False) -> None:
        # `tail` is true only for the LAST statement in `statements`, and only when `statements`
        # itself is already known to be in tail position relative to its own enclosing trigger (see
        # _compile_if's own docstring for what that unlocks and why it's safe).
        last_index = len(statements) - 1
        for i, stmt in enumerate(statements):
            self._compile_statement(stmt, trigger, tail=tail and i == last_index)

    def _compile_statement(self, stmt, trigger, *, tail: bool = False) -> None:
        if stmt.kind == "assign":
            self._compile_assign(stmt, trigger)
        elif stmt.kind == "if":
            self._compile_if(stmt, trigger, tail=tail)
        elif stmt.kind == "expr_stmt":
            self._compile_call_statement(stmt.expr, trigger, out_target=None)
        elif stmt.kind == "for_each":
            self._compile_for_each(stmt, trigger)
        elif stmt.kind == "do":
            # Unlike "if", a "do ... end" block has no condition of its own -- it's pure grouping,
            # not gating -- so splicing its statements directly into the parent trigger always
            # preserves the exact same runtime behavior, in every position, not just tail position
            # (see _compile_if's own docstring for why "if" can't always do this). No wrapper opcode
            # or extra trigger needed at all, ever -- confirmed a real, previously-unnecessary cost:
            # every "do" block in RCC Onslaught v13.bin's own script was paying for an unneeded "Run
            # Inline Nested Trigger" wrapper action for zero semantic benefit. `tail` still threads
            # through unchanged, since splicing doesn't change whether this do-block's own last
            # statement is in tail position relative to the enclosing trigger.
            self._compile_statements(stmt.body, trigger, tail=tail)
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
        trial = typeinfo.create()
        if not hasattr(trial, "value"):
            # A composite argument type (e.g. PlayerSetArgument) rather than a plain enum -- needs
            # its own dedicated handling (see _build_player_set_arg for the one confirmed real
            # case), not this generic brute-force mechanism.
            return None
        cache_key = (typeinfo.internal_name, expr.name)
        cached = self._enum_cache.get(cache_key)
        if cached is not None:
            trial.value = cached
            return trial
        for k in range(_ENUM_BRUTE_FORCE_LIMIT):
            try:
                trial.value = k
                text = trial.decompile(self._variant)
            except Exception:  # noqa: BLE001 -- signals "value out of range for this enum family"
                # Confirmed a real case: SoundArgument.value's own setter raises TypeError once k
                # overflows whatever narrower integer width it actually stores (128 for a real
                # sound argument in RCC Onslaught v13.bin) -- not just .decompile() that can fail
                # once the brute-force search runs past the family's real value range.
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

    def _build_player_set_argument(self, exprs, typeinfo):
        """PlayerSetArgument (e.g. ``set_waypoint_visibility``'s own argument) has no ``.value`` at
        all -- it's a composite (``set_type``/``player``/``add_or_remove``), not a plain enum
        (confirmed: the generic brute-force enum fallback crashes on it directly with no ``.value``
        attribute). Real usage in RCC Onslaught v13.bin is one of the 4 simple bare-identifier forms
        (1 call value) or ``PlayerSetType.specific_player``, decompiled as ``mod_player, <player>,
        <0-or-1>`` (3 call values -- note this is RVT's own decompiled keyword, not the official
        reference's "player" -- see module docstring for why the two dialects' keywords can differ
        for the same opcode). ``normal`` (the 6th ``PlayerSetType`` member) has no confirmed real
        example, so its own call syntax isn't known -- not supported yet. Returns ``(values consumed
        including the type/keyword, the built argument)``.
        """
        if not exprs or exprs[0].kind != "identifier":
            raise UnsupportedConstruct("a player-set argument's first call value must be an identifier")
        name = exprs[0].name
        if name in ("no_one", "everyone", "allies", "enemies"):
            arg = typeinfo.create()
            arg.set_type = getattr(self._rvt.PlayerSetType, name)
            return 1, arg
        if name == "mod_player":
            if len(exprs) < 3:
                raise UnsupportedConstruct("'mod_player' needs 2 more call values (a player, then 0 or 1)")
            if exprs[2].kind != "int":
                raise UnsupportedConstruct("a player-set argument's add_or_remove value must be a plain integer")
            if self._templates.literal_scalar is None:
                raise UnsupportedConstruct(
                    "this variant's own script has no existing integer literal to source a "
                    "player-set argument's add_or_remove value from"
                )
            arg = typeinfo.create()
            arg.set_type = self._rvt.PlayerSetType.specific_player
            arg.player.copy_from(self._build_argument(exprs[1], arg.player.get_variable_typeinfo()))
            arg.add_or_remove.copy_from(self._templates.literal_scalar)
            arg.add_or_remove.index = exprs[2].value
            return 3, arg
        raise UnsupportedConstruct(
            "a player-set argument's first call value must be one of "
            "no_one/everyone/allies/enemies/mod_player"
        )

    def _build_format_string_argument(self, exprs, typeinfo):
        """A format string (e.g. ``set_objective_text``'s own argument, quoted in call syntax) is a
        real, persistent entry in the variant's own string table (``mp.script_strings.add_new()``,
        confirmed constructible and settable via ``ReachString.set_content()``/
        ``FormatStringArgument.string =``, unlike most argument types touched by this module which
        have no constructor at all) -- not just a plain string value.

        A format string can also embed ``%n``/``%p``-style replacement tokens (e.g. ``"...%n points
        to win."``, ``"%p's drop pod crushed %p"``), each consuming one *extra* call-syntax value for
        the token's own source (confirmed real cases in RCC Onslaught v13.bin, both ``%n`` -> a
        number and ``%p`` -> a player). The tokens live as *separate* metadata
        (``FormatStringArgument.token_count``/``.token(i).type``/``.value``, up to 2 -- confirmed
        settable directly, unlike most of what this module touches) alongside the string's own
        literal text (which keeps the ``%n``/``%p`` characters as plain text -- confirmed directly:
        setting the string content alone does not auto-populate ``token_count``). Each token's own
        value is built the same way as any other "_any_variable" operand (this module's own general
        variable-resolution machinery, not a special case) and then unwrapped via ``.variable.clone()``
        -- the concrete class that comes back (``ScalarVariable`` for ``%n``, ``PlayerVariable`` for
        ``%p``) already matches what the token slot itself needs, confirmed directly against real
        token values in RCC Onslaught v13.bin, no ``copy_from()`` dance required. Any placeholder
        character other than ``%n``/``%p`` isn't supported yet (no confirmed real example to build
        the type mapping from).

        Reuses a real, already-present string with the exact same text (``_Templates.strings``, the
        same self-sourcing principle as every other template in this module) before ever adding a
        new one -- the string table's own capacity is fixed (confirmed 112 entries) and
        ``add_new()`` returns ``None`` rather than raising once full, confirmed a real case
        recompiling RCC Onslaught v13.bin's own script completely unedited: every format-string call
        naively add_new()-ing its own fresh entry exhausted the table almost immediately, even
        though the variant already had every one of those exact strings somewhere in its own table
        already (recompiling something unedited should reuse what's already there, not duplicate it).

        Returns ``(values consumed, the built argument)``.
        """
        if not exprs or exprs[0].kind != "string":
            raise UnsupportedConstruct("a format-string argument's first call value must be a quoted string")
        text = _unescape_string_literal(exprs[0].value)
        token_types = []
        for placeholder in re.findall(r"%[a-zA-Z]", text):
            token_type = _FORMAT_STRING_TOKEN_TYPES.get(placeholder)
            if token_type is None:
                raise UnsupportedConstruct(f"format-string token {placeholder!r} is not supported yet")
            token_types.append(token_type)
        if len(token_types) > 2:
            raise UnsupportedConstruct("a format string can have at most 2 tokens")
        if len(exprs) - 1 < len(token_types):
            raise UnsupportedConstruct(f"this format string needs {len(token_types)} more call value(s)")

        arg = typeinfo.create()
        existing = self._templates.strings.get(text)
        if existing is not None:
            arg.string = existing
        else:
            new_string = self._mp.script_strings.add_new()
            if new_string is None:
                self._raise_string_table_full()
            new_string.set_content(self._rvt.Language.english, text)
            self._templates.strings[text] = new_string
            arg.string = new_string

        arg.token_count = len(token_types)
        any_variable_typeinfo = self._modify_variable.arguments[1].typeinfo
        for i, token_type_name in enumerate(token_types):
            token = arg.token(i)
            token.type = getattr(self._rvt.OpcodeStringTokenType, token_type_name)
            wrapped = self._build_argument(exprs[1 + i], any_variable_typeinfo)
            token.value = wrapped.variable.clone()
        return 1 + len(token_types), arg

    def _raise_string_table_full(self):
        # add_new() returns None rather than raising once the string table's own fixed capacity
        # (confirmed: 112 entries) is full -- confirmed a real case: RCC Onslaught v13.bin's own
        # string table is already at capacity, which is exactly why reusing an existing matching
        # string (see _build_format_string_argument's own caller) matters, not just an optimization.
        raise UnsupportedConstruct("this variant's own string table is full -- no room for a new string")

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

        # A property (e.g. "current_player.biped.shields = 200") isn't a stored variable at all --
        # it decompiles looking exactly like a plain assignment, but is really its own dedicated
        # action with mapping.type == "property_set" (e.g. "Modify Object Shields"), not the generic
        # "Modify Variable" -- confirmed a real case in RCC Onslaught v13.bin. See
        # _find_property_function's own docstring.
        if stmt.target.kind == "member":
            prop_function, selector = _find_property_function(
                self._rvt, self._variant, stmt.target.name, kind="property_set"
            )
            if prop_function is not None:
                if stmt.value.kind == "call":
                    raise UnsupportedConstruct("a call result can't be assigned into a property")
                self._compile_property_set(
                    prop_function, stmt.target.target, stmt.op, stmt.value, trigger, selector=selector
                )
                return

        if stmt.value.kind == "call":
            if stmt.op != "=":
                raise UnsupportedConstruct(
                    f"a call result can only be plain-assigned ('='), not {stmt.op!r}"
                )
            self._compile_call_statement(stmt.value, trigger, out_target=stmt.target)
            return

        # Reading a property (e.g. "global.number[10] = current_player.biped.health") is likewise
        # its own dedicated action ("Get Object Health", mapping.type == "property_get") with a real
        # out-variable -- reuses the exact same "call with an out-variable" machinery a real call
        # would (property_get functions take no positional args beyond context/out, confirmed
        # directly, so an empty call_args list is correct here, not a special case).
        if stmt.value.kind == "member":
            prop_function, selector = _find_property_function(
                self._rvt, self._variant, stmt.value.name, kind="property_get"
            )
            if prop_function is not None:
                if stmt.op != "=":
                    raise UnsupportedConstruct(
                        f"a property read can only be plain-assigned ('='), not {stmt.op!r}"
                    )
                if selector is not None:
                    # No real property_get action currently uses the selector-argument pattern (see
                    # _find_property_function's own docstring) -- _emit_function_opcode has no way to
                    # set a selector argument, so this fails cleanly rather than silently building a
                    # wrong opcode if the engine ever grows one.
                    raise UnsupportedConstruct(
                        f"property read {stmt.value.name!r} needs a selector argument, which isn't supported yet"
                    )
                action = self._emit_function_opcode(
                    prop_function, stmt.value.target, [], out_target=stmt.target, is_condition=False
                )
                trigger.add_opcode(action)
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

    def _compile_property_set(self, function, context_expr, op, value_expr, trigger, *, selector=None) -> None:
        arg_infos = function.arguments
        context_index = function.mapping.arg_context
        operator_index = function.mapping.arg_operator
        # selector is not None for a shared, multi-property action (e.g. "Modify Player Grenades")
        # whose own selector argument (mapping.arg_name) must be excluded from the operand search --
        # see _find_property_function's own docstring.
        selector_index = function.mapping.arg_name if selector is not None else None
        excluded = {context_index, operator_index} | ({selector_index} if selector_index is not None else set())
        operand_index = next(i for i in range(len(arg_infos)) if i not in excluded)
        if op not in _ASSIGN_OPERATOR_VALUES:
            raise UnsupportedConstruct(f"assignment operator {op!r} is not supported yet")

        action = self._rvt.Action()
        action.function = function
        built = {
            context_index: self._build_argument(context_expr, arg_infos[context_index].typeinfo),
            operand_index: self._build_argument(value_expr, arg_infos[operand_index].typeinfo),
        }
        operator_arg = arg_infos[operator_index].typeinfo.create()
        operator_arg.value = _ASSIGN_OPERATOR_VALUES[op]
        built[operator_index] = operator_arg
        if selector_index is not None:
            selector_arg = arg_infos[selector_index].typeinfo.create()
            selector_arg.value = selector
            built[selector_index] = selector_arg
        for i in range(len(arg_infos)):
            action.add_argument(built[i])
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

        function = _find_function(
            self._rvt, primary_name=method_name, condition=False, call_arg_count=len(expr.args)
        )
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

    def _build_shape_argument(self, exprs, typeinfo):
        """A Shape (``set_shape``'s own argument) is one opcode argument but a *variable* number of
        call-syntax values -- the first names the shape type, and how many more follow depends on
        that type (confirmed against the official reference's own "set_boundary" syntax --
        RVT's "Set Object Shape" is the same underlying Shape argument type -- and against real
        ``set_shape(...)`` calls in RCC Onslaught v13.bin): ``none`` takes no more, ``sphere`` takes
        1 (radius), ``cylinder`` takes 3 (radius, bottom, top), ``box`` takes 4 (width [=radius],
        length, bottom, top). Returns ``(values consumed including the type, the built argument)``.
        """
        if not exprs or exprs[0].kind != "identifier" or exprs[0].name not in _SHAPE_TYPE_FIELDS:
            raise UnsupportedConstruct(
                "a Shape's first call value must be one of none/sphere/cylinder/box"
            )
        shape_type_name = exprs[0].name
        field_names = _SHAPE_TYPE_FIELDS[shape_type_name]
        if len(exprs) - 1 < len(field_names):
            raise UnsupportedConstruct(f"{shape_type_name!r} shape needs {len(field_names)} more call value(s)")
        if self._templates.literal_scalar is None:
            raise UnsupportedConstruct(
                "this variant's own script has no existing integer literal to source a Shape's "
                "dimensions from"
            )

        shape = typeinfo.create()
        shape.shape_type = getattr(self._rvt.ShapeType, shape_type_name)
        for field_name, value_expr in zip(field_names, exprs[1:]):
            if value_expr.kind != "int":
                raise UnsupportedConstruct("a Shape's dimensions must be plain integer literals yet")
            field_arg = getattr(shape, field_name)
            field_arg.copy_from(self._templates.literal_scalar)
            field_arg.index = value_expr.value
        return 1 + len(field_names), shape

    def _build_meter_parameters_argument(self, exprs, typeinfo):
        """A MeterParametersArgument (``set_meter_params``'s own argument, e.g. RCC Onslaught
        v13.bin's real ``script_widget[1].set_meter_params(number, hud_player.number[0], 1200)``) is
        the same "one opcode argument, variable call-syntax value count keyed on the first value"
        shape as Shape/PlayerSet -- ``none`` takes no more, ``number`` takes 2 (numerator,
        denominator), ``timer`` takes 1 (timer). Unlike Shape's dimensions, ``numerator``/
        ``denominator``/``timer`` accept any ordinary variable/literal expression, not just a bare
        int literal (confirmed by the real call above: numerator is a variable reference, denominator
        a bare literal) -- built through this module's own general variable-resolution machinery
        (``_build_argument``) against each field's *own* natural typeinfo (``field.
        get_variable_typeinfo()``, confirmed a real, separate "number"-family typeinfo, not the
        generic "_any_variable" family "Modify Variable"'s own value slot uses -- using the wrong one
        here means the template lookup inside ``_build_argument`` never matches what
        ``_scan_templates`` actually registered these fields under) and then copied into the target's
        embedded, constructor-less ``ScalarVariable``/``TimerVariable`` field via ``Variable.
        copy_from()`` (same "no constructor for an embedded Variable member" gap Shape's own fields
        have -- see ``copy_from``'s own native docstring). Returns ``(values consumed including the
        type keyword, the built argument)``.
        """
        if not exprs or exprs[0].kind != "identifier" or exprs[0].name not in _METER_TYPE_FIELDS:
            raise UnsupportedConstruct(
                "a meter-parameters argument's first call value must be one of none/number/timer"
            )
        meter_type_name = exprs[0].name
        field_names = _METER_TYPE_FIELDS[meter_type_name]
        if len(exprs) - 1 < len(field_names):
            raise UnsupportedConstruct(f"{meter_type_name!r} meter needs {len(field_names)} more call value(s)")

        arg = typeinfo.create()
        arg.type = getattr(self._rvt.MeterType, meter_type_name)
        for field_name, value_expr in zip(field_names, exprs[1:]):
            field = getattr(arg, field_name)
            built = self._build_argument(value_expr, field.get_variable_typeinfo())
            field.copy_from(built)
        return 1 + len(field_names), arg

    def _emit_function_opcode(self, function, context_expr, call_args, *, out_target, is_condition: bool):
        arg_infos = function.arguments
        context_index = function.mapping.arg_context
        out_index = next((i for i, a in enumerate(arg_infos) if a.is_out_variable), None)

        # mapping.arg_context has (at least) two distinct negative sentinels, not one -- confirmed
        # directly: "End Round"/"In Forge" (bare game.end_round()/game.is_in_forge(), no real
        # receiver) use -2, while a genuinely bare call with no dot-prefix at all (rand(10)) uses -1.
        # Both mean "no real context argument slot to build" either way -- the "game." prefix on a
        # -2 call is purely decorative syntax, not a real object reference, so it's fine (and
        # correct) to just ignore context_expr whenever context_index is negative, regardless of
        # which sentinel or whether a decorative prefix happened to parse into context_expr at all.
        if context_index >= 0 and context_expr is None:
            raise UnsupportedConstruct(f"{function.name!r} needs a call target before the dot")
        if (out_index is not None) != (out_target is not None):
            raise UnsupportedConstruct(
                f"{function.name!r} {'requires' if out_index is not None else 'has no'} a result to assign"
            )

        positional_indices = _CALL_ARGUMENT_ORDER_OVERRIDES.get(function.name) or [
            i for i in range(len(arg_infos)) if i != context_index and i != out_index
        ]

        opcode = self._rvt.Condition() if is_condition else self._rvt.Action()
        opcode.function = function
        built_by_index = {}
        if context_index >= 0:
            built_by_index[context_index] = self._build_argument(context_expr, arg_infos[context_index].typeinfo)
        if out_index is not None:
            built_by_index[out_index] = self._build_argument(out_target, arg_infos[out_index].typeinfo)

        # Most positional slots consume exactly one call-syntax value each, but a Vector3 (e.g.
        # attach_to's "offset", written "0, 0, -2" -- confirmed via Vector3Argument.x/y/z) always
        # consumes 3, and a Shape (see _build_shape_argument's own docstring) consumes a variable
        # number depending on its own first value -- so this has to be a single forward pass with a
        # running cursor, not a separate up-front count check against a per-position constant.
        call_arg_cursor = 0
        for i in positional_indices:
            typeinfo = arg_infos[i].typeinfo
            if call_arg_cursor >= len(call_args):
                raise UnsupportedConstruct(f"{function.name!r} needs more call arguments than given")
            if typeinfo.internal_name == "_vector3":
                if call_arg_cursor + 3 > len(call_args):
                    raise UnsupportedConstruct(f"{function.name!r} needs more call arguments than given")
                built_by_index[i] = self._build_vector3_argument(
                    call_args[call_arg_cursor : call_arg_cursor + 3], typeinfo
                )
                call_arg_cursor += 3
            elif typeinfo.internal_name == "_shape":
                consumed, built = self._build_shape_argument(call_args[call_arg_cursor:], typeinfo)
                built_by_index[i] = built
                call_arg_cursor += consumed
            elif typeinfo.internal_name == "_player_set":
                consumed, built = self._build_player_set_argument(call_args[call_arg_cursor:], typeinfo)
                built_by_index[i] = built
                call_arg_cursor += consumed
            elif typeinfo.internal_name == "_format_string":
                consumed, built = self._build_format_string_argument(call_args[call_arg_cursor:], typeinfo)
                built_by_index[i] = built
                call_arg_cursor += consumed
            elif typeinfo.internal_name == "_meter_parameters":
                consumed, built = self._build_meter_parameters_argument(call_args[call_arg_cursor:], typeinfo)
                built_by_index[i] = built
                call_arg_cursor += consumed
            else:
                built_by_index[i] = self._build_argument(call_args[call_arg_cursor], typeinfo)
                call_arg_cursor += 1
        if call_arg_cursor != len(call_args):
            raise UnsupportedConstruct(
                f"{function.name!r} expects {call_arg_cursor} call argument(s), got {len(call_args)}"
            )

        for i in range(len(arg_infos)):
            opcode.add_argument(built_by_index[i])
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
            function = _find_function(
                self._rvt, primary_name=method_name, condition=True, call_arg_count=len(expr.args)
            )
            if function is None:
                raise UnsupportedConstruct(f"no condition function found for call {method_name!r}")
            condition = self._emit_function_opcode(
                function, context_expr, expr.args, out_target=None, is_condition=True
            )
        else:
            raise UnsupportedConstruct(f"expression kind {expr.kind!r} is not supported as a condition yet")

        condition.inverted = inverted
        condition.or_group = or_group
        trigger.add_opcode(condition)

    def _compile_condition(self, condition_expr, trigger) -> None:
        """Builds ``condition_expr`` as one or more ``Condition`` opcodes with the right
        ``or_group`` values for the engine's own flat model (AND across groups, OR within one) --
        see :func:`_next_or_group`'s own docstring for how that was confirmed.

        The grammar's own precedence (``or_expr := and_expr ("or" and_expr)*``) means ``or`` is
        always the *outermost* operator wherever it appears without explicit parens -- so splitting
        on top-level ``or`` first (:func:`_split_disjuncts`) and then each resulting disjunct on top-
        level ``and`` (:func:`_split_conjuncts`) already reaches every simple term for an ordinary,
        unparenthesized condition, with no deeper recursion needed. When there's genuinely only one
        disjunct (no top-level ``or`` at all), each of its conjuncts gets its own group directly
        (the common case, and also what already correctly handles a *conjunct* that's itself a flat
        OR, e.g. ``(a or b) and c`` -- unaffected by anything below). When there's more than one
        disjunct and at least one of them is itself an AND-chain (e.g. ``a and b or c`` -- confirmed
        a real case in RCC Onslaught v13.bin), the flat model can't represent that directly and needs
        real CNF distribution: ``(a and b) or c`` == ``(a or c) and (b or c)`` -- the cartesian
        product across each disjunct's own conjunct list gives exactly that, generalized to any
        number of disjuncts/conjuncts. Capped at a small number of resulting groups so a
        pathological expression fails fast with :class:`UnsupportedConstruct` rather than exploding.
        A conjunct that's itself compound in a way this doesn't cover (parenthesized ``or`` nested
        inside an ``and`` that's itself inside an ``or``) safely falls through to
        :func:`_compile_term`'s own "not supported" case rather than being handled wrong.
        """
        disjuncts = self._split_disjuncts(condition_expr)
        if len(disjuncts) == 1:
            for conjunct in self._split_conjuncts(disjuncts[0]):
                or_group = self._next_or_group(trigger)
                for term in self._split_disjuncts(conjunct):
                    self._compile_term(term, trigger, or_group=or_group)
            return

        clauses = [self._split_conjuncts(d) for d in disjuncts]
        total_groups = 1
        for clause in clauses:
            total_groups *= len(clause)
            if total_groups > 16:
                raise UnsupportedConstruct(
                    "this condition's and/or combination is too large to expand safely"
                )
        for combination in itertools.product(*clauses):
            or_group = self._next_or_group(trigger)
            for term in combination:
                self._compile_term(term, trigger, or_group=or_group)

    def _compile_if(self, stmt, trigger, *, tail: bool = False) -> None:
        """A Megalo trigger's conditions gate *every* opcode that follows them in that same
        trigger's own flat opcode list, not just an "if" body -- there's no way to gate a span and
        then resume ungated execution afterward within one trigger. That's why an "if" ordinarily
        needs its own wrapper (a real nested Trigger, or an inline "Run Inline Nested Trigger" scope
        -- see _compile_nested_body's own docstring) to isolate its body's conditional execution from
        whatever comes after it.

        ``tail`` (propagated from _compile_statements, true only for the last statement of a
        statement list that is itself already known to be in tail position all the way up to its own
        enclosing trigger) means nothing *does* come after this "if" within that trigger -- so its
        conditions and body can be appended directly, with no wrapper at all: the same runtime
        behavior, for less than the wrapper's own added action-opcode cost. This is a real, previously
        significant cost: even after removing "do" blocks' own unnecessary wrapper (see
        _compile_statement's own "do" case), RCC Onslaught v13.bin's own script -- which nests deeply
        but, like most real control flow, mostly ends its own containing block right after its last
        "if" -- exceeded the real Reach file format's own compiled-script byte budget (0x5028 bytes,
        confirmed via the vendored engine's own save-time check) purely from unwrapped-if-body cost
        this removes. Still deterministic over the parsed AST alone (not recovered from lossy
        decompiled text) -- "is this the last statement in its own tail-positioned list" is a
        structural fact about the source, not a guess.
        """
        if stmt.altif_clauses or stmt.alt_body is not None:
            raise UnsupportedConstruct("'altif'/'alt' clauses are not supported yet")
        self._compile_condition(stmt.condition, trigger)
        if tail:
            self._compile_statements(stmt.body, trigger, tail=True)
        else:
            self._compile_nested_body(stmt.body, trigger)

    # -- for each ------------------------------------------------------------------------------

    def _resolve_forge_label_index(self, label_expr) -> int:
        if label_expr.kind == "int":
            index = label_expr.value
        elif label_expr.kind == "string":
            # See _unescape_string_literal's own docstring -- label_expr.value is raw AST text, not
            # the real content a stored name would compare equal to.
            label_text = _unescape_string_literal(label_expr.value)
            matches = [
                i
                for i in range(self._mp.forge_label_count)
                if self._mp.forge_label(i).name is not None
                and self._mp.forge_label(i).name.get_content(self._rvt.Language.english) == label_text
            ]
            if len(matches) != 1:
                raise UnsupportedConstruct(f"no unique forge label named {label_text!r} in this variant")
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
        """Builds ``body`` and wires it to run from ``trigger`` -- inline (embedded directly in
        ``trigger``'s own opcode list via "Run Inline Nested Trigger", zero extra trigger slots) for
        a plain ``if``/``do`` body, or as a real, separate subroutine ``Trigger`` (called via "Run
        Nested Trigger") when ``block_type``/``forge_label_index`` is given -- a ``for each`` loop's
        block_type/forge_label only exist on a real ``Trigger``, an inline scope has neither.

        Deterministic either way: this is a fixed rule over the parsed AST (inline unless the caller
        specifically needs trigger-only fields), not a decision recovered from lossy decompiled text
        the way the native compiler's own ``bInlineIfs`` is -- compiling the same source always
        produces the same structure, so this doesn't reintroduce the non-determinism that was the
        whole reason this compiler exists (see module docstring's "Why this exists"). Inlining is
        also what actually keeps a large, deeply-nested script within the engine's own
        ``Limits::max_triggers`` (320) -- confirmed a real, previously-blocking case: RCC Onslaught
        v13.bin's full script, every construct in which was already otherwise supported, hit exactly
        that cap when every nested body cost a real trigger; the "Run Inline Nested Trigger" opcode
        (``MegaloScopeArgument`` -- confirmed via ``test_construct_inline_trigger_with_a_nested_
        action_persists_through_save_reload`` in ``test_megalo_engine_ast_bindings.py``, including a
        real save/reload, before this was written) is the native compiler's own real answer to
        exactly this, not a workaround invented here.
        """
        # Either way, `body` becomes a brand-new scope/trigger's *entire* content -- nothing else is
        # ever appended afterward -- so it's in tail position from the start (see _compile_if's own
        # docstring), same as the top-level trigger/function bodies compile() itself builds.
        if block_type is None and forge_label_index is None:
            outer = self._rvt.Action()
            outer.function = self._run_inline_nested_trigger
            scope_arg = self._run_inline_nested_trigger.arguments[0].typeinfo.create()
            self._compile_statements(body, scope_arg.data, tail=True)
            outer.add_argument(scope_arg)
            trigger.add_opcode(outer)
            return

        child = self._add_trigger()
        child_index = self._mp.trigger_count - 1
        self._mp.mark_trigger_as_subroutine(child_index)
        if forge_label_index is not None:
            self._mp.mark_trigger_forge_label(child_index, forge_label_index)
        else:
            self._mp.mark_trigger_block_type(child_index, block_type)
        self._compile_statements(body, child, tail=True)

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
