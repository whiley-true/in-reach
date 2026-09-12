# in-reach script layer — TO_IMPLEMENT

Status: `DESIGN_NOTES.md`, re-checked against the two prior prototypes on disk
(`D:\whileyRepos\in-reach-v1 (dis)`, `D:\whileyRepos\in-reach-v2 (dis)`) that this repo's own
`CLAUDE.md` names as read-only reference material. `DESIGN_NOTES.md` was written without access to
either repo; this document keeps its structure and its decisions, but corrects every place where
those decisions collided with something the prior repos actually confirmed (grammar, engine limits,
a working headless compiler, a shipped VCS design), and calls out the couple of places where prior
research quietly disagrees with `DESIGN_NOTES.md`'s own assumptions.

Scope: same as `DESIGN_NOTES.md` — the script-management half of in-reach. Map tools are out of
scope here.

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
   `fatal_errors`/`errors`/`warnings`/`notices`, each a `(line, col, text)` message. This closes
   `DESIGN_NOTES.md`'s open item #4 outright: RVT automation is not a nightly corpus job, it's the
   interactive fast loop *and* the oracle, from milestone 1 onward. See §10.
2. **The engine's real storage-pool caps are smaller and richer than what `DESIGN_NOTES.md` guessed
   at**, and were pulled straight from `Megalo::Limits` and `variables_and_scopes.cpp` in the vendored
   RVE source under `in-reach-v2 (dis)/refactor/ReachVariantEditor/`. `global.number = 12` was right;
   everything else in that table needed either a correction or a number it didn't have at all
   (per-pool timer/team/player/object caps, `max_triggers`, `max_conditions`, `max_actions`). See §3.
3. **Comments are already real, compileable Megalo syntax** (`-- text` to end of line), confirmed
   directly via `compile_script()` in `in-reach-v2`. `DESIGN_NOTES.md`'s open item #3 (whether `-- @`
   annotations need a second mini-parser bolted onto a plain lexer, or should be promoted to real
   keywords) is resolved in favor of the simpler option: comments were never going to break the
   compiler either way, so annotation-as-comment is safe to commit to now, not a placeholder pending
   `mgl/2`. See §4.7.
4. **The confirmed grammar has no `|=` operator.** `_ASSIGN_OPS` is exactly
   `{"=", "+=", "-=", "*=", "/=", "%="}`; bitwise OR (`|`) exists only as a binary *expression*
   operator. `DESIGN_NOTES.md` §4.3's `bit_set` lowering (`cx.c_flags |= flag_kit_given`) is not valid
   Megalo — it needs to lower to `cx.c_flags = cx.c_flags | flag_kit_given` instead. See §4.3.
5. **`alt`/`altif` are the confirmed working "else"/"else if"; literal `else`/`elseif` are reserved
   but do nothing** (the compiler rejects them by name, with no handler ever wired up server-side).
   `DESIGN_NOTES.md` already assumed this correctly (it's called out directly in this repo's own
   `CLAUDE.md`) — this is confirmation, not a correction, but it's confirmed hard enough (a compiler
   error message quoted verbatim, a `Compiler::is_keyword()` comment saying `// reserved`) that it's
   worth treating as settled, not "prior research."
6. **A working pybind11 binding of the whole engine already exists** — `_reachvarianttool`, prebuilt
   for `cp314-win_amd64`, plus two from-scratch AST layers over it
   (`in-reach-v2 (dis)/refactor/mide/megalo_ast/`: a ~1,700-line text-grammar layer already validated
   against 5 real fixtures, and a read-only binding onto the engine's own compiled Trigger/Opcode
   graph). Milestone 1 in `DESIGN_NOTES.md` §12 ("Parser + lossless emitter...") is a *port*, not a
   from-scratch write — see §12.
