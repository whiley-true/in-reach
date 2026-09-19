# Next steps

Where the scripts work stands, what's left, in what order, and what needs a decision. Everything under
"Where things stand" was measured or tested, not assumed; `CLAUDE.md` is the source of truth for what the
code does today, and `TO_IMPLEMENT_(LATEST).md` is still the design for the module layer (see
"Documents that are now wrong" below before trusting it).

## Where things stand

**Single-file scripts work end to end.** `script/output.txt` is one file, and it can stay one file.

- **Compiler coverage.** The in-house compiler (`megalo_compiler.py`) compiles **423 of 423** real
  multiplayer scripts against their own variant, and **377 of 377** with only the synthetic template pool
  (own templates thrown away) -- every built-in, hopper and personal variant on the dev machine. Measured by
  `tests/app/rvt/test_megalo_compiler_corpus.py`, opt-in via `IN_REACH_CORPUS_DIRS`.
  *"Compiles" is not "faithful" -- see item 1.*
- **Blank-start projects work.** The template pool (`template_source.py`) supplies what a blank base lacks;
  the compiler creates forge labels (via a native stub compile), widget / trait-set / stat / option entries,
  and finds timer rates by search; `settings/` is reconciled to match (`reconcile_forge_labels`,
  `reconcile_script_tables`, `reconcile_script_strings`) and written back so Apply never sticks on "unapplied".
- **Env profiles.** `script/env/<name>.env` (`FLAGS=`, `NAME=value`), `${NAME}` substitution, and
  `-- @if FLAG` / `@else` / `@end`. Line numbers never shift; text using neither feature is unchanged. New
  projects start with `dev` (active) and `release`. A "Select Build Profile" palette submenu and a status-bar
  indicator switch profiles.
- **Two correctness bugs fixed on the way:** `or` binds tighter than `and` in Megalo (the parser and the docs
  had it backwards, so mixed conditions were both bigger *and* different in meaning); native error lines are
  0-based and were shown one line too high.
- **Native bindings** (timer-rate setter, `WidgetArgument`/`PlayerTraitsArgument.set_value`, four
  `add_scripted_*`) are built into the bundled `.pyd` and committed in `mega-ide` as `5d0fe97`.
  See `native/README.md`.

**Not committed in this repo.** A lot of work is sitting in the working tree (compiler, pool, aliases,
labels/tables, env profiles, native `.pyd`, about a dozen new test files). Commit it in themed pieces rather than one blob --
suggested split: (1) alias pass + condition precedence + top-level loops, (2) template pool + table/label
creation + reconcile, (3) env profiles + palette/status bar + starters, (4) the `.pyd` on its own (it's a
tracked 2 MB binary).

---

## Priorities

### 1. Make the in-house compiler honour `declare` -- correctness, do this first

**Problem.** `declare global.number[0] with network priority high = 7` compiles to *nothing* in-house.
Verified: native keeps both the priority and the initial value; the in-house build has no `declare` lines at
all. The compiler validates `declare` and then ignores it (deliberate at the time -- see its module docstring
-- but its consequences are bigger than that note suggests):

- A script written from scratch on a blank base loses every initial value and every network priority.
- In a project from a real `.bin`, the base variant's *own* declarations survive (they live in the variant,
  not in the script text), so it looks fine -- but **editing a `declare` line in `output.txt` does nothing**.
- The corpus "100%" doesn't see this: it checks that compilation succeeds, not that the result matches.

**Why first.** The module linker (item 3) allocates storage and needs to emit priorities (e.g. IR008: a
widget-driven player number must be `high`). It can't be built on a compiler that drops them.

**Work.** Find how native stores a declaration (variable initial value + `network priority` per slot) and
what the binding exposes; add bindings if it doesn't (a native rebuild -- the toolchain is set up, see
`native/README.md`). Then implement in `_compile_declare`. Also add a **fidelity check** to the corpus test:
recompiled `declare` lines and trigger/condition/action counts must equal the original's, so "compiles"
can't hide a loss again. Size: M.

### 2. Close the round trip with RVT

- **`inline:` doesn't re-parse.** Decompiling a script the in-house compiler built emits `inline: do ... end`,
  which the parser rejects, so a second compile of that text falls back to native. Today's flow never
  decompiles a built `.bin`, so nobody hits it -- but "pull the script back out of a `.bin` RVT just edited"
  would. Teach the parser (and unparser) the `inline:` form. Size: S.
- **RVT edits don't reach the script.** RVT saves are mirrored into `settings/` only, and every Apply rebuilds
  from the frozen `init_gametype/<id>.bin`. Decide what "edit in RVT, keep working here" should mean before
  building anything (see Decisions). Size: M, mostly design.
- **Native fallback still has the inlining problem** (`bInlineIfs`, non-idempotent trigger counts). It's now
  rare -- everything in the corpus stays in-house -- but a script outside the compiler's subset still hits it.

### 3. The module layer (the original goal)

Follow `TO_IMPLEMENT` milestones 1-3, after the corrections below. The pieces, roughly in order:

1. **`-- @` annotation parsing** (`@number`, `@onumber`, `@trait`, `@fragment`, ...) as a second small parser
   over comments. Size: M.
2. **Semantic model + linter** (IR001-IR012). Caps are known and verified (`_POOL_SIZES`, `_SCRIPT_TABLES`,
   condition/action/trigger caps). Size: M-L.
