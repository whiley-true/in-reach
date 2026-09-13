# in-reach script layer — TO_IMPLEMENT

Status: consolidated design, re-checked against the two prior prototypes on disk
(`D:\whileyRepos\in-reach-v1 (dis)`, `D:\whileyRepos\in-reach-v2 (dis)`) that this repo's own
`CLAUDE.md` names as read-only reference material. The original draft of this design was written
without access to either repo; this document keeps that draft's structure and its decisions, but
corrects every place where those decisions collided with something the prior repos actually
confirmed (grammar, engine limits, a working headless compiler, a shipped VCS design), and calls out
the couple of places where prior research quietly disagrees with an earlier assumption here.

Scope: the script-management half of in-reach. Map tools are out of scope here.

Everything below still lowers to plain RVT (Cobb's ReachVariantTool) dialect. RVT stays the compiler
of record; in-reach owns everything before that. What changes in this pass is how much of "RVT" is
actually available to lean on already — see §10.

---

## 0. What prior research changes, in one pass

Read this section first; the rest of the document is the detail behind each line.

1. **RVT's compiler is not a GUI-only thing you paste into.** `in-reach-v2`'s `mide/rvt_headless.py`
   calls the exact same pybind11-bound engine methods RVT's own `--headless --recompile` CLI uses
   (`GameVariant.multiplayer.compile_script(source)` / `.save(path)`), fully in-process, no `.exe`
   involved. `compile_script()` returns a result object with `.success` and
   `fatal_errors`/`errors`/`warnings`/`notices`, each a `(line, col, text)` message. This closes the
   open question of whether RVT exposes a headless compile (§0.1 item 4) outright: RVT automation is
   not a nightly corpus job, it's the interactive fast loop *and* the oracle, from milestone 1
   onward. See §10.
2. **The engine's real storage-pool caps are smaller and richer than this design's original
   guesses**, and were pulled straight from `Megalo::Limits` and `variables_and_scopes.cpp` in the
   vendored RVE source under `in-reach-v2 (dis)/refactor/ReachVariantEditor/`. `global.number = 12`
   was right; everything else in that table needed either a correction or a number it didn't have at
   all (per-pool timer/team/player/object caps, `max_triggers`, `max_conditions`, `max_actions`). See
   §3.
3. **Comments are already real, compileable Megalo syntax** (`-- text` to end of line), confirmed
   directly via `compile_script()` in `in-reach-v2`. The open question of whether `-- @` annotations
   need a second mini-parser bolted onto a plain lexer, or should be promoted to real keywords
   (§0.1 item 3), is resolved in favor of the simpler option: comments were never going to break the
   compiler either way, so annotation-as-comment is safe to commit to now, not a placeholder pending
   `mgl/2`. See §4.7.
4. **The confirmed grammar has no `|=` operator.** `_ASSIGN_OPS` is exactly
   `{"=", "+=", "-=", "*=", "/=", "%="}`; bitwise OR (`|`) exists only as a binary *expression*
   operator. §4.3's `bit_set` lowering (`cx.c_flags |= flag_kit_given`) is not valid Megalo — it
   needs to lower to `cx.c_flags = cx.c_flags | flag_kit_given` instead. See §4.3.
5. **`alt`/`altif` are the confirmed working "else"/"else if"; literal `else`/`elseif` are reserved
   but do nothing** (the compiler rejects them by name, with no handler ever wired up server-side).
   This document already assumed this correctly (it's called out directly in this repo's own
   `CLAUDE.md`) — this is confirmation, not a correction, but it's confirmed hard enough (a compiler
   error message quoted verbatim, a `Compiler::is_keyword()` comment saying `// reserved`) that it's
   worth treating as settled, not "prior research."
6. **A working pybind11 binding of the whole engine already exists** — `_reachvarianttool`, prebuilt
   for `cp314-win_amd64`, plus two from-scratch AST layers over it
   (`in-reach-v2 (dis)/refactor/mide/megalo_ast/`: a ~1,700-line text-grammar layer already validated
   against 5 real fixtures, and a read-only binding onto the engine's own compiled Trigger/Opcode
   graph). Milestone 1 in §12 ("Parser + lossless emitter...") is a *port*, not a from-scratch write
   — see §12.
7. **Megalo triggers are flat opcode lists at the engine level; nesting is purely positional** (a run
   of Condition opcodes opens an if-level, and *everything remaining in the same flat list* becomes
   its body, recursively — not just up to the next condition run). This is the compiler's own
   business, not something the text-level linker described here needs to reproduce — RVT already
   lowers structured `if ... then ... end` text into that shape — but it's the reason the engine
   exposes exactly one real looping construct (`for_each_*`, itself a "Run Nested Trigger" to a
   specially-typed trigger) and a genuine subroutine mechanism. That subroutine mechanism is a
   second, already-existing alternative to §7's fragment-fusion scheme for the "shared preamble"
   problem — worth an explicit decision, not an oversight. See §7.
8. **A prior prototype already tried a flatter version of "modules" and hit exactly the problem this
   design's linker exists to solve.** `in-reach-v1`'s own `CLAUDE.md` describes (not yet built)
   `cfg/script/manifest.json` + `declarations.msc` + `modules/*.msc`, compiled by concatenating module
   text into one blob before calling `compile_script()` — no abstract storage, no kinds, no linker.
   Its own writeup names the failure mode: "no modular imports, comment blocks doing a filename's job,
   colliding aliases." That's independent validation that the abstract-storage/kind/link step
   described in §4/§6 is solving a real, previously-hit problem, not a hypothetical one.
9. **A Dulwich shadow-repo VCS almost identical to §9.6's design (below) was already designed and
   partially shipped** in `in-reach-v2` (`app/vcs.py`): a bare repo at `.inreach/vcs.git`, no working
   tree of its own (the real one is `edit/` on disk), tree built by *recursively walking whatever's
   currently on disk* rather than a fixed file list (deliberately, to make room for modules later), a
   status file (`vcs_status.json`) keyed by commit sha with levels `0 edited / 1 compiles / 2+
   released`, single branch only. It also sketches the most likely shape for cross-project module
   versioning: each module gets its own Dulwich repo, referenced via a git submodule–style gitlink
   tree entry (mode `0o160000`). This design's own "no registry, no versioning beyond a
   `module.toml` field" decision is fine as a v1 cut, but the richer design already exists on paper if
   modules outgrow that. See §5.2/§9.6.
10. **The "ONI EVAC Implementation Guide" that §8 (below) cites for every linter rule (IR001–IR018)
    does not exist anywhere in either prior repo.** It's presumably a separate document the user has;
    nothing here should be read as confirming or disputing those specific rules' section numbers.
    Flagged so nobody goes looking for it in `in-reach-v1`/`in-reach-v2` and comes up empty confused.
    See §8.

---

## 0.1 Decisions taken and open items

**Decided**

| Topic | Decision |
|---|---|
| Canonical source | Text, as a directory of small `.mgl` files. Blocks, node graph, SQLite index and `Compiled.txt` are all derived and disposable. |
| Git | Dulwich drives a *shadow* repo under `.in-reach/history/` (own git dir, worktree = project). It never writes into the user's own repo unless they ask. **A near-identical design already exists in `in-reach-v2`'s `app/vcs.py`** — same bare-repo-plus-recursive-walk shape, at `.inreach/vcs.git`. Reuse its status-level convention (`0 edited / 1 compiles / 2+ released`) rather than inventing a new one. |
| Priority order | Modules + linker → budget panel + linter → env profiles → simulator/test plan. Blocks/nodes UI last. |
| Compile backend | RVT, via the confirmed-working in-process pybind11 binding (§10), not RVT.exe. The planned in-house checker still wraps it; until it's written, the in-house linter is the fast loop and the real compiler is the oracle — but "the oracle" is now a Python function call, not a GUI paste step. |
| Grammar | Cobb's RVT syntax; **confirmed directly** against `in-reach-v2`'s `megalo_ast` grammar and against decompiled fixtures — see §3/§4. |
| Modules | Per project (no registry, no versioning beyond a field in `module.toml`). A richer, already-sketched alternative (gitlink-referenced module repos) exists if this needs to grow later — see item 9 above. |
| IDE | Qt. Blockly later via `QWebEngineView`; LSP is optional. |

**Open** (updated)

1. Tick and timer semantics are largely unmeasured — **still true after checking prior research**.
   Neither `in-reach-v1` nor `in-reach-v2` ever built or ran a probe gametype; `engine_semantics.toml`
   has no prior-repo equivalent to seed from. §11.1's probe-gametype plan is still the way to get this
   data, not a redundant step.
2. Do modules write their trait sets/options/widgets/labels into `settings/*.json` (self-contained
   modules), or only *require* that index N exists (hand-owned settings)? Still open; `in-reach-v1`'s
   abandoned `.msc` design didn't get far enough to answer it either (it never had a linker to do the
   allocating).