7. **Megalo triggers are flat opcode lists at the engine level; nesting is purely positional** (a run
   of Condition opcodes opens an if-level, and *everything remaining in the same flat list* becomes
   its body, recursively — not just up to the next condition run). This is the compiler's own
   business, not something the text-level linker in `DESIGN_NOTES.md` needs to reproduce — RVT already
   lowers structured `if ... then ... end` text into that shape — but it's the reason the engine
   exposes exactly one real looping construct (`for_each_*`, itself a "Run Nested Trigger" to a
   specially-typed trigger) and a genuine subroutine mechanism. That subroutine mechanism is a second,
   already-existing alternative to `DESIGN_NOTES.md` §7's fragment-fusion scheme for the "shared
   preamble" problem — worth an explicit decision, not an oversight. See §7.
8. **A prior prototype already tried a flatter version of "modules" and hit exactly the problem this
   design's linker exists to solve.** `in-reach-v1`'s own `CLAUDE.md` describes (not yet built)
   `cfg/script/manifest.json` + `declarations.msc` + `modules/*.msc`, compiled by concatenating module
   text into one blob before calling `compile_script()` — no abstract storage, no kinds, no linker.
   Its own writeup names the failure mode: "no modular imports, comment blocks doing a filename's job,
   colliding aliases." That's independent validation that the abstract-storage/kind/link step in
   `DESIGN_NOTES.md` §4/§6 is solving a real, previously-hit problem, not a hypothetical one.
9. **A Dulwich shadow-repo VCS almost identical to `DESIGN_NOTES.md` §9.6 was already designed and
   partially shipped** in `in-reach-v2` (`app/vcs.py`): a bare repo at `.inreach/vcs.git`, no working
   tree of its own (the real one is `edit/` on disk), tree built by *recursively walking whatever's
   currently on disk* rather than a fixed file list (deliberately, to make room for modules later), a
   status file (`vcs_status.json`) keyed by commit sha with levels `0 edited / 1 compiles / 2+
   released`, single branch only. It also sketches the most likely shape for cross-project module
   versioning: each module gets its own Dulwich repo, referenced via a git submodule–style gitlink
   tree entry (mode `0o160000`). `DESIGN_NOTES.md`'s "no registry, no versioning beyond a
   `module.toml` field" decision is fine as a v1 cut, but the richer design already exists on paper if
   modules outgrow that. See §5.2/§9.6.
10. **The "ONI EVAC Implementation Guide" that `DESIGN_NOTES.md` §8 cites for every linter rule
    (IR001–IR018) does not exist anywhere in either prior repo.** It's presumably a separate document
    the user has; nothing here should be read as confirming or disputing those specific rules'
    section numbers. Flagged so nobody goes looking for it in `in-reach-v1`/`in-reach-v2` and comes up
    empty confused. See §8.

---

## 0.1 Decisions taken and open items (updated)

**Decided** (unchanged from `DESIGN_NOTES.md` unless noted)

