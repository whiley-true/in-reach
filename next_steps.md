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
  *"Compiles" is not "faithful" -- the corpus test now also checks declarations, tables, every statement,
  and the `inline:` round trip, all 373 of 373.*
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

### 1. ~~Make the in-house compiler honour `declare`~~ -- done

`declare global.number[0] with network priority high = 7` now compiles to exactly what native produces
(`variable_declarations.py`; new native bindings, see `native/README.md`). Two findings beyond the original
description:

- **Variables a script merely *uses* weren't declared either.** Native implies a declaration for every
  variable used (a list grows to `index + 1`, priority `low`, initial zero); in-house declared none, so a
  script written on a blank base produced a variant with an empty declaration table. Fixed the same way.
- **Native replaces the declaration table; in-house kept the base's.** That's why editing a `declare` line
  in a real-`.bin` project did nothing, and why deleting one didn't either. In-house now replaces it too:
  the script text is the whole truth.

Checked against the real corpus (`test_megalo_compiler_corpus.py`, opt-in): 373 of 373 distinct shipped
scripts recompile to identical `declare` lines and identical forge-label/string/option/stat/trait/widget
counts, and the 23 of them that compile in-house against a *blank* base (where nothing can be inherited)
get identical declarations. Coverage is unchanged (419/419; pool-only 373/373). An owner the resolver can't
classify, a repeated `declare`, or an unsupported initial value falls back to native.

**Not what the original item asked for:** trigger/condition/action counts are *not* asserted equal to the
original's. They can't be -- the compiler inlines, so it builds 15,154 triggers where the shipped variants
have 29,624, and 42 of 373 scripts need a few more actions. The corpus test checks what has exactly one
right answer (declarations and the script tables) instead.

### 2. Close the round trip with RVT

- ~~**`inline:` doesn't re-parse.**~~ Done. The parser/unparser handle `inline: do` and `inline: if` (a flag on
  the node; the compiler ignores it, since it only records layout). Checked at scale
  (`test_megalo_compiler_corpus.py`): all 373 shipped scripts, built in-house, decompile to text that parses,
  recompiles in-house, and decompiles to *identical* text. Doing this turned up two real miscompiles:
  - **A condition gated everything after its `if`.** The compiler put a non-tail `if`'s condition in the
    enclosing block and only the body in the inline wrapper, but a condition gates every opcode after it in
    its block -- so `if A then X end` then `Z` built a script where `Z` only ran when `A` held, and an
    `altif`/`alt` chain's later branches could never run. The condition now goes inside the wrapper
    (`inline: if A then ... end`, as native builds it). Same opcode count. `test_megalo_if_gating.py`.
    *No shipped script or user script compiled in-house before this can be trusted on that point.*
  - **`set_shape` swapped a cylinder's/box's two heights** (top and bottom) in 112 of the 373 shipped scripts;
    the tests only ever used equal heights. `test_megalo_compiler_corpus.py` now asserts every statement of
    every script recompiles unchanged, which is the check "it compiles" never was.

  Also fixed on the way: a run of `declare` lines cost an empty trigger ahead of the first top-level loop.
- ~~**RVT edits don't reach the script.**~~ Done (decision 4 (c)): when RVT saves, the resync now also notices
  that the *script* changed and pulls RVT's version into `script/output.txt` (`script_sync.py`, hooked into
  `MainWindow._on_watched_bin_changed`). "Changed" means the built `.bin`'s script differs from what it was at
  the last build/sync, recorded in `build/script.autogenerated.json` together with a digest of the `output.txt`
  it was built from -- so an RVT save that only touched settings leaves `output.txt` (comments, profile
  directives and all) alone. It pulls silently unless that would lose something, and then asks first: edits to
  `output.txt` not yet applied, `--` comments (RVT's script has none), `-- @if` / `${...}` directives (the
  pulled script is one profile already resolved), or unsaved edits in an open `output.txt` tab. Declining keeps `output.txt`; the next Apply then
  rebuilds from it and RVT's script changes are dropped, as the dialog says. Covered end to end against real
  variants (`test_script_pull_end_to_end.py`) and in the IDE (`test_rvt_script_pull.py`).
  **Still open:** RVT edits to anything that is neither in `settings/*.json` nor in the script (Apply rebuilds
  from the frozen `init_gametype/<id>.bin`) are still dropped on the next Apply, and a project last built
  before this landed has no snapshot, so its first RVT save can't be compared -- Apply once (Launch RVT does)
  and it's tracked from then on.
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