3. ~~Annotations are `-- @` comments...~~ **Resolved**: comments are confirmed real, compileable
   Megalo syntax (item 3 above), so committing to `-- @` annotations now (not gating on a future
   `mgl/2` promotion to real keywords) is safe. Keep the second mini-parser; drop the hedge.
4. ~~Whether RVT exposes any headless compile.~~ **Resolved: yes.** See §10 — this was already built
   twice over (once as a Python-native reimplementation, once by shelling out to a patched RVT.exe's
   own `--headless` flag for the separate `.mglo`-writing need). RVT automation is interactive, not a
   nightly job.
5. **New**: module authoring format. This document has assumed `.mgl` text modules throughout so
   far. A prior design note (`in-reach-v2`'s own `CLAUDE.md`, "Modules (unscoped, future)") records
   that its own authors' longer-term direction had already drifted toward *Python-authored* modules
   that compile down to Megalo, precisely because plain-text modules don't compose well at scale.
   Nothing in either prior repo actually implements Python-authored modules, so this isn't a "prior
   research says do X instead" correction — but it is a recorded, deliberate second opinion from the
   same lineage of design work, worth an explicit yes/no rather than inheriting `.mgl`-only by
   default.
6. **New**: preamble/fragment sharing vs. subroutines. §7's fusion mechanism (below) inlines
   fragments to share one preamble per fused trigger. The engine already has a *different*,
   already-working mechanism for "run this shared logic from multiple places": a subroutine trigger
   (`entry_type == subroutine` or any trigger called from more than one place) reached via "Run Nested
   Trigger," left un-inlined as a real call rather than spliced in. That costs one trigger slot (of
   320) plus a "Run Nested Trigger" action per call site, in exchange for zero duplicated code and no
   fusion-legality analysis. Worth deciding, per preamble, which mechanism is cheaper — see §7.

---

## 1. The problem and the spine

Megalo scripts are one long file organised into rigid blocks (declarations, options, triggers with
conditions and actions). They don't compose: every trigger hardcodes slot numbers
(`global.number[3]`), the storage pools are tiny (12 global numbers, 8 player numbers, ...), and the
order of triggers is load-bearing because the whole script runs top to bottom once per tick. A
5,000-line script is unreadable, unreusable and unsafe to edit.

Every feature on the wishlist (git, storage-hack UI, SQLite index, autocomplete, LLM docs, block/node
editors, env substitution, modules, tick simulation) is a producer or consumer of one thing: a proper
intermediate representation of the script.

One engine-level fact worth carrying in your head while designing the linker/fusion passes, confirmed
by reading `in-reach-v2`'s `megalo_ast/engine.py` (itself a line-by-line port of the real decompiler's
`CodeBlock::decompile()`/`Trigger::decompile()`):

> A compiled Trigger is one flat, program-order list of Condition/Action opcodes. There is no nested
> "if" structure at that level. A run of consecutive Condition opcodes opens an if-level, and
> **everything remaining in the same flat list — not just up to the next condition run — becomes that
> if's body, recursively.** The only other block-forming constructs are "Run Nested Trigger" (a
> subroutine call, or an inlined do/for-each/if block when the target is only ever reached from one
> place) and "Run Inline Nested Trigger" (an argument-embedded block, confirmed unused by every real
> fixture examined — MCC-only).

This is why Megalo scripts are written with explicit `if ... then ... end` blocks in text (RVT's
compiler does the lowering from structured text to that flat, fallthrough-to-end-of-list shape) and
why `for each ... do ... end` is not a distinct bytecode construct but sugar over a nested-trigger
call to a specially-typed trigger. None of this changes what the text-level linker described here
needs to emit — it only ever emits structured `if/end` text, same as today — but it explains *why*
the engine has exactly one real loop construct and a real subroutine call mechanism, both of which
matter for §7.

```
 .mgl source files ──parse──▶ AST (lossless) ──analyse──▶ semantic model ──link──▶ Compiled.txt (RVT)
                                  │                            │
                                  ├── block editor              ├── budget panel, linter
                                  ├── node graph                ├── SQLite index
                                  └── LLM-facing docs           └── simulator
```