| Topic | Decision |
|---|---|
| Canonical source | Text, as a directory of small `.mgl` files. Blocks, node graph, SQLite index and `Compiled.txt` are all derived and disposable. |
| Git | Dulwich drives a *shadow* repo under `.in-reach/history/` (own git dir, worktree = project). It never writes into the user's own repo unless they ask. **A near-identical design already exists in `in-reach-v2`'s `app/vcs.py`** — same bare-repo-plus-recursive-walk shape, at `.inreach/vcs.git`. Reuse its status-level convention (`0 edited / 1 compiles / 2+ released`) rather than inventing a new one. |
| Priority order | Modules + linker → budget panel + linter → env profiles → simulator/test plan. Blocks/nodes UI last. |
| Compile backend | RVT, via the confirmed-working in-process pybind11 binding (§10), not RVT.exe. The planned in-house checker still wraps it; until it's written, the in-house linter is the fast loop and the real compiler is the oracle — but "the oracle" is now a Python function call, not a GUI paste step. |
| Grammar | Cobb's RVT syntax; **confirmed directly** against `in-reach-v2`'s `megalo_ast` grammar and against decompiled fixtures — see §3/§4. |
| Modules | Per project (no registry, no versioning beyond a field in `module.toml`), matching `DESIGN_NOTES.md`. A richer, already-sketched alternative (gitlink-referenced module repos) exists if this needs to grow later — see item 9 above. |
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
5. **New**: module authoring format. `DESIGN_NOTES.md` assumes `.mgl` text modules throughout. A
   prior design note (`in-reach-v2`'s own `CLAUDE.md`, "Modules (unscoped, future)") records that its
   own authors' longer-term direction had already drifted toward *Python-authored* modules that
   compile down to Megalo, precisely because plain-text modules don't compose well at scale. Nothing
   in either prior repo actually implements Python-authored modules, so this isn't a "prior research
   says do X instead" correction — but it is a recorded, deliberate second opinion from the same
   lineage of design work, worth an explicit yes/no rather than inheriting `.mgl`-only by default.
6. **New**: preamble/fragment sharing vs. subroutines. `DESIGN_NOTES.md` §7's fusion mechanism inlines
   fragments to share one preamble per fused trigger. The engine already has a *different*,
   already-working mechanism for "run this shared logic from multiple places": a subroutine trigger
   (`entry_type == subroutine` or any trigger called from more than one place) reached via "Run Nested
   Trigger," left un-inlined as a real call rather than spliced in. That costs one trigger slot (of
   320) plus a "Run Nested Trigger" action per call site, in exchange for zero duplicated code and no
   fusion-legality analysis. Worth deciding, per preamble, which mechanism is cheaper — see §7.

---

## 1. The problem and the spine

Unchanged from `DESIGN_NOTES.md`. One engine-level fact worth carrying in your head while designing
the linker/fusion passes, confirmed by reading `in-reach-v2`'s `megalo_ast/engine.py` (itself a
line-by-line port of the real decompiler's `CodeBlock::decompile()`/`Trigger::decompile()`):

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
call to a specially-typed trigger. None of this changes what the text-level linker in
`DESIGN_NOTES.md` needs to emit — it only ever emits structured `if/end` text, same as today — but it
explains *why* the engine has exactly one real loop construct and a real subroutine call mechanism,
both of which matter for §7.

```
 .mgl source files ──parse──▶ AST (lossless) ──analyse──▶ semantic model ──link──▶ Compiled.txt (RVT)
                                  │                            │
                                  ├── block editor              ├── budget panel, linter
                                  ├── node graph                ├── SQLite index
                                  └── LLM-facing docs           └── simulator
```

The **language catalog** (`catalog.json`, §3) sits under all of it: every action, condition,
property, enum literal, parameter type and cap, in one machine-readable file. `DESIGN_NOTES.md` says
this should be "generated from RVT's source and pinned to an RVT commit" — now that a working native
binding exists (§10), generation can call the compiler directly for validation (compile a fixture,
compare against the catalog's claims) rather than only static-parsing opcode tables.

---

## 2. Project layout

Unchanged from `DESIGN_NOTES.md`'s §2 — reproduced here for reference, not because prior research
changed it:

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
itself). `DESIGN_NOTES.md`'s `.in-reach/history/` should be the same shape (bare, no checkout) for
the same reason: there's no need for a second copy of `script/` on disk just to have something for
git to diff.

Rules (unchanged): `build/` is never edited by hand and never imported back into `script/`. Object
kinds, block order and slot pins live in `project.toml`, not in code. The system `_env` (install
paths, Steam IDs, logging) is unrelated to `script/env/*.env` and is never read by the linker.

---

## 3. Language catalog

`catalog.json` is the one place engine facts live, generated by
`in_reach.catalog.generate --rvt <commit>`. Two things change here given prior research:

- **Generation can validate itself against the real compiler**, not just parse opcode tables — feed
  a fixture through `compile_script()`/`decompile_script()` (§10) and check the catalog's claims
  about a given action/condition/property against what actually compiles.
- **The caps table below replaces `DESIGN_NOTES.md`'s version wholesale.** Every number here was read
  directly out of the vendored RVE C++ source under
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