3. **Linker**: storage allocation, kinds, resource allocation, module ordering, `link_map.json`. Note the
   compiler now resolves `alias` itself, so the linker *can* emit `alias` lines (the doc's plan, and no longer
   the trap I'd feared) -- but still measure whether that's better than substituting in the AST. Needs item 1.
   Size: L.
4. **Budget panel** over `link_map.json`; **fusion** (with the subroutine alternative in `TO_IMPLEMENT` §7).
5. **Python as a one-way generator** front-end that emits `.mgl`/AST into `build/` (decided earlier: a
   generator, not a synced peer). Only after modules show what `.mgl` can't express -- an
   `inline function`/macro facility in `.mgl` may cover most of it.

Per-module choice of syntax (`.mgl` or `.py`) needs no sync machinery because modules meet only at the linker,
via their manifests. **Rule to keep:** one editable source per module; every other view is regenerated.

### 4. Script editing in the IDE

Right now a script is edited as plain text and errors come back in Apply's failure dialog. Still to do:

- **Megalo syntax highlighting** in the editor (only JSON has a highlighter today). The lexer/parser already
  exist and produce spans. Include `-- @if` directives and `${...}` placeholders. Size: M.
- **A Problems panel** with clickable error lines (positions are now 1-based and correct). Size: M.
- **Scripts panel** (`scripts_panel.py`) is still a stub -- the natural home for the profile picker, the
  module list, and later the budget view.
- **Autocomplete / hover** from `catalog.json` and `reference/megalo/`; **LLM panel** is a stub too. The
  audience decision (players who use the LLM panel) makes the linter + a machine-readable catalog the thing
  that makes an LLM useful here. Size: L.
- Small: make *Stamp Release* switch to the `release` profile (and say so). `TO_IMPLEMENT` §4.5 also wants
  the active profile and flags stamped into the `Compiled.txt` header and the commit message -- neither does
  that yet.

### 5. Known compiler gaps (all fall back to native, none is wrong)

- A stat on an owner other than `current_player` (`global.player[3].script_stat[1]`, a team's stat) needs an
  example in the base script. A native binding to select the team-stat scope, or to derive `which` for other
  owners, would close it.
- `|` outside a flags slot; a nested call used as a sub-expression; a property read inside an expression
  (needs a temporary the compiler doesn't allocate).
- Settings-defined **forge labels** can't be created from `settings/` (only from a script naming one) because
  there is no `add_forge_label` binding -- a one-liner in the same style as the four `add_scripted_*`, if
  symmetry with the other tables is wanted.

### 6. Repo and distribution

- **The `.pyd` has no source in this repo.** It's built from `mega-ide`'s tree and committed as a binary.
  Either vendor the C++ (mind the GPLv3 attribution gap `TO_IMPLEMENT` §10 already flags), reference it as a
  submodule, or build it in CI. Until then every native change means: edit `mega-ide`, rebuild, copy the
  `.pyd`, commit a 2 MB blob.
- **Multi-platform / multi-Python**: the binary is CPython 3.14, 64-bit Windows only. Unsolved by any prior
  prototype.
- **CI can't run the corpus** (MCC files aren't redistributable). The 100% figures are a local measurement;
  consider committing a *derived* fidelity report (counts only, no game content).
- The full suite takes ~6.5 minutes; worth splitting fast/slow markers before it grows further.

---

## Decisions needed from you

1. **Module manifest format** -- `module.toml` as in `TO_IMPLEMENT` §5, or something lighter? Should a
   module's storage needs be *declared* (`[requires]`, checked by the linter) or *inferred* from its code?
2. **Do modules write into `settings/`** (self-contained), or only require that an index exists
   (hand-owned settings)? Open since the original design; the table/label work makes the self-contained
   option cheap now.
3. **Fusion vs. subroutine** as the default lowering for shared preambles -- automatic, or only as an
   explicit `@fusion` opt-in?
4. **RVT round trip**: when someone edits the built `.bin` in RVT, should Apply (a) warn and refuse, (b) merge
   the RVT changes into `settings/` and leave the script alone (today's partial behaviour), or (c) pull the
   script back out too (needs item 2's `inline:` fix)?
5. **Native source**: vendor it, submodule it, or build in CI (item 6)?
6. **Default profile for new projects** is `dev`. Good default, or should a project start with none chosen?

---

## Documents that are now wrong

- **`TO_IMPLEMENT_(LATEST).md`**
  - §4 grammar: the precedence line is fixed, and IR002 ("no parenthesised compound `or`") is now confirmed --
    native rejects *any* parenthesised condition. Re-check anything else derived from the old precedence
    (the `bit_test` lowering, the simulator's condition model).
  - §6 step 8 / §0.1: `alias` emission is fine now that the compiler resolves aliases; the caveat I gave
    earlier no longer applies.
  - §3 "unverified" caps and §11's probe gametype are still open and still needed.
  - The "ONI EVAC Implementation Guide" cited by every lint rule doesn't exist in either prior repo.
- **`native/README.md`** describes the bindings as of `5d0fe97`; update it with each native change.
- **`.claude/rules`**: worth adding a note that a Windows `Path.write_text` converts line endings (the repo is
  `autocrlf=true`, so this is harmless, but it surprised us).

---

## Useful commands

- Full suite: `python -m pytest tests -q` (~6.5 min).
- Real-corpus coverage (needs MCC installed):
  `IN_REACH_CORPUS_DIRS="<...>\haloreach\game_variants;<...>\hopper_game_variants;<personal GameType dir>"
  python -m pytest tests/app/rvt/test_megalo_compiler_corpus.py -q -s`
- Rebuild the native extension: see `native/README.md` (an incremental build after touching only
  `bindings.cpp` is a couple of minutes).