The **language catalog** (`catalog.json`, §3) sits under all of it: every action, condition,
property, enum literal, parameter type and cap, in one machine-readable file — generated from RVT's
source and pinned to an RVT commit. Now that a working native binding exists (§10), generation can
call the compiler directly for validation (compile a fixture, compare against the catalog's claims)
rather than only static-parsing opcode tables.

---

## 2. Project layout

```
<project>/
  script/
    project.toml            block order, active profile, object kinds, pins, constants, module list
    blocks/                 hand-authored, one file per block keyword
      setup.mgl
      win_check.mgl
    modules/                per-project modules, one directory each
      hill_score/
        module.toml
        hill_score.mgl
        README.md           purpose, assumptions, what to check when it misbehaves
    env/
      dev.env
      release.env
    tests/
      *.yaml                simulator scenarios
  build/                    generated, gitignored
    Compiled.txt            plain RVT text; what you paste into RVT
    declarations.mgl        generated declaration + alias block
    link_map.json           every abstract name -> concrete slot / index, plus budgets and fusion report
    index.db                SQLite query cache
    *.autogenerated.json    (as today)
  settings/                 settings.json, script_settings.json, strings.json (as today)
  schemas/                  (as today)
  .in-reach/
    history/                shadow git repo
```

One naming note worth carrying forward: `in-reach-v2`'s equivalent shadow-repo folder is
`.inreach/vcs.git` (a *bare* repo, no working tree — the real working tree is `edit/`/`script/`
itself). This design's own `.in-reach/history/` should be the same shape (bare, no checkout) for the
same reason: there's no need for a second copy of `script/` on disk just to have something for git to
diff.

Rules: `build/` is never edited by hand and never imported back into `script/`. Object kinds, block
order and slot pins live in `project.toml`, not in code. The system `_env` (install paths, Steam IDs,
logging) is unrelated to `script/env/*.env` and is never read by the linker.

---

## 3. Language catalog

`catalog.json` is the one place engine facts live, generated by `in_reach.catalog.generate --rvt
<commit>` from RVT's source (opcode tables) and script documentation. Regenerating on an RVT update
produces a reviewable diff instead of a rediscovery exercise.

Contents:
- **Actions / conditions**: name, receiver type (player/object/team/game/timer), parameters with
  types and enum domains, whether the call is a value or a statement (rule IR003), notes.
- **Properties**: `spawn_sequence`, `team`, `biped`, `score`, ... with type and read/write.
- **Enum literals**: `no_one`, `allies`, `everyone`, `all_players`, `none`, `elite_tier_1`, ...
- **Caps**: storage pools, temporaries per trigger, engine-resource/counter caps — see the corrected
  tables below.
- **Trigger headers**: see the corrected list below, and their read restrictions.

Consumers: parser (keyword tables), linter, autocomplete/LSP, Blockly palette, node editor, simulator
semantics table, LLM overview generator.

Two things change here given prior research:

- **Generation can validate itself against the real compiler**, not just parse opcode tables — feed
  a fixture through `compile_script()`/`decompile_script()` (§10) and check the catalog's claims
  about a given action/condition/property against what actually compiles.
- **The caps table below replaces this design's original guesses wholesale.** Every number here was
  read directly out of the vendored RVE C++ source under
  `in-reach-v2 (dis)/refactor/ReachVariantEditor/native/src/ReachVariantTool/`
  (`game_variants/components/megalo/limits.h` and `variables_and_scopes.cpp`'s
  `VariableScope(list, max_scalars, max_timers, max_teams, max_players, max_objects)` constructors),
  not observed/inferred.

### Storage pools (confirmed, `variables_and_scopes.cpp`)

| Scope | number (scalar) | timer | team | player | object |
|---|---|---|---|---|---|
| `global` | **12** | 8 | 8 | 8 | 16 |
| `player` | 8 | 4 | 4 | 4 | 4 |
| `object` | 8 | 4 | 2 | 4 | 4 |
| `team` | 8 | 4 | 4 | 4 | 6 |
| `temporary` (per-trigger scratch) | **10** | **0** | 6 | 3 | **8** |

The original guess had `global.number = 12` right and the temporaries row right (10 number / 8
object / 3 player / 6 team — confirmed exactly), but had nothing for `global`'s own
timer/team/player/object caps, or for the `player`/`object`/`team` scope pools at all. Note
**temporaries have no timer pool at all** (`max_timers = 0`) — a fragment/preamble can never
allocate a scratch timer, only a real `player.timer`/`object.timer`/etc. slot; worth its own linter
check if the temporaries budgeting below (§4.6/IR004) doesn't already assume this.

### Engine-resource / counter caps (confirmed, `limits.h`)

| Cap | Value |
|---|---|
| `max_script_traits` | 16 |
| `max_script_widgets` | 4 |
| `max_script_options` | 16 |
| `max_script_option_values` | 8 (per option) |
| `max_script_labels` | 16 |
| `max_script_stats` | 4 |
| `max_triggers` | 320 |
| `max_conditions` | 512 |
| `max_actions` | 1024 |
| `max_string_ids` | 256 |
| `max_variant_strings` | 112 |
| `max_object_types` | 2048 |
| `max_incident_types` | 1024 |
| `max_engine_sounds` | 95 |

Traits/widgets/options/labels match the original "observed" numbers exactly (16/4/16/16) — good sign
those were sound. **Two of the original claims did not turn up anywhere in the confirmed source and
should be treated as unverified, not wrong-but-close:** "scripted objects (256)" (256 is
`max_string_ids`, not anything called "scripted objects" in the source — possibly a mix-up, or a
genuinely different limit not covered by this pass) and "palettes (6)" (the one requisition-palette
constant found, `cobb::bitmax(4)` in `opcode_arg_types/all_indices.h`, works out to 15, not 6 — could
be a different, per-map palette count this pass didn't locate). Don't ship either number in
`catalog.json` without re-deriving it.

`max_triggers`/`max_conditions`/`max_actions` are exactly the RVT counters IR012 needs — use these,
not placeholders, once that rule is implemented.

### Trigger headers (corrected)

The original list was: `on init`, `on pregame`, `on local`, `on host migration`, plain. The engine
binding (`EngineTrigger.entry_type`, a `TriggerEntryType` enum member name) confirms **two more
distinct entry types that list omitted**: `on_local_init` and `on_object_death`, plus `subroutine`
(a trigger that only ever runs when called via "Run Nested Trigger" — see §7). Confirmed literal
source spellings, read directly off decompiled fixtures in
`in-reach-v2 (dis)/refactor/tests/resources/`:

```
on init: ...
on local: ...
on pregame: ...
on host migration: ...
```

`on_local_init`, `on_object_death`, and how a script text authors a `subroutine`-entry trigger were
**not** found spelled out in any of the 5 fixtures checked (`blank_ff`, `blank_mp`, `infection`,
`invasion`, `juggernaut`) — they exist at the engine level but this pass didn't confirm their literal
`on ...:` text form. Confirm against a fixture that actually uses them (or against
`compile_script()` directly, the way every other grammar claim in `in-reach-v2` was checked) before
the catalog asserts a spelling for them.

`catalog/engine_semantics.toml` is a sibling file for *measured* runtime facts (tick rate, timer
units, evaluation order, `apply_traits` lifetime). Values start as `null` and are filled in from the
probe gametype (§11.1, still not done by anyone). The simulator reads it and refuses to guess where
it is `null`.

---

## 4. The `.mgl` dialect

A strict superset of the RVT dialect: anything RVT accepts is valid `.mgl` and lowers to itself.
Extensions are `-- @` annotation comments and `${...}` constants. Every claim below was checked
against `in-reach-v2 (dis)/refactor/mide/megalo_ast/{nodes,lexer,parser}.py`'s own docstrings, each
of which documents having been confirmed directly via `compile_script()`, not inferred from
decompiled examples alone.

**Confirmed real, already-working RVT syntax** (not inreach inventions layered on top — genuinely
part of the dialect `compile_script()` already accepts):
- `-- text` line comments, to end of line.
- `alias <name> = <expr>` — a compile-time-only local name, resolved away in the compiled output
  (decompiling a variant that used one shows the aliased expression, not the alias name). This is
  good news for §6's linker: emitting `alias` lines for abstract storage names is leaning on a real
  compiler feature, not inventing new compile-time semantics RVT has to somehow tolerate.
- `if <cond> then <body> [altif <cond> then <body>]* [alt <body>] end` — `alt`/`altif` are the real,
  working "else"/"else if." Literal `else`/`elseif` are reserved words that are parsed but rejected
  ("Word \"else\" is reserved for potential future use as a keyword. It cannot appear here.") — never
  emit them.
- `declare <scope>.<type>[<index>] [with network priority <priority>] [= <value>]`.
- `for each <selector> [with label <label-val>] [randomly] do <body> end` — `label`/`randomly` may
  appear in either source order; canonicalize on emit (label first), as assumed below.
- Expression grammar, confirmed operator precedence (lowest to highest):
  `or` < `and` < `not` < compare (`==`,`!=`,`<`,`>`,`<=`,`>=`, **non-chaining** — `a < b < c` is not a
  thing, only one comparison per expression) < `|` (bitwise/flag OR, left-associative) < postfix
  (`.`, `[]`, `()`).
- Compound assignment operators: **exactly** `=`, `+=`, `-=`, `*=`, `/=`, `%=`. **No `|=`, no `&=`, no
  plain binary `+`/`-`/`*`/`/` expression operators at all** — arithmetic only ever happens as a
  compound assignment statement, never inline in an expression.
- Reserved-but-nonfunctional words (parsed, rejected, no production exists or ever will in this
  compiler build): `else`, `elseif`, `enum`, `function`, `inline`.

### 4.1 Abstract storage

Code uses names; the linker allocates slots and emits `alias` lines.

```
-- @number  g_phase             priority=low
-- @number  g_scientists_alive  priority=high
-- @object  g_config            priority=low
-- @player  g_revealer          priority=local
-- @team    g_attackers         priority=low
-- @timer   g_phase_timer       default=6
-- @pnumber p_hud_count         priority=high        player.number
-- @pobject p_carrier           priority=low         player.object
-- @pplayer p_reviver           priority=low         player.player
-- @pteam   p_home              priority=low         player.team
-- @ptimer  p_aa_hold           default=1            player.timer
-- @tnumber team3.tc_mines_alive priority=low        team storage used as round-level state
```

Object-side storage is declared against a **kind** (§4.2):

```
-- @onumber carrier.c_role
-- @onumber carrier.c_flags
-- @oobject carrier.c_carrier_b
-- @oplayer carrier.c_owner
-- @otimer  carrier.c_bleed_cap default=24 owns_default=true
-- @onumber weapon.w_level
-- @onumber mine.m_armed
```

Lowering (one possible allocation):

```
declare global.number[0] with network priority low      -- g_phase
alias g_phase = global.number[0]
declare object.number[0] with network priority low
alias c_role  = object.number[0]                        -- kind carrier
alias w_level = object.number[0]                        -- kind weapon  (shares slot)
alias m_armed = object.number[0]                        -- kind mine    (shares slot)
declare object.timer[0] = 24                            -- carrier owns the default
alias c_bleed_cap = object.timer[0]
```

Cross-check every pool size above against §3's corrected caps table, not the earlier guesses.

### 4.2 Object kinds

A kind is a set of objects always reached the same way (a label, a stored reference, the biped). Two
kinds may share an object slot because no single object is ever two kinds. Declared in
`project.toml`, mergeable from modules:

```toml
[kinds.carrier]
reached_by = ["p_carrier", "c_carrier_b"]
[kinds.weapon]
reached_by = ["label:weap_spawn", "get_weapon"]
[kinds.mine]
reached_by = ["label:mine"]
[kinds.biped]
reached_by = ["biped"]
```

Timer slots are shared only when at most one kind claims `owns_default=true`; every other kind must
assign the timer directly and never call `reset()` (lint IR006b). This is the guide's "Declared
Default" column, enforced.

### 4.3 Bitfields — **correction required**

```
-- @bitfield carrier.c_flags { kit_given, aa_latch, small_scale, boarded, has_spawned, is_johnson }
```

Allocates one `@onumber`, assigns powers of two, emits `alias flag_kit_given = 1` etc. Bit 15 is
reserved; more than 15 flags is an error. Three intrinsics lower to the helper idiom, each costing
one temporary number that the temporaries budget counts. The original design's lowering used a
`|=` compound assignment:

```
bit_set(cx.c_flags, kit_given)           -> cx.c_flags |= flag_kit_given
```

`|=` is not a real compound-assignment operator (confirmed set above, §4). The intrinsic must lower
to a plain assignment using the binary `|` operator instead:

```
bit_set(cx.c_flags, kit_given)           -> cx.c_flags = cx.c_flags | flag_kit_given
bit_clear(cx.c_flags, kit_given)         -> scratch = cx.c_flags; scratch = scratch | flag; ... (as before; already used = / -=, not |=)
if bit_test(cx.c_flags, kit_given) then  -> scratch = cx.c_flags; scratch = scratch | flag; if scratch != 0 then
```

The rest of this section's design (one `@onumber` per bitfield, powers-of-two aliasing, bit 15
reserved, `bit_impl = "and" | "divmod"` project setting via `project.toml`) is unaffected — only the
literal operator emitted by `bit_set`'s expansion needs to change. Re-check any other place in the
codebase/docs that assumed a `|=` or `&=` compound existed.

### 4.4 Engine resources

Trait sets, options, widgets and Forge labels are declared in code, allocated by the linker, and
written into `settings/*.json` in index order. Existing hand-made entries are never moved.

```
-- @trait  t_freeze      { movement_speed = "value_000", jump_height = 0 }
-- @option o_disable_win { type = "toggle", default = 0, name = "DEV disableWin" }
-- @option o_round_mins  { type = "range", min = 1, max = 30, default = 10, name = "Round minutes" }
-- @widget w_scientists  { position = "top_left" }
-- @label  L_hill = "hill"
```

Emits `alias t_freeze = script_traits[N]`, `alias o_disable_win = script_option[N]`, `alias
w_scientists = script_widget[N]`; `with label L_hill` lowers to `with label "hill"` and adds the
label to `script_settings.json`. Strings stay as RVT literals; the linker only counts them. Cross-check
every cap this section relies on against §3's corrected table.

### 4.5 Constants and profiles

`${NAME}` is a compile-time constant. Resolution order: module `[params]` from the importer →
`project.toml [constants]` → active env profile. Unresolved, non-integer where a Number is required,
or outside signed 16-bit is a lower error (IR015).

Conditional compilation removes dev-only code from release builds and reclaims its budget:

```
-- @if DEV
   game.show_message_to(current_player, none, "DEV: in hill")
-- @end
```

`DEV` is any flag listed in the profile's `FLAGS=`. `-- @if !DEV` is allowed. The active profile and
flags are stamped into the `Compiled.txt` header and the shadow-repo commit message.

### 4.6 Fragments (fusion, §7)

A module may author **fragments** instead of whole triggers. A fragment is a loop body plus the
signature of the loop it wants to live in; the linker merges compatible adjacent fragments into one
trigger.

```
-- @fragment HUMAN_PASS.health_tiers
-- @loop     player
-- @gate     g_phase == phase_live
-- @preamble human_ctx           provides cx, cb, role; guards cx != no_object
-- @guard    role == role_marine
-- @traits   layer=injury
-- @fusion   auto                auto | never | force:<group>
```

A **preamble** is a named, shared prologue: the temporaries it allocates, the statements that fill
them, and the guard it establishes. Defined once (in a block file or provided by a module) and
required by fragments.

```
-- @preamble human_ctx
-- @provides cx:object cb:object role:number
cx = current_player.p_carrier
if cx != no_object then
   cb   = cx.c_carrier_b
   role = cx.c_role
-- @guard-end                   fragments are inserted here, inside the guard
end
```

See §7 for the subroutine alternative to this fusion mechanism — the `-- @` syntax itself
(`-- @fragment`, `-- @loop`, `-- @gate`, `-- @preamble`, `-- @guard`, `-- @traits`, `-- @fusion`) is
unaffected by anything prior research found.

### 4.7 Docs

`-- @doc` lines above a trigger, fragment or declaration attach to that AST node, survive
round-trip, and feed the LLM overview. `-- @see TAG` points at a section of the module `README.md`.
`-- @assumes BLOCK` records an ordering assumption the linter checks (IR016). This is now safe to
commit to without the `mgl/2` hedge (comments are confirmed real syntax — see §0.1 item 3).

---

## 5. Manifests

### 5.1 `module.toml`

```toml
[module]
name     = "revive"
version  = "0.3.0"
tags     = ["human", "downed", "medic"]
features = ["F71", "F72", "F73"]          # feature-list rows this module closes
summary  = "Contact revive with meter, heal, freeze and empty-handed catch."

[requires]
global_number  = 0
player_number  = 1
player_timer   = 1
object_number  = { carrier = 2 }          # per kind
object_object  = { carrier = 1 }
team_number    = { team3 = 1 }
traits         = 2
widgets        = 1
options        = 1
labels         = 0
temporaries    = { number = 3, object = 2, player = 1, team = 0 }   # max in any one trigger/fragment
preambles      = ["human_ctx"]

[shared]                                   # reuse if the project already provides them
traits = ["t_freeze"]

[provides]
aliases   = ["p_revive_meter", "c_revive_target", "t_freeze", "t_uncharged"]
blocks    = ["REVIVE_PASS"]
preambles = []

[order]
after  = ["HUMAN_PASS"]
before = ["DOWNED_PASS"]                   # a completed revive clears status this tick
phase  = "live"

[params]
role_medic     = { type = "number", doc = "role constant for Medic" }
revive_seconds = { type = "number", default = 5 }

[kinds]
carrier = { reached_by = ["p_carrier"] }
```

The `[requires]` counts are what the module's own `@` declarations add up to; the linter checks they
agree, so an importer can read the cost without reading the code.

One data point worth keeping in mind while designing `[requires]`/`[provides]`: `in-reach-v1`'s own
(unbuilt) module design, `cfg/script/manifest.json` + `modules/*.msc`, never got as far as a
`[requires]`-style declared-cost manifest at all — it just concatenated module text and let colliding
aliases surface at compile time. That's the exact failure mode `[requires]`/`[provides]` plus the
linker's allocation pass (§6) are designed to prevent. Treat this as validation, not a reason to
simplify — the flatter approach was tried (on paper) and abandoned for scale reasons.

### 5.2 `project.toml`

```toml
[project]
name     = "oni_evac"
dialect  = "mgl/1"
profile  = "dev"
bit_impl = "and"

[blocks]
order = ["BOOTSTRAP", "MAP_ROLL", "ROLE_ASSIGN", "SPAWN", "STAGING", "PLAYER_PASS",
         "DEATH_PASS", "HUMAN_PASS", "DOWNED_PASS", "WIN_CHECK", "HUD_LOCAL"]

[constants]
PHASE_TIMER = 6

[pins]                                     # escape hatch; validated and reported
"p_hud_count" = "player.number[0]"         # widget-driven: must be hud_player.number[0]

[[modules]]
name   = "revive"
params = { role_medic = 3, revive_seconds = "${REVIVE_SECONDS}" }

[kinds]                                    # see §4.2

[caps]                                     # override catalog caps (RVT counters are lower bounds)
triggers = 128
```

### 5.3 Env profiles

```
# script/env/dev.env
FLAGS=DEV,VERBOSE_HUD
PHASE_TIMER=2
REVIVE_SECONDS=2

# script/env/release.env
FLAGS=
PHASE_TIMER=6
REVIVE_SECONDS=5
```

The IDE shows the profile switcher next to **Build**; switching relinks and re-emits `Compiled.txt`.

---

## 6. Linker

Input: parsed block files + imported modules + `project.toml` + active profile. Output:
`build/declarations.mgl`, `build/Compiled.txt`, `build/link_map.json`, updated `settings/*.json`.

1. **Resolve order.** DAG from `[blocks].order` plus every module's `after`/`before`. Topological
   sort. A cycle or unknown block is an error naming the edges.
2. **Merge kinds.** Union module kind tables into the project's. Conflicting `reached_by` claims are
   errors.
3. **Resolve shared resources.** `[shared]` entries bind to an existing provider if present, else
   allocate.
4. **Allocate storage.** Per pool, first-fit honouring `[pins]`. Object pools pack kinds onto slots;
   timer slots share only under the `owns_default` rule. Overflow errors name the pool and the module
   that tipped it.
5. **Allocate engine resources.** Append traits/options/widgets/labels to `settings/*.json` in stable
   order (existing first, then modules in link order).
6. **Substitute constants; strip `@if`** blocks the profile does not enable.
7. **Fuse fragments** (§7).
8. **Lower** bitfield intrinsics and abstract names; emit declarations + concatenated body. Since
   `alias` is confirmed real RVT syntax (§4), this step can emit `alias <abstract-name> =
   <concrete-slot>` lines directly into `Compiled.txt` rather than needing to rewrite every use-site
   of an abstract name into its concrete slot. That's a real compiler feature doing the substitution
   at compile time, not the linker faking it by find-and-replace across the concatenated body —
   cheaper to implement and less error-prone than the alternative.
9. **Emit `link_map.json`** and run the linter over the linked result (some rules only make sense
   post-link: IR004 on fused triggers, IR012 counters).

Allocation is **stable**: an unchanged project relinks to identical slots (order by first-seen, not
by name), so `Compiled.txt` diffs between builds show real changes only.

`link_map.json` shape:

```json
{
  "profile": "dev", "flags": ["DEV"],
  "storage":   { "g_phase": {"slot": "global.number[0]", "owner": "blocks/bootstrap.mgl", "priority": "low"},
                 "c_role":  {"slot": "object.number[0]", "kind": "carrier", "owner": "modules/roles"},
                 "w_level": {"slot": "object.number[0]", "kind": "weapon",  "owner": "blocks/weapon_spawn.mgl"} },
  "resources": { "t_freeze": {"index": 0, "kind": "trait", "owner": "modules/revive", "shared_by": ["modules/staging"]} },
  "budget":    { "global.number": {"cap": 12, "used": 7},
                 "object.number": {"cap": 8, "used": 8, "slots": {"0": ["carrier", "weapon", "mine"]}},
                 "traits": {"cap": 16, "used": 16},
                 "counters": {"triggers": 41, "conditions": 210, "actions": 388, "bits": 91240} },
  "order":     ["BOOTSTRAP", "MAP_ROLL", "...", "REVIVE_PASS", "DOWNED_PASS", "..."],
  "fusion":    { "groups": [ {"trigger": "HUMAN_PASS", "fragments": ["roles.role_traits", "health.tiers"], "saved": {"triggers": 1, "actions": 4, "conditions": 2}} ],
                 "declined": [ {"a": "counts.headcount", "b": "hud.text", "reason": "headcount writes g_humans_alive; hud.text reads it"} ] }
}
```

---

## 7. Fusion (optimization) — plus the subroutine alternative

What fusion saves, with certainty: triggers (an RVT counter and bits) and the repeated **preamble**
every per-player block carries (`cx = current_player.p_carrier; if cx != no_object; role = cx.c_role;
if g_phase == live`). Whether an extra loop pass costs meaningful engine time per tick is unmeasured;
do not optimise for that until the probe (§11.1) says so.

**Mechanism.** Fragments with the same `@loop` and `@gate` that are *adjacent* in the resolved order
are merged into one trigger: loop header once, preamble once, then each fragment's body inside its
own `@guard` as a nested `if`. Guards shared by every fragment in the group are hoisted. Adjacency is
the rule on purpose: predictable output, and users already control adjacency with `after`/`before`. A
scheduler that hoists fragments across other blocks can come later if counters demand it. This is a
text-level transformation the linker performs before ever handing `Compiled.txt` to the real
compiler, and the engine's flat-opcode/positional-if representation (§1) is exactly why sequential
top-level fragments that both start `for each player do` really do cost two separate trigger slots
today, and really can be merged into one `for each player do` with two `if`-guarded bodies inside —
nothing about the engine's internal shape blocks that.

**Legality.** Two loops run "A for every player, then B for every player"; fused they run "A then B
per player". That is identical only when no body reads, on one iteration, state the other wrote on a
different iteration. Iteration-local writes: `current_player.*`, `current_object.*`, the current
carrier, temporaries. Cross-iteration writes: globals, team storage, other players' storage, spawned
objects. Rule: fuse when no fragment in the group writes cross-iteration state another fragment in
the group reads; otherwise keep separate triggers and report why. Overrides: `@fusion never` (side
effects the analysis cannot see, e.g. `place_at_me` ordering) and `@fusion force:<group>`; every
override is listed in `link_map.json`.

**Temporaries.** Fragments are independent, so their scratch temporaries are dead between fragments
and the linker renames them onto a shared pool. A fused trigger needs `preamble temps +
max(fragment temps)`, not the sum. A fragment that hands a value to a later fragment is really a
preamble and must be declared as one.

**Trait order.** `apply_traits` is last-wins per field, and the guide's rule is base → charged →
injury → environment → heroic → reviving → downed → freeze. Fragments declare `@traits layer=…`;
within a fused group the layer is the ordering tiebreaker when no explicit constraint exists, and
IR009 checks that the final order is non-decreasing by layer with freeze last. This is checked across
features, which the hand-written version could not do.

**Visibility.** The budget panel shows fragments → triggers with counters before and after, and every
declined merge with its reason. `Compiled.txt` carries a comment at each fused trigger listing its
fragments. Hand-authored blocks stay whole triggers unless opted into fragments, so migration is
incremental.

**The subroutine alternative.** Prior research adds a second, already-existing engine mechanism for
the same underlying problem fusion solves (repeated preamble/shared logic cost) — a genuine
subroutine call:

> A trigger reached by "Run Nested Trigger" from more than one call site (or a `subroutine`-entry
> trigger nothing calls directly) is **not inlined** by the decompiler — it's left as a real call
> (`EngineTriggerCallStatement`, decompiled as `trigger_N()`). This is a first-class, already-working
> "define once, call from several places" mechanism, no fusion-legality analysis required.

Trade-off, for a shared preamble specifically:

| | Fusion (above) | Subroutine call |
|---|---|---|
| Trigger count | Saves one trigger per fused group | Costs one trigger (the subroutine itself) |
| Per-call cost | Zero (inlined) | One "Run Nested Trigger" action per call site |
| Legality analysis | Required (IR018: no fragment may write cross-iteration state a fused sibling reads) | Not required — a subroutine call has normal, ordinary sequencing; nothing about it is unsound the way merging two loop bodies can be |
| Best fit | Fragments that are genuinely adjacent in resolved block order and share a loop/gate | Logic reused from *non-adjacent* places, or reused across different loop kinds, where fusion's adjacency requirement can't apply at all |

This isn't a call to replace fusion above — adjacency-based fusion is still the right default for the
common case (the worked example in §13, `HILL_PASS`, is exactly the adjacent-same-loop case fusion is
built for). It's a call to make the linker's fragment/preamble model aware that a second lowering
strategy exists and is sometimes strictly better (non-adjacent reuse, or reuse across different
`@loop` kinds where fusion's own adjacency rule can never fire) rather than leaving those cases to
`declined` with no alternative offered. Whether the linker should ever choose subroutine-call lowering
*automatically*, or only ever as an explicit `@fusion` override a module author opts into, is a fair
open question — nothing in prior research answers it, since neither prototype ever built a linker to
make the choice with.

---

## 8. Linter

Rules read the catalog for types, caps and literals; none hardcodes engine facts. Sources refer to
the "ONI EVAC Implementation Guide" section numbers below — **that document was not found anywhere in
`in-reach-v1` or `in-reach-v2`**, so it's presumably something the user has outside of either repo.
Nothing here confirms or disputes those specific rules; they're simply out of scope for what prior
research could check.

| id | rule | source |
|---|---|---|
| IR001 | dereference depth ≤ 2 | 3.1 #1 |
| IR002 | no parenthesised compound `or`; flatten via scratch | 3.1 #2 |
| IR003 | action used as a value (`get_*` inside a condition) | 3.1 #3 |
| IR004 | per-trigger temporaries over cap (post-fusion) | 3.1 #4 |
| IR005 | timer declared with a network priority | 3.1 #5 |
| IR006 | slot declared twice | 3.1 #6 |
| IR006b | `timer.reset()` on a kind that doesn't own the slot default | 3.1 #6 |
| IR007 | `true`/`false` where a Number is required | 3.1 #7 |
| IR008 | `on local:` reads a non-networked global; widget player number not `high` | 3.1 #11 |
| IR009 | trait application order within a trigger / fused group; T0 not last | 5.2 |
| IR010 | unlabelled `for each object do` inside a per-tick trigger | 3.3 |
| IR011 | bitfield uses bit 15; `bit_test` without a spare temporary | 4.8 |
| IR012 | RVT counter budget exceeded (triggers/conditions/actions/strings/bits) | 3.3 / F163 |
| IR013 | module `[order]` constraint violated by a hand edit to `[blocks].order` | 5.2 |
| IR014 | kind alias read on an object reached through a different kind's path | 4.7 |
| IR015 | `${...}` unresolved, non-integer, or out of 16-bit range | §4.5 |
| IR016 | `@assumes BLOCK` not satisfied by the resolved order | 5.2 |
| IR017 | `[requires]` counts disagree with the module's declarations | §5.1 |
| IR018 | fragment writes cross-iteration state read by a fused sibling (only reachable via `force`) | §7 |

Diagnostics carry file, line, rule id, and a one-line fix hint. The IDE shows them in the Problems
panel; the CLI (`in-reach lint`) exits non-zero.

Two rules *are* directly informed by confirmed grammar facts from prior research, though, and are
worth tightening:

- **IR007** (`true`/`false` where a Number is required) — confirmed relevant: the grammar has no
  boolean literal token at all (`lexer.py`'s token kinds are exactly
  `int | percent | string | ident | punct | comment | eof`), so `true`/`false` can only ever appear as
  bare identifiers, which will either resolve to something else entirely or fail to resolve — this
  rule should probably fire on `true`/`false` as identifiers *anywhere*, not just "where a Number is
  required."
- **New rule candidate**: flag `|=`/`&=`/bare binary `+`/`-`/`*`/`/` in emitted or hand-authored `.mgl`
  — none of those are real tokens the compiler accepts; catching this at lint time is strictly better
  than letting RVT's own compiler error surface it after a full link (see §4.3's `bit_set` correction
  for exactly how this bites the design as currently written).

---

## 9. Derived views

### 9.1 Budget panel (Qt)

A view over `link_map.json`: one row per pool with cap/used/free and, for object pools, which kinds
share each slot; engine resources; RVT counters with the configured caps; the fusion report. Clicking
a slot lists every reader and writer (from the index).

### 9.2 SQLite index

`build/index.db`, regenerated on every link, gitignored, never a source of truth.

```
trigger      (id, order_index, block, loop_kind, header, gate, source_file, source_line, fused_from)
statement    (id, trigger_id, index, kind, opcode, args_json, source_file, source_line)
variable     (name, slot, pool, kind, owner)
var_ref      (statement_id, variable, mode)        -- mode: read | write
resource     (name, kind, index, owner)
resource_ref (statement_id, resource)
```

Answers: "who writes `g_phase`", "what runs between X and Y", "which triggers apply T3", and the
read/write dependency graph between triggers (which is also the first node view, §9.4).

`in-reach-v2`'s `mide/commands.py` already ships `generate_ast_json`/`generate_engine_ast_json`
functions producing exactly the two JSON shapes §9.4's node graph and §9.5's tooling would want (a
`Script`/AST dump, and an `EngineAst` dump of the compiled trigger graph). Match those names/shapes
when building the equivalent commands here rather than inventing new ones — there's no reason for
`in_reach`'s own catalog/index tooling to diverge from already-settled naming for the same two
artifacts.

### 9.3 Storage-hack UI

Bitfields render as a bit grid per word (used/free/reserved). Object slots render as a kind × slot
matrix showing sharing. Both are edits to the `@` declarations, not to code.

### 9.4 Block editor and node graph

Both are projections of the AST. Blockly in `QWebEngineView`, one block file at a time; blocks are
generated from the AST and text is re-emitted from blocks, so text stays canonical. AST nodes carry
stable IDs; layout positions live in a sidecar (`build/layout.json`), not in source. The node graph
starts as the auto-generated read/write dependency graph between triggers (already in the index);
drag-and-drop authoring comes later.

### 9.5 Autocomplete and LLM friendliness

Completion and diagnostics implemented once, driven by catalog + semantic model, exposed over LSP
(pygls) so the Qt editor, VS Code and coding agents share them. For LLMs: one file per block,
`README.md` per module, a generated `OVERVIEW.md` (budget table, block order, module list, fusion
report), and an MCP server exposing `lint`, `link`, `query_index`, `simulate`. A model with a linter
and simulator is far more useful than one with a style guide.

### 9.6 Shadow git

Snapshot on every successful link (not on save): commit message `link: <profile> flags=<…>
triggers=<n> conditions=<n> actions=<n> bits=<n>`. The IDE shows a history list and a diff of
`Compiled.txt` between any two snapshots. "Commit to project repo" is a separate, explicit action.

The concrete status-level convention (`0 edited / 1 compiles / 2+ released`, keyed by commit sha in a
sidecar JSON file, not inside the Dulwich repo itself) is worth adopting verbatim rather than
re-deriving — it was already designed, built, and exercised in `in-reach-v2`'s `app/vcs.py` (see
§0.1 item 9 and §2's naming note above). One caveat carried over honestly from that design: its own
author later noted the `1 compiles` label became a misnomer once `apply`/`commit` were split apart (a
commit no longer implies its content actually compiles) — if `in-reach` keeps a similar split between
"link" and "commit," name the status level for what it actually guarantees, not what an earlier
design iteration meant it to guarantee.

---

## 10. RVT integration

The original plan assumed:

> **Paste workflow** until in-house RVT automation exists: Build → open `Compiled.txt` → paste into
> RVT → compile → record RVT's counters in the snapshot (manually, or via the existing OCR path).

**This workflow already has a fully-automated, in-process replacement, built and working in
`in-reach-v2`:**

```python
# in-reach-v2 (dis)/refactor/mide/rvt_headless.py, condensed
rvt = get_rvt()                       # lazy-loads _reachvarianttool.pyd
variant = rvt.load(str(bin_path))
result = variant.multiplayer.compile_script(source_text)
# result.success, .fatal_errors / .errors / .warnings / .notices
# each message: .line, .col, .text
if result.success:
    variant.save(str(dst_path))
```

Confirmed by reading `headless.cpp` directly: RVT's own `--headless --recompile` CLI mode is *exactly*
this same `Megalo::Compiler::parse()`/`.apply()` + `GameVariant::write()` call path, already exposed
by the pybind11 bindings. No GUI, no `.exe` process, no paste step, no OCR is needed for the compile
step at all — a project can call the real Megalo compiler as a plain Python function and get back
structured, line/col-addressable diagnostics.

What this means for the plan above:

- **§0's open item 4 is resolved**: yes, headless compile exists, and a Python-native equivalent
  (bypassing even the need to build/ship a headless-capable `ReachVariantTool.exe`) already exists too.
  RVT is available as the fast loop's own oracle from day one, not a nightly corpus job bolted on
  later.
- **The "Adopt wizard" and "Paste workflow" collapse into one thing**: loading an existing `.bin`,
  decompiling its script (`variant.multiplayer.decompile_script()` — the read-direction counterpart,
  also already bound and exercised), and letting a user name slots/declare kinds against that text is
  exactly what `in-reach-v2`'s `edit_io.write_edit_from_variant()` already does today for its own
  (non-modular) `edit/rvt/script.txt`. Porting that flow is the fast path to an "Adopt" wizard, not
  writing a new decompile-and-annotate step from scratch.
- **A prebuilt native module already exists and is a real distribution constraint, not a future
  problem**: `_reachvarianttool.cp314-win_amd64.pyd` (plus Qt5/zlib DLLs) is a committed binary in
  `in-reach-v2`, ABI-locked to that one CPython build/platform, built from GPLv3-licensed
  `ReachVariantEditor` source. Two things worth carrying into this repo's own packaging plan
  (`CLAUDE.md`'s own "planned pip-installable CLI... wrapping a prebuilt pybind11 extension" framing
  already anticipates this, but concretely):
  - **License/attribution is an open compliance gap in the prior work, not a solved problem** —
    `in-reach-v2`'s own `README.md` flags this explicitly: "This repo ships a compiled binary built
    from that [GPLv3] source, and `mega-ide` never added a `LICENSE` file covering the vendored
    source... before this repo goes anywhere public, add a `LICENSE`/attribution reflecting that."
    Don't inherit that gap silently — resolve it before `in-reach` ships a `.pyd` built the same way.
  - **Multi-version/multi-platform distribution was never solved** — the prior repos' own "Next
    steps" name this directly ("decide whether `mide/native/`'s prebuilt binary is the right
    long-term distribution story... versus a proper multi-platform/multi-version build pipeline").
    `in-reach`'s own `CLAUDE.md` already notes the prior prototypes were "Windows-only... native
    `.pyd` ABI-locked to a specific CPython build" as a known limitation to fix, not carry forward —
    this is the same open problem, unsolved by either prior repo.
- **The heavier "launch the real RVT GUI for visual editing" integration** (§0.1's `IDE` decision,
  "Qt. Blockly later...") is a separate, much larger effort `in-reach-v2` also built (a patched,
  topbar-trimmed RVT.exe, UI-Automation-driven screen scripting, hash-polling save detection) that is
  explicitly **out of scope** for the script-layer redesign this document describes — worth knowing
  it exists and roughly what it cost (a full RVT source patch + custom MSBuild toolchain), but not
  something to pull forward alongside the headless-compile piece above.

---

## 11. Simulator and test plan

### 11.1 Probe gametype (prerequisite) — genuinely still needed

Because tick and timer semantics are unmeasured, build one throwaway gametype first: a `network
priority high` global incremented every tick and shown in a widget; timers at several `set_rate`
values; one trigger per header kind (`on init`, `on pregame`, `on local`, plain, `on host migration`)
each writing a stamp; `apply_traits` applied on one tick and observed the next. Play it, read the
widget back (Tesseract is already wired), and record results in `catalog/engine_semantics.toml`.

Both prior repos were checked directly for any existing measurement of tick/timer semantics
(`apply_traits` lifetime, evaluation order, `set_rate` units): none exists. `catalog/
engine_semantics.toml` has no prior-repo equivalent to seed values from. This probe is not redundant
with anything already done.

### 11.2 Interpreter

An AST interpreter over a mock world: players, objects (labels, kinds, slots, shapes), teams, timers,
game variables, script options. Actions with known semantics mutate the model; engine-side queries
(`shape_contains`, `get_distance_to`, `place_at_me`) return scenario-supplied values; anything
unmodeled is reported as such, never guessed. Since `apply_traits` is per-tick, the natural output is
a trait stack per player per tick.

Prior research does confirm one useful simplification: since a compiled trigger really is
"conditions gate everything after them in the same list" (§1), an interpreter modeling
`if`/`altif`/`alt` structurally (via `nodes.IfStatement` once the parser is ported, §12) is modeling
the *text* semantics, which is what a hand-authored `.mgl` file actually means — it does not need to
also understand the flat/positional opcode shape from §1 at all. That shape only matters if the
simulator is ever built to run directly off a decompiled `.bin`'s `EngineTrigger.opcodes` rather than
off parsed `.mgl` text; for the source-level interpreter described here (driving a mock world), it's
irrelevant and can be ignored.

### 11.3 Scenarios

```yaml
name: revive_basic
profile: dev
options: { o_disable_win: 1 }
world:
  labels:
    config: [{ id: cfg }]
    spawn:  [{ id: sp_h, team: 0, spawn_sequence: 0 }]
  players:
    - { id: P1, team: 0, role: medic }
    - { id: P2, team: 0, role: marine }
ticks:
  1:  { events: [round_start] }
  30: { events: [{ health: { P2: 0 } }] }
  32: { events: [{ distance: { P1: { P2: 5 } } }] }
  40: { assert: ["trait_stack(P1) == [t_medic, t_uncharged, t_freeze]", "p_revive_meter(P1) >= 50"] }
  45: { assert: ["c_status(P2) == status_up", "fired(REVIVE_PASS)"] }
```

Runs under pytest (`in_reach.sim` collects `script/tests/*.yaml`). The IDE's test-plan view is the
scenario list with pass/fail, plus a per-tick timeline: triggers fired in order → statements → state
diff → trait stack per player.

---

## 12. Milestones (reordered guidance, not renumbered)

The original milestone list is still the right shape. What changes is how milestone 1 gets done:

1. **Parser + lossless emitter; round-trip test over every decompiled gametype available. Catalog
   generator.** — Given a validated ~1,700-line implementation of exactly this already exists
   (`in-reach-v2 (dis)/refactor/mide/megalo_ast/{lexer,nodes,parser,unparse,visit}.py`, confirmed
   against 5 real fixtures including the `a and b or c` precedence edge case), this repo's own
   `CLAUDE.md` guidance ("port deliberately, piece by piece... once real implementation starts")
   applies directly: **port this module in**, adapting it to the richer `.mgl` dialect described
   here (bitfields, kinds, fragments, `${}` constants — none of which the ported grammar covers yet,
   since it only targets what `compile_script()` itself already accepts), rather than writing a new
   recursive-descent parser from zero. The engine-bound half (`engine.py`) is lower priority for this
   milestone — it needs a loaded native `GameVariant`, and is more relevant to §11.2's interpreter and
   to any future "adopt an existing `.bin`" tooling than to the text-level parser/emitter this
   milestone is about.
   - Porting also inherits a working native binding to validate the round-trip against
     (`compile_script`/`decompile_script`, §10) instead of needing to stand one up separately.
   - Resolve the license/distribution gap named in §10 as part of bringing the native module itself
     forward, not as an afterthought once the parser milestone is "done."
2. **Semantic model, budget panel, IR001–IR012.** — Use §3's corrected caps table, not the original
   guesses.
3. **Linker.** — Unchanged; §6's `alias`-emission note applies here.
4. **Fragments and fusion, IR013–IR018.** — Decide the subroutine-vs-fusion question from §7 before
   or during this milestone, since it changes what "fuse" even means for non-adjacent fragments.
5. **Env profiles + IDE profile switcher. Shadow-repo snapshots on successful link.** — Reuse
   `in-reach-v2`'s status-level convention per §9.6.
6. **SQLite index, query panels, dependency-graph view.** — Match `generate_ast_json`/
   `generate_engine_ast_json` naming/shape per §9.
7. **Probe gametype → `engine_semantics.toml` → interpreter → scenario runner → test-plan view.** —
   Unchanged; still greenfield, nothing to port.
8. **Blockly editor per block file; node editor over the dependency graph; LSP.** — Unchanged.

---

## 13. Sample workflow: "Hill Rush"

A deliberately small gametype to show every moving part once. Standing in the hill gives you a
movement buff and one point every `SCORE_INTERVAL` seconds; first to `SCORE_TO_WIN` ends the round.
Two modules (scoring, buff) fuse into one player pass. Dev builds show a debug message and lower the
win score. None of its bitfield intrinsics happen to be used in this worked example, so the `|=`
correction in §4.3 doesn't require editing anything below §13.7 as written; if this example is ever
extended to demonstrate bitfields, use the corrected lowering.

> Example code is illustrative of the pipeline. Individual action names must be validated against the
> catalog once it exists; none of it has been compiled by RVT.

### 13.1 Create the project

```
$ in-reach new hill_rush
created hill_rush/script/project.toml
created hill_rush/script/blocks/
created hill_rush/script/modules/
created hill_rush/script/env/dev.env, release.env
created hill_rush/script/tests/
initialised shadow repo hill_rush/.in-reach/history
```

### 13.2 `script/project.toml`

```toml
[project]
name     = "hill_rush"
dialect  = "mgl/1"
profile  = "dev"
bit_impl = "and"

[blocks]
order = ["SETUP", "HILL_PASS", "WIN_CHECK"]

[[modules]]
name = "hill_score"

[[modules]]
name = "hill_buff"

[kinds.hill]
reached_by = ["label:hill"]
```

### 13.3 `script/env/dev.env` and `release.env`

```
# dev.env
FLAGS=DEV
SCORE_INTERVAL=1
SCORE_TO_WIN=5

# release.env
FLAGS=
SCORE_INTERVAL=1
SCORE_TO_WIN=50
```

### 13.4 `script/blocks/setup.mgl`

```
-- @block SETUP
-- @doc Runs once at round start: pins every hill object and shows its waypoint to everyone.
-- @label L_hill = "hill"

on init: for each object with label L_hill do
   current_object.set_invincibility(1)
   current_object.set_garbage_collection_disabled(1)
   current_object.set_waypoint_visibility(everyone)
end
```

### 13.5 `script/blocks/win_check.mgl`

```
-- @block WIN_CHECK
-- @doc Ends the round when any player reaches the score target. Dev profile raises the target via env.

for each player do
   if current_player.score >= ${SCORE_TO_WIN} then
      game.end_round()
   end
end
```

### 13.6 `script/modules/hill_score/`

`module.toml`

```toml
[module]
name    = "hill_score"
version = "1.0.0"
tags    = ["hill", "scoring"]
summary = "One point per SCORE_INTERVAL seconds while standing in a hill."

[requires]
player_timer = 1
labels       = 1
temporaries  = { number = 1 }

[provides]
aliases   = ["p_hill_timer"]
blocks    = ["HILL_PASS"]
preambles = ["in_hill"]

[order]
after = ["SETUP"]

[params]
score_interval = { type = "number", default = "${SCORE_INTERVAL}" }

[kinds]
hill = { reached_by = ["label:hill"] }
```

`hill_score.mgl`

```
-- @ptimer p_hill_timer default=${score_interval}

-- @preamble in_hill
-- @provides in_hill:number
-- @doc Sets in_hill to 1 if the current player's biped is inside any hill shape.
in_hill = 0
for each object with label L_hill do
   if current_object.shape_contains(current_player.biped) then
      in_hill = 1
   end
end
-- @guard-end

-- @fragment HILL_PASS.score
-- @loop     player
-- @preamble in_hill
-- @fusion   auto
if in_hill == 1 then
   current_player.p_hill_timer.set_rate(-100%)
   if current_player.p_hill_timer.is_zero() then
      current_player.score += 1
      current_player.p_hill_timer = ${score_interval}
   end
end
if in_hill == 0 then
   current_player.p_hill_timer.set_rate(0%)
   current_player.p_hill_timer = ${score_interval}
end
```

### 13.7 `script/modules/hill_buff/`

`module.toml`

```toml
[module]
name    = "hill_buff"
version = "1.0.0"
tags    = ["hill", "traits"]
summary = "Movement buff while standing in a hill; debug message in DEV builds."

[requires]
traits      = 1
preambles   = ["in_hill"]
temporaries = { number = 0 }

[provides]
aliases = ["t_hill_buff"]
blocks  = ["HILL_PASS"]

[order]
after = ["SETUP"]
```

`hill_buff.mgl`

```
-- @trait t_hill_buff { movement_speed = "value_120" }

-- @fragment HILL_PASS.buff
-- @loop     player
-- @preamble in_hill
-- @traits   layer=environment
-- @fusion   auto
if in_hill == 1 then
   current_player.apply_traits(t_hill_buff)
-- @if DEV
   game.show_message_to(current_player, none, "DEV: in hill")
-- @end
end
```

### 13.8 Build (dev profile)

```
$ in-reach build
parse     3 block files, 2 modules ....................... ok
order     SETUP → HILL_PASS → WIN_CHECK
kinds     hill (label:hill)
alloc     player.timer[0] ← p_hill_timer (hill_score)
resources script_traits[0] ← t_hill_buff (hill_buff)      settings.json updated
          forge_labels[0]  ← "hill" (setup)               script_settings.json updated
profile   dev  flags=DEV  SCORE_INTERVAL=1 SCORE_TO_WIN=5
fusion    HILL_PASS ← hill_score.score + hill_buff.buff
          shared preamble in_hill; temporaries 1 number (was 1+1)
          saved: 1 trigger, 3 actions, 1 condition
lint      0 errors, 0 warnings
counters  triggers=3 conditions=6 actions=15 strings=1 bits≈1.9k
wrote     build/Compiled.txt build/declarations.mgl build/link_map.json build/index.db
snapshot  .in-reach/history  a41c2f  "link: dev flags=DEV triggers=3 conditions=6 actions=15"
```

### 13.9 `build/Compiled.txt` (dev)

```
-- in-reach build: hill_rush  profile=dev  flags=DEV  2026-09-12T14:02:11Z
-- Auto-generated and non-editable. Edit script/ and rebuild.

declare player.timer[0] = 1                                 -- p_hill_timer (hill_score)

alias p_hill_timer = player.timer[0]
alias t_hill_buff  = script_traits[0]

-- SETUP (blocks/setup.mgl)
on init: for each object with label "hill" do
   current_object.set_invincibility(1)
   current_object.set_garbage_collection_disabled(1)
   current_object.set_waypoint_visibility(everyone)
end

-- HILL_PASS (fused: hill_score.score, hill_buff.buff; preamble in_hill)
for each player do
   alias in_hill = allocate temporary number
   in_hill = 0
   for each object with label "hill" do
      if current_object.shape_contains(current_player.biped) then
         in_hill = 1
      end
   end
   -- hill_score.score
   if in_hill == 1 then
      current_player.p_hill_timer.set_rate(-100%)
      if current_player.p_hill_timer.is_zero() then
         current_player.score += 1
         current_player.p_hill_timer = 1
      end
   end
   if in_hill == 0 then
      current_player.p_hill_timer.set_rate(0%)
      current_player.p_hill_timer = 1
   end
   -- hill_buff.buff
   if in_hill == 1 then
      current_player.apply_traits(t_hill_buff)
      game.show_message_to(current_player, none, "DEV: in hill")
   end
end

-- WIN_CHECK (blocks/win_check.mgl)
for each player do
   if current_player.score >= 5 then
      game.end_round()
   end
end
```

Switching the profile to `release` and rebuilding changes exactly two things: the `DEV: in hill` line
disappears (and the string count drops to 0), and `>= 5` becomes `>= 50`. The shadow repo shows that
as a two-line diff.

### 13.10 `build/link_map.json` (excerpt)

```json
{
  "profile": "dev", "flags": ["DEV"],
  "storage":   { "p_hill_timer": {"slot": "player.timer[0]", "owner": "modules/hill_score", "default": 1} },
  "resources": { "t_hill_buff": {"kind": "trait", "index": 0, "owner": "modules/hill_buff"},
                 "L_hill":      {"kind": "label", "index": 0, "owner": "blocks/setup.mgl"} },
  "budget":    { "player.timer": {"cap": 4, "used": 1}, "traits": {"cap": 16, "used": 1}, "labels": {"cap": 16, "used": 1},
                 "counters": {"triggers": 3, "conditions": 6, "actions": 15, "strings": 1} },
  "order":     ["SETUP", "HILL_PASS", "WIN_CHECK"],
  "fusion":    { "groups": [{"trigger": "HILL_PASS", "fragments": ["hill_score.score", "hill_buff.buff"],
                             "preamble": "in_hill", "temporaries": {"number": 1},
                             "saved": {"triggers": 1, "actions": 3, "conditions": 1}}],
                 "declined": [] }
}
```

### 13.11 What the linter would have said

Had `hill_buff.buff` been written with `apply_traits` *before* a fragment declaring `layer=freeze`,
IR009 fires on the fused group. Had `WIN_CHECK` written `current_player.score >=
${SCORE_TO_WIN}` with `SCORE_TO_WIN` missing from `release.env`, IR015 fires on switching profile.
Had someone added `-- @fragment HILL_PASS.headcount` that writes a global `g_in_hill_count` and a
sibling that reads it, the linker would keep them as separate triggers and list the pair under
`declined` with the reason.

### 13.12 Scenario test `script/tests/hill_basic.yaml`

```yaml
name: hill_basic
profile: dev
world:
  labels:
    hill: [{ id: hill_a, shape: sphere }]
  players:
    - { id: P1, team: 0 }
    - { id: P2, team: 1 }
ticks:
  1:   { events: [round_start] }
  2:   { events: [{ shape_contains: { hill_a: [P1] } }] }
  3:   { assert: ["trait_stack(P1) == [t_hill_buff]", "trait_stack(P2) == []"] }
  # timer semantics come from engine_semantics.toml; until measured the next line reports "unmodeled"
  62:  { assert: ["score(P1) == 1"] }
  400: { assert: ["score(P1) == 5", "round_ended"] }
```

```
$ in-reach test
hill_basic  tick 3    ok
hill_basic  tick 62   UNMODELED  timer.set_rate: engine_semantics.timer_units is null
hill_basic  tick 400  UNMODELED  (depends on tick 62)
1 scenario, 1 ok, 2 unmodeled, 0 failed
```

That "unmodeled" is the point: the simulator tells you which engine fact you still need to measure
rather than pretending.

### 13.13 Ship

1. Switch profile to `release`, build, confirm the two-line diff.
2. Open `build/Compiled.txt`, paste into RVT, compile.
3. Record RVT's counters against the snapshot (manually, or via OCR).
4. Optional: "Commit to project repo" to push the snapshot into your own git history.

---

## Appendix A: glossary

- **Block** — a hand-authored trigger or group of triggers under one block keyword (`SETUP`,
  `HUMAN_PASS`), one file each.
- **Module** — a directory with `module.toml` + `.mgl` + `README.md` that declares its
  storage/resource needs abstractly and is linked into a project.
- **Fragment** — a loop body with a loop signature; the linker fuses adjacent compatible fragments
  into one trigger.
- **Preamble** — a shared, named prologue (temporaries + statements + guard) required by fragments.
- **Kind** — a set of objects always reached the same way; kinds may share object slots.
- **Pin** — a forced concrete slot for an abstract name, declared in `project.toml`.
- **Profile** — an env file (`dev.env`, `release.env`) supplying `${}` constants and `FLAGS`.
- **Link map** — `build/link_map.json`, the record of every allocation and fusion decision.
- **Catalog** — `catalog.json`, the machine-readable RVT dialect; `engine_semantics.toml`, the
  measured runtime facts.

## Appendix B: where each confirmed fact in this document came from

For anyone re-verifying any claim above against the prior repos directly:

| Fact | File |
|---|---|
| Grammar (comments real, `alt`/`altif` real, `else`/`elseif` reserved-but-dead, operator set, precedence) | `in-reach-v2 (dis)/refactor/mide/megalo_ast/nodes.py`, `lexer.py`, `parser.py` (module docstrings + `_ASSIGN_OPS`/`_UNIMPLEMENTED_RESERVED_WORDS`) |
| Flat-opcode/positional-if engine representation, trigger entry types, subroutine mechanism | `in-reach-v2 (dis)/refactor/mide/megalo_ast/engine.py` (module docstring, `EngineTrigger`, `_build_statements`, `_compute_is_function_flags`) |
| Storage pool caps (per scope, per type) | `in-reach-v2 (dis)/refactor/ReachVariantEditor/native/src/ReachVariantTool/game_variants/components/megalo/variables_and_scopes.cpp` (the five `VariableScope(...)` definitions) |
| Engine resource/counter caps (`max_triggers`, `max_script_traits`, etc.) | `.../game_variants/components/megalo/limits.h` |
| Confirmed `on <event>:` text spellings | `in-reach-v2 (dis)/refactor/tests/resources/{blank_ff,blank_mp,infection,invasion,juggernaut}/type_code.txt` |
| Headless/in-process compile via pybind11 | `in-reach-v2 (dis)/refactor/mide/rvt_headless.py`, corroborated by `in-reach-v2 (dis)/src/inreach/app/mglo.py`'s and `CLAUDE.md`'s own description of the real `ReachVariantTool.exe --headless` flag |
| Dulwich shadow-repo VCS design | `in-reach-v2 (dis)/CLAUDE.md`, "VCS (`app/vcs.py`)" section |
| Abandoned flatter module design and its failure mode | `in-reach-v1 (dis)/CLAUDE.md`, "Architecture: where editing happens" |
| Native module license/distribution gaps | `in-reach-v2 (dis)/refactor/README.md`, "License" and "Next steps" sections |
| "ONI EVAC Implementation Guide" — not found | (absence confirmed via repo-wide search of both `in-reach-v1 (dis)` and `in-reach-v2 (dis)`) |