`DESIGN_NOTES.md` had `global.number = 12` right and the temporaries row right (10 number / 8 object
/ 3 player / 6 team — confirmed exactly), but had nothing for `global`'s own timer/team/player/object
caps, or for the `player`/`object`/`team` scope pools at all. Note **temporaries have no timer pool at
all** (`max_timers = 0`) — a fragment/preamble can never allocate a scratch timer, only a real
`player.timer`/`object.timer`/etc. slot; worth its own linter check if `DESIGN_NOTES.md`'s temporaries
budgeting (§4.6/IR004) doesn't already assume this.

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

Traits/widgets/options/labels match `DESIGN_NOTES.md`'s numbers exactly (16/4/16/16) — good sign the
original "observed" numbers were sound. **Two of `DESIGN_NOTES.md`'s claims did not turn up anywhere
in the confirmed source and should be treated as unverified, not wrong-but-close:**
"scripted objects (256)" (256 is `max_string_ids`, not anything called "scripted objects" in the
source — possibly a mix-up, or a genuinely different limit not covered by this pass) and
"palettes (6)" (the one requisition-palette constant found, `cobb::bitmax(4)` in
`opcode_arg_types/all_indices.h`, works out to 15, not 6 — could be a different, per-map palette
count this pass didn't locate). Don't ship either number in `catalog.json` without re-deriving it.

`max_triggers`/`max_conditions`/`max_actions` are exactly the RVT counters IR012 needs — use these,
not placeholders, once that rule is implemented.

### Trigger headers (corrected)

`DESIGN_NOTES.md` listed: `on init`, `on pregame`, `on local`, `on host migration`, plain. The engine
binding (`EngineTrigger.entry_type`, a `TriggerEntryType` enum member name) confirms **two more
distinct entry types that list omitted**: `on_local_init` and `on_object_death`, plus `subroutine`
(a trigger that only ever runs when called via "Run Nested Trigger" — see §7). Confirmed literal
source spellings, read directly off decompiled fixtures in `in-reach-v2 (dis)/refactor/tests/resources/`:

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

`catalog/engine_semantics.toml` is unchanged from `DESIGN_NOTES.md` — still a sibling file for
*measured* runtime facts, still starts `null`, still needs the probe gametype (§11.1, still not done
by anyone).

---

## 4. The `.mgl` dialect

A strict superset of the RVT dialect, unchanged in intent. Every claim below was checked against
`in-reach-v2 (dis)/refactor/mide/megalo_ast/{nodes,lexer,parser}.py`'s own docstrings, each of which
documents having been confirmed directly via `compile_script()`, not inferred from decompiled
examples alone.

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
  appear in either source order; canonicalize on emit (label first) same as `DESIGN_NOTES.md` already
  assumed.
- Expression grammar, confirmed operator precedence (lowest to highest):
  `or` < `and` < `not` < compare (`==`,`!=`,`<`,`>`,`<=`,`>=`, **non-chaining** — `a < b < c` is not a
  thing, only one comparison per expression) < `|` (bitwise/flag OR, left-associative) < postfix
  (`.`, `[]`, `()`).
- Compound assignment operators: **exactly** `=`, `+=`, `-=`, `*=`, `/=`, `%=`. **No `|=`, no `&=`, no
  plain binary `+`/`-`/`*`/`/` expression operators at all** — arithmetic only ever happens as a
  compound assignment statement, never inline in an expression.
- Reserved-but-nonfunctional words (parsed, rejected, no production exists or ever will in this
  compiler build): `else`, `elseif`, `enum`, `function`, `inline`.

### 4.1 Abstract storage — unchanged from `DESIGN_NOTES.md`, cross-check against §3's corrected caps table above rather than the old numbers.

### 4.2 Object kinds — unchanged.

### 4.3 Bitfields — **correction required**

`DESIGN_NOTES.md`'s lowering:

```
bit_set(cx.c_flags, kit_given)           -> cx.c_flags |= flag_kit_given
```

`|=` is not a real compound-assignment operator (confirmed set above). The intrinsic must lower to a
plain assignment using the binary `|` operator instead:

```
bit_set(cx.c_flags, kit_given)           -> cx.c_flags = cx.c_flags | flag_kit_given
bit_clear(cx.c_flags, kit_given)         -> scratch = cx.c_flags; scratch = scratch | flag; ... (as before; already used = / -=, not |=)
if bit_test(cx.c_flags, kit_given) then  -> scratch = cx.c_flags; scratch = scratch | flag; if scratch != 0 then
```

The rest of §4.3's design (one `@onumber` per bitfield, powers-of-two aliasing, bit 15 reserved,
`bit_impl = "and" | "divmod"` project setting) is unaffected — only the literal operator emitted by
`bit_set`'s expansion needs to change. Re-check any other place in the codebase/docs that assumed a
`|=` or `&=` compound existed.