- ~~**The `.pyd` has no source in this repo.**~~ Done (decision 5: build in CI, everything in this repo). The
  non-UI ReachVariantTool engine (GPLv3, as this repo is), the bindings and a CMake file are vendored under
  `native/`; `native/build.py` builds the module and installs it into the package, and was checked by
  building from this tree, running the native tests against the result, then wheel -> clean venv -> the module
  loads from the installed package. `setup.py` makes wheels `cp3XX-win_amd64` rather than `py3-none-any`,
  and the sdist carries the C++. `.github/workflows/native.yml` builds on Windows for 3.12-3.14, runs the whole
  suite against it (the first CI run of any native test) and uploads the wheels.
  **First GitHub runs found three real problems, all fixed but not yet re-run:** (1) the workflow installed the
  package non-editable, so on 3.12/3.13 the tests imported a site-packages copy without the built module and
  650 tests silently skipped, and on 3.14 they would have tested the *committed* module -- now editable, with a
  step that fails if the module just built doesn't load; (2) `build.py` finished and installed the build, then
  crashed deleting its temporary build directory because MSBuild still held a handle on it -- the default build
  directory is now the persistent, git-ignored `native/build/`; (3) four IDE tests had never run on Windows
  under Qt's `offscreen` platform, which has no emoji font (icons all render as one box) -- the Windows job now
  uses the real platform, the maps-panel test reads `full_text` instead of the width-dependent elided text, and
  the emoji-rendering comparisons skip with a stated reason where a platform can't draw emoji. **Still to
  confirm on a real run:** that the 3.12-3.14 jobs go green with the native tests actually running (not
  skipped), and that vcpkg's Qt5 caches. `publish.yml` still builds an untagged wheel from the *committed*
  module; once the native job is green, switch publish to its wheels (build on Windows, one wheel per Python,
  `pypa/gh-action-pypi-publish` over the lot) and stop committing the `.pyd`/DLLs -- until then a checkout works
  without a toolchain because they're committed.
  Still Windows-only and per-CPython-version (the engine uses MSVC-specific constructs); Linux/macOS wheels
  would need a portability pass first.
- **Multi-platform / multi-Python**: solved for Python (CI builds 3.12-3.14 wheels, see above), not for
  platform -- it is 64-bit Windows only, and so is in-reach itself (Steam/MCC paths).
- **CI can't run the corpus** (MCC files aren't redistributable). The 100% figures are a local measurement;
  consider committing a *derived* fidelity report (counts only, no game content).
- The full suite takes ~6.5 minutes; worth splitting fast/slow markers before it grows further.

---

## Decisions

All settled; nothing is waiting on you.

1. **Module manifest** -- a storage need is *inferred* from the module's own `@` annotations, never declared
   twice. The linter and the budget panel show the totals. `module.toml` therefore holds only what code can't
   say: name and version, `order` (`after`/`before`/`phase`), `params`, shared items, tags. `TO_IMPLEMENT` §5.1's
   `[requires]` table is dropped (and with it the whole class of "manifest disagrees with code" lint errors);
   `[provides]` likewise follows from the annotations.
2. **Modules write into `settings/`** -- self-contained: a module carries its own trait sets, options,
   widgets and labels, and whatever the user has edited in `settings/` wins (the same rule the compiler's table
   reconciliation already follows: created from either side, never dropped once edited).
3. **Fusion** -- adjacency fusion is automatic, with the legality check `TO_IMPLEMENT` §7 describes (IR018).
   Subroutine lowering of a shared preamble happens only when a module author asks for it with an explicit
   `@fusion` override, and every override is listed in `link_map.json`. Revisit once the budget panel shows
   what each costs.
4. ~~**RVT round trip**~~ -- decided: (c), pull the script back out too. Built; see item 2.
5. ~~**Native source**~~ -- decided: build in CI, with the source in this repo, so a fresh install contains
   everything. Built; see item 6.
6. **Default profile for new projects** stays `dev`.

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