### 4.4 Engine resources — unchanged, cross-check caps against §3.

### 4.5 Constants and profiles — unchanged.

### 4.6 Fragments (fusion) — see §7 for the subroutine-alternative note; the `.mgl` syntax itself
(`-- @fragment`, `-- @loop`, `-- @gate`, `-- @preamble`, `-- @guard`, `-- @traits`, `-- @fusion`) is
unaffected by anything prior research found.

### 4.7 Docs — unchanged, and now safe to commit to without the `mgl/2` hedge (comments are
confirmed real syntax — see §0.1 item 3).

---

## 5. Manifests

### 5.1 `module.toml` — unchanged from `DESIGN_NOTES.md`.

One data point worth keeping in mind while designing `[requires]`/`[provides]`: `in-reach-v1`'s own
(unbuilt) module design, `cfg/script/manifest.json` + `modules/*.msc`, never got as far as a
`[requires]`-style declared-cost manifest at all — it just concatenated module text and let colliding
aliases surface at compile time. That's the exact failure mode `[requires]`/`[provides]` plus the
linker's allocation pass (§6) are designed to prevent. Treat this as validation, not a reason to
simplify — the flatter approach was tried (on paper) and abandoned for scale reasons.

### 5.2 `project.toml` — unchanged.

### 5.3 Env profiles — unchanged.

---

## 6. Linker

Unchanged from `DESIGN_NOTES.md`. One addition: since `alias` is confirmed real RVT syntax (§4), step
8 ("Lower bitfield intrinsics and abstract names; emit declarations + concatenated body") can emit
`alias <abstract-name> = <concrete-slot>` lines directly into `Compiled.txt` rather than needing to
rewrite every use-site of an abstract name into its concrete slot. That's a real compiler feature
doing the substitution at compile time, not the linker faking it by find-and-replace across the
concatenated body — cheaper to implement and less error-prone than the alternative.

---

## 7. Fusion (optimization) — plus the subroutine alternative

`DESIGN_NOTES.md`'s fusion mechanism (merge adjacent same-loop, same-gate fragments into one trigger,
sharing one preamble) is unaffected by anything prior research found — it's a text-level
transformation the linker performs before ever handing `Compiled.txt` to the real compiler, and the
engine's flat-opcode/positional-if representation (§1) is exactly why sequential top-level fragments
that both start `for each player do` really do cost two separate trigger slots today, and really can
be merged into one `for each player do` with two `if`-guarded bodies inside — nothing about the
engine's internal shape blocks that.

What prior research *adds* is a second, already-existing engine mechanism for the same underlying
problem fusion solves (repeated preamble/shared logic cost) — a genuine subroutine call:

> A trigger reached by "Run Nested Trigger" from more than one call site (or a `subroutine`-entry
> trigger nothing calls directly) is **not inlined** by the decompiler — it's left as a real call
> (`EngineTriggerCallStatement`, decompiled as `trigger_N()`). This is a first-class, already-working
> "define once, call from several places" mechanism, no fusion-legality analysis required.

Trade-off, for a shared preamble specifically:

| | Fusion (`DESIGN_NOTES.md` §7) | Subroutine call |
|---|---|---|
| Trigger count | Saves one trigger per fused group | Costs one trigger (the subroutine itself) |
| Per-call cost | Zero (inlined) | One "Run Nested Trigger" action per call site |
| Legality analysis | Required (IR018: no fragment may write cross-iteration state a fused sibling reads) | Not required — a subroutine call has normal, ordinary sequencing; nothing about it is unsound the way merging two loop bodies can be |
| Best fit | Fragments that are genuinely adjacent in resolved block order and share a loop/gate | Logic reused from *non-adjacent* places, or reused across different loop kinds, where fusion's adjacency requirement can't apply at all |

This isn't a call to replace §7 — adjacency-based fusion is still the right default for the common
case (`DESIGN_NOTES.md`'s own worked example, `HILL_PASS`, is exactly the adjacent-same-loop case
fusion is built for). It's a call to make the linker's fragment/preamble model aware that a second
lowering strategy exists and is sometimes strictly better (non-adjacent reuse, or reuse across
different `@loop` kinds where fusion's own adjacency rule can never fire) rather than leaving those
cases to `declined` with no alternative offered. Whether the linker should ever choose subroutine-call
lowering *automatically*, or only ever as an explicit `@fusion` override a module author opts into, is
a fair open question — nothing in prior research answers it, since neither prototype ever built a
linker to make the choice with.

---

## 8. Linter

`DESIGN_NOTES.md`'s IR001–IR018 table cites "ONI EVAC Implementation Guide" section numbers for every
rule. **That document was not found anywhere in `in-reach-v1` or `in-reach-v2`** — it's presumably
something the user has outside of either repo. Nothing here confirms or disputes those specific
rules; they're simply out of scope for what this pass could check. Two rules *are* directly informed
by confirmed grammar facts from this pass, though, and are worth tightening:

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

Unchanged from `DESIGN_NOTES.md`, with one naming note: `in-reach-v2`'s `mide/commands.py` already
ships `generate_ast_json`/`generate_engine_ast_json` functions producing exactly the two JSON shapes
§9.4's node graph and §9.5's tooling would want (a `Script`/AST dump, and an `EngineAst` dump of the
compiled trigger graph). Match those names/shapes when building the equivalent commands here rather
than inventing new ones — there's no reason for `in_reach`'s own catalog/index tooling to diverge from
already-settled naming for the same two artifacts.

### 9.6 Shadow git — see §0.1 item 9 and §2's naming note above. The concrete status-level convention
(`0 edited / 1 compiles / 2+ released`, keyed by commit sha in a sidecar JSON file, not inside the
Dulwich repo itself) is worth adopting verbatim rather than re-deriving — it was already designed,
built, and exercised in `in-reach-v2`'s `app/vcs.py`. One caveat carried over honestly from that
design: its own author later noted the `1 compiles` label became a misnomer once `apply`/`commit`
were split apart (a commit no longer implies its content actually compiles) — if `in-reach` keeps a
similar split between "link" and "commit," name the status level for what it actually guarantees, not
what an earlier design iteration meant it to guarantee.

---

## 10. RVT integration — substantially different from `DESIGN_NOTES.md`

This is the section prior research changes the most. `DESIGN_NOTES.md` assumed:

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

What this means for `DESIGN_NOTES.md`'s plan:

- **§0's open item 4 is resolved**: yes, headless compile exists, and a Python-native equivalent
  (bypassing even the need to build/ship a headless-capable `ReachVariantTool.exe`) already exists too.
  RVT is available as the fast loop's own oracle from day one, not a nightly corpus job bolted on
  later.
- **§10's "Adopt wizard" and "Paste workflow" collapse into one thing**: loading an existing `.bin`,
  decompiling its script (`variant.multiplayer.decompile_script()` — the read-direction counterpart,
  also already bound and exercised), and letting a user name slots/declare kinds against that text is
  exactly what `in-reach-v2`'s `edit_io.write_edit_from_variant()` already does today for its own
  (non-modular) `edit/rvt/script.txt`. Porting that flow is the fast path to §10's "Adopt" wizard, not
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
- **The heavier "launch the real RVT GUI for visual editing" integration** (§0's `IDE` decision, "Qt.
  Blockly later...") is a separate, much larger effort `in-reach-v2` also built (a patched,
  topbar-trimmed RVT.exe, UI-Automation-driven screen scripting, hash-polling save detection) that is
  explicitly **out of scope** for the script-layer redesign `DESIGN_NOTES.md` describes — worth
  knowing it exists and roughly what it cost (a full RVT source patch + custom MSBuild toolchain), but
  not something to pull forward alongside the headless-compile piece above.

---

## 11. Simulator and test plan

### 11.1 Probe gametype (prerequisite) — **unchanged, genuinely still needed.**

Checked both prior repos directly for any existing measurement of tick/timer semantics
(`apply_traits` lifetime, evaluation order, `set_rate` units): none exists. `catalog/
engine_semantics.toml` has no prior-repo equivalent to seed values from. Build the probe gametype as
`DESIGN_NOTES.md` describes — this is not redundant with anything already done.

### 11.2 Interpreter — unchanged. Prior research does confirm one useful simplification: since a
compiled trigger really is "conditions gate everything after them in the same list," an interpreter
modeling `if`/`altif`/`alt` structurally (as `DESIGN_NOTES.md`'s own parser already will, via
`nodes.IfStatement`) is modeling the *text* semantics, which is what a hand-authored `.mgl` file
actually means — it does not need to also understand the flat/positional opcode shape from §1 at all.
That shape only matters if the simulator is ever built to run directly off a decompiled `.bin`'s
`EngineTrigger.opcodes` rather than off parsed `.mgl` text; for the interpreter `DESIGN_NOTES.md`
describes (source-level, driving a mock world), it's irrelevant and can be ignored.

### 11.3 Scenarios — unchanged.

---

## 12. Milestones (reordered guidance, not renumbered)

`DESIGN_NOTES.md`'s milestone list is still the right shape. What changes is how milestone 1 gets
done:

1. **Parser + lossless emitter; round-trip test over every decompiled gametype available. Catalog
   generator.** — Given a validated ~1,700-line implementation of exactly this already exists
   (`in-reach-v2 (dis)/refactor/mide/megalo_ast/{lexer,nodes,parser,unparse,visit}.py`, confirmed
   against 5 real fixtures including the `a and b or c` precedence edge case), this repo's own
   `CLAUDE.md` guidance ("port deliberately, piece by piece... once real implementation starts")
   applies directly: **port this module in**, adapting it to `DESIGN_NOTES.md`'s richer `.mgl`
   dialect (bitfields, kinds, fragments, `${}` constants — none of which the ported grammar covers
   yet, since it only targets what `compile_script()` itself already accepts), rather than writing a
   new recursive-descent parser from zero. The engine-bound half (`engine.py`) is lower priority for
   this milestone — it needs a loaded native `GameVariant`, and is more relevant to §11.2's interpreter
   and to any future "adopt an existing `.bin`" tooling than to the text-level parser/emitter this
   milestone is about.
   - Porting also inherits a working native binding to validate the round-trip against
     (`compile_script`/`decompile_script`, §10) instead of needing to stand one up separately.
   - Resolve the license/distribution gap named in §10 as part of bringing the native module itself
     forward, not as an afterthought once the parser milestone is "done."
2. **Semantic model, budget panel, IR001–IR012.** — Use §3's corrected caps table, not
   `DESIGN_NOTES.md`'s original numbers.
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

Unchanged from `DESIGN_NOTES.md` **except**: none of its bitfield intrinsics happen to be used in this
worked example, so the `|=` correction in §4.3 doesn't require editing anything below §13.7 as
written. If this example is ever extended to demonstrate bitfields, use the corrected lowering.

---

## Appendix A: glossary

Unchanged from `DESIGN_NOTES.md`.

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
