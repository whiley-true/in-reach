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
- **Script projects work end to end** (`script/project.toml`, blocks, modules): they link, fuse, allocate,
  compile in-house from the linker's text, report errors at their source lines, and show their budget. Verified
  against the design's Hill Rush example (`tests/app/script_project/hill_project.py`), including a real build
  whose decompile shows the two modules' fragments fused into one `for each player` loop. **Not verified in the
  game** -- nothing here has run in Halo, so "the fused/allocated script means what the modules meant" rests on
  the compiler's own checks and the analysis' conservatism, not on the engine.
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
- ~~**RVT edits don't reach the script.**~~ Built (decision 4 (c)) -- **but mostly dormant, and I built it before
  checking what the shipped RVT can do.** The bundled RVT is the patched build from `in-reach-v2`: its Gametype
  Code page is read-only with Compile/Decompile disabled, so RVT never changes the script text; what users edit
  there is *script settings* (forge labels, options, trait sets, widgets, stats, strings), and those already
  flow into `settings/*.json` through the existing resync. So the pull-back below only fires for a `.bin`
  changed by something other than the bundled RVT. It is harmless (a no-op when the script is unchanged) and
  stays; it is *not* what makes "edit in RVT, keep working here" work. When RVT saves, the resync also notices
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

1. ~~**`-- @` annotation parsing**~~ Done: `megalo_ast/annotations.py`, `parse_annotations(text)`. Twenty storage
   spellings, `@bitfield`, `@trait`/`@option`/`@widget`/`@label`, `@fragment`/`@loop`/`@gate`/`@guard`/`@guard-end`/
   `@preamble`/`@provides`/`@traits`/`@fusion` (incl. the `subroutine` mode from decision 3) and `@doc`/`@see`/
   `@assumes`. It only *parses*: a malformed annotation is reported (line and column, one per annotation, with a
   suggestion for a misspelt name) and never stops the good ones around it; duplicate names, capacity and the
   other cross-line rules are step 2's. Grammar choices where `TO_IMPLEMENT` §4's examples were loose are in
   its new §4.8 -- notably that prose after the arguments needs a second `--`. Also added a public
   `parse_expression()` to the Megalo parser for the `@gate`/`@guard` conditions.
   *Not done yet, on purpose:* attaching each annotation to the statement it precedes (`@doc` "attaches to that
   AST node"), and rendering annotations back to text -- both belong with the semantic model in step 2, which is
   the first thing that needs them.
2. ~~**Project model**~~ Done (modules first -- decided): `app/script_project/` -- `load_project(folder)` reads
   `script/project.toml` and each `module.toml`, discovers modules and `blocks/*.mgl`, preprocesses every file
   with the constants it sees and reads its annotations, orders the blocks, merges kinds, and returns a
   `ScriptProject` plus a *located* diagnostic (file, line, code) for every problem it finds -- manifest syntax
   and types, unknown keys, a bad or missing module parameter (at the importer's line or the module's own), an
   undefined `${}`, a malformed annotation, a block-order cycle (naming every edge), conflicting kinds -- without
   stopping at the first. No allocation, no linting yet. Everything after this reads a *project*, so the linter
   is multi-file from the start, and `is_linked(folder)` (a `script/project.toml` exists) separates it from
   today's single-file projects, which are untouched. The design's own Hill Rush example (§13) loads with zero
   diagnostics (`test_script_project_loader.py`). Choices where the design was ambiguous, all in
   `TO_IMPLEMENT` §4.5/§5:
   - **A profile overrides `project.toml`'s `[constants]`** (they are defaults), not the other way round --
     the design's own example (`PHASE_TIMER = 6` there, `2` in `dev.env`) only makes sense that way; a constant
     defined as `"${OTHER}"` follows OTHER's final value. Module parameters beat both, in that module's files.
   - **Annotation arguments are substituted by the preprocessor** (`-- @ptimer t default=${interval}` is how a
     parameter reaches storage) -- previously *all* comments were left alone. The `-- @` prefix, a `-- note`,
     `@doc` prose and ordinary comments still are.
   - **A block is a file in `blocks/` (name = stem, upper-cased) or exists because a module writes
     `@fragment BLOCK.x`**; a module's `[order] after/before` name blocks and apply to every block it
     contributes to. Blocks nothing orders sort after the listed ones, in first-seen order, so a relink is stable.
   - `script_sync` (the RVT pull-back) does nothing in a linked project.
   Found by the tests on the way: the cycle finder crashed when the lowest-ranked stuck block was only
   *downstream* of the cycle, which is exactly what a mistaken `before = ["SETUP"]` produces.
3. ~~**Semantic model + linter**~~ Done for every rule that needs no engine catalog: `model.py` (fragments,
   preambles, blocks, storage, resources) and `lint.py`: IR005, IR006, IR007 (as a value only), IR010 (a warning), IR011, IR016; IR013/IR015
   come from `load_project`, IR004 (temporaries over the cap, *post-fusion*), IR012 (a counter within 10% of its
   cap) and IR018 (a forced fusion the analysis would have declined) from the linker; IR017 is moot (decision 1).
   **Still not done, and why:** IR001-IR003, IR008, IR009, IR014 and IR006b need an engine catalog (dereference
   depth, action-used-as-value, trait application order, which kind owns a slot default...) that doesn't exist yet
   -- `reference/megalo/` has the raw material, and the "ONI EVAC Implementation Guide" they cite isn't in either
   prior repo.
4. ~~**Linker**~~ Done: `allocation.py` (stable slots, pins, kinds sharing object slots, one default per shared
   slot, bitfields), `resources.py` (traits/options/widgets into `settings/script_settings.json`; a resource
   keeps its index, the user's edits win, nothing is dropped) and `linker.py` (`link()` -> `build/Compiled.txt`,
   `declarations.mgl`, `link_map.json`; writes nothing unless everything succeeded, and nothing that hasn't
   changed). It emits `alias` lines (measured: works, and keeps the source readable). In *linked mode* the
   compile flow links first and compiles the linker's text; compiler errors are reported at the source file and
   line (`BuildMessage.file`, via `source_lines`). Two things found on the way: the native fallback compiler
   can't create trait sets/options/widgets, so a mistake elsewhere in a linked script used to be reported next to
   a bogus "the maximum defined index is 1" -- the fresh variant is now grown to match `settings/` first; and
   `View Compiled` would have overwritten the linker's `build/Compiled.txt` with the (stale) `output.txt` --
   it shows the linker's text now.
5. ~~**Budget panel + fusion**~~ Done. Fusion (`fusion.py`): adjacent fragments with the same loop, gate and
   preamble become one trigger when a conservative read/write analysis finds nothing one writes that another
   reads on a different iteration (anything it can't classify declines the merge); `@fusion never` and
   `force:<group>` (IR018 warns if forcing overrode a real conflict); a guard every member shares is hoisted
   unless something in the group writes what it reads; every merge and every declined merge with its reason is
   in `link_map.json`. **`@fusion subroutine` is refused with a warning, not implemented:** lowering a shared
   preamble to an engine subroutine is unverified -- in particular whether a called trigger sees its caller's
   temporaries, which the shared-preamble design depends on -- and there is no way to check without the probe
   gametype (§11.1). **Reported savings are triggers and preambles only**, not actions/conditions (the design's
   example shows those; measuring them needs a compile per candidate). The budget is the Scripts view (storage
   pools, engine tables, and trigger/condition/action counters measured on the built variant and recorded in
   `link_map.json` by `record_counters()`); "bits" (space usage) is still only in the Dashboard's stats box.
6. **Python as a one-way generator** -- *dropped from the roadmap (decided): the IDE/CLI split, shareable modules and the composition
   board below replaced it; nothing here should be built for Python authoring.*
6-old. **Python as a one-way generator** front-end that emits `.mgl`/AST into `build/` (decided earlier: a
   generator, not a synced peer). Only after modules show what `.mgl` can't express -- an
   `inline function`/macro facility in `.mgl` may cover most of it.

Per-module choice of syntax (`.mgl` or `.py`) needs no sync machinery because modules meet only at the linker,
via their manifests. **Rule to keep:** one editable source per module; every other view is regenerated.

### 4. Script editing in the IDE

Right now a script is edited as plain text and errors come back in Apply's failure dialog. Still to do:

- ~~**Megalo syntax highlighting**~~ Done (`megalo_highlighter.py`): `.mgl`, `script/output.txt`, `build/Compiled.txt`;
  keywords, built-in roots, strings, numbers, comments, `-- @` annotations, `-- @if`/`@else`/`@end` directives
  and `${...}` placeholders. Line-based and regex-driven on purpose (a half-typed script must still colour), so it
  doesn't use the parser's spans.
- ~~**A Problems panel**~~ Done (bottom-panel "Problems" tab): a linked project's checks re-run on every save,
  and an Apply puts every compiler message there, at its source file and line. Clickable. A single-file
  project's errors are there too (at `script/output.txt`), but only after an Apply -- nothing re-checks a
  single-file script as you type.
- ~~**Scripts panel**~~ Done for script projects: profile picker, modules, blocks, budget, fusion, Check/Link/New
  Module, and "Create Script Project" for a single-file one (`scaffold.py`). `in-reach lint` and `in-reach link`
  run the same checks headlessly.
- **Autocomplete / hover** from `catalog.json` and `reference/megalo/`; **LLM panel** is a stub too. The
  audience decision (players who use the LLM panel) makes the linter + a machine-readable catalog the thing
  that makes an LLM useful here. Size: L.
- *Stamp Release* and profiles -- decided: **warn, don't switch.** `MainWindow.vcs_stamp` asks "Stamp Anyway /
  Cancel" when the project has a `release` profile and isn't on it (nothing is switched: the active profile is a
  project file the stamp records). Revisit switching-and-restoring if the warning proves not enough.
  `TO_IMPLEMENT` §4.5 also wants the active profile and flags stamped into the commit message; the
  `Compiled.txt` header of a linked project has had them from the start, the commit message doesn't.

### 5. Known compiler gaps (all fall back to native, none is wrong)

- ~~**`@option` couldn't be built; trait sets and options had empty names.**~~ Fixed with three new native bindings (a
  rebuild of the `.pyd` -- see `native/README.md`): `name`/`desc` became settable on trait sets, options and option values,
  `ScriptedOption.add_value()` and `.make_range()`. A new entry points at the strings table's one shared empty string, so a
  declared trait showed a blank name in game; `resource_text.py` now gives each declared entry strings of its own (the
  alias by default, `name = "..."`/`desc = "..."` when given, "Off"/"On" for a toggle) and `strings_writer.own_text` keeps
  `settings/strings.json` in step. The code *owns* that text -- overwritten every build -- because the strings are found by
  position and a position moves when something is declared before it; rename by editing the declaration. Options now
  build (toggle and range) and follow their declaration through a resync; a range option's enum values, which a reload
  drops, no longer count as a difference anywhere.
  **Still to do:** `@stat` and `@widget` have no text to name (a widget has none; stats aren't declarable yet).

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
  step (`native/verify.py`, unit-tested) that fails if the module just built doesn't load *or* if a different
  copy of it was loaded; (2) `build.py` finished and installed the build, then
  crashed deleting its temporary build directory because MSBuild still held a handle on it -- the default build
  directory is now the persistent, git-ignored `native/build/`; (3) four IDE tests had never run on Windows
  under Qt's `offscreen` platform, which has no emoji font (icons all render as one box) -- the Windows job now
  uses the real platform, the maps-panel test reads `full_text` instead of the width-dependent elided text, and
  the emoji-rendering comparisons skip with a stated reason where a platform can't draw emoji. **Still to
  confirm on a real run:** that the 3.12-3.14 jobs go green with the native tests actually running (not
  skipped), and that vcpkg's Qt5 caches. **All of that went green on real runs and was merged.**
  **Publishing** (`publish.yml`) now builds one `cp3XX-win_amd64` wheel per Python by *calling* `native.yml` (a
  reusable workflow, so a release is built and tested with exactly the steps that pass on PRs) plus an sdist, and
  `.github/scripts/check_dist.py` refuses to upload unless `dist/` is exactly that -- 3.12-3.14 Windows wheels and
  one sdist, one version, equal to the release tag. The gate exists because the old Ubuntu build would now tag its
  wheel `linux_x86_64`, which PyPI rejects *after* the sdist may already be up, and a PyPI version can't be
  re-uploaded. `native.yml` also runs on pushes to `main` so a release finds the vcpkg Qt cache. **Not yet run:**
  a real release -- the first one is the test of `publish.yml` (actionlint-clean and covered by
  `test_publish_workflow.py`, but GitHub has never executed it). **Done:** the `.pyd`/DLLs are no longer
  committed (git-ignored; a checkout needs `python native/build.py` before native features or tests work), the sdist is
  source only, a wheel carries only its own Python's module, and the bundled ReachVariantTool is down from 62 MB to 28 MB
  (the OpenGL software fallback, ANGLE/Direct3D DLLs and Qt translations were never loaded -- checked by launching it and
  reading its loaded-module list; `tests/app/test_native_packaging.py` keeps all of that true). Each
  wheel is also installed into a clean environment and imported from outside the checkout before it is uploaded
  as an artifact (the smoke-test step in `native.yml`), since the test suite only ever imports the source tree.
  Still Windows-only and per-CPython-version (the engine uses MSVC-specific constructs); Linux/macOS wheels
  would need a portability pass first.
- **Multi-platform / multi-Python**: solved for Python (CI builds 3.12-3.14 wheels, see above), not for
  platform -- it is 64-bit Windows only, and so is in-reach itself (Steam/MCC paths).
- **CI can't run the corpus** (MCC files aren't redistributable). The 100% figures are a local measurement;
  consider committing a *derived* fidelity report (counts only, no game content).
- The full suite takes ~6.5 minutes; worth splitting fast/slow markers before it grows further.

---

## Roadmap after the split (decided; work done)

The repos: `in-reach` (this: library + CLI + the native module), `in-reach-ide` (the PyQt IDE, extracted with its git history;
depends on `in-reach>=0.3,<0.4`), `within-reach` (hot reload / screen capture; a scaffold, `in-reach` and `in-reach-ide` will
depend on it). Windows only; no VSCode tooling (a text file in any editor is the goal); no Linux CI; no Python authoring.

- **Phase 0** guard tests -- `tests/test_import_boundaries.py`: the library and CLI import no GUI and never the IDE; importing
  `script_project`/`megalo_ast` loads no native module. Done.
- **Phase 1** `in_reach.api` + a full CLI (`build`, `check`/`lint`, `link`, `show`, `create-project`, `new-module`, `profile`,
  `new`, `export`, `verify`, `launch`, `vcs ...`, `module ...`, `block-order`, `move-fragment`, `run`), `--format json`
  (schema 1), exit codes 0/1/2. `in-reach run` opens the IDE only if `in-reach-ide` is installed. Done.
- **Phase 2** (language server / VSCode extension): dropped.
- **Phase 3** code views: `show --view rvt|rvt+|megalo`, `build/Decompiled.txt`, "View Decompiled" in the IDE. Done.
- **Phase 4** shareable modules: `module add|update|lock|verify`, `project.lock`, path and git sources. Done. **Not done:** a
  registry/hosted index (decided: path and git URL are enough for now); nothing checks a shared module against the
  linter's rules *before* vendoring it (it is checked like any module once added).
- **Phase 5** index database: deferred (its consumer was the language server).
- **Phase 6** composition: the edit API and commands are done; the IDE board (module checkboxes, drag to reorder blocks,
  "Move to" for fragments) is done. **Not done:** dragging a *fragment* between blocks with the mouse (it is a right-click
  menu), and a visual budget/fusion preview while dragging (the view refreshes after each edit).

**Known gaps / risks from the split:** the IDE repo's CI installs `in-reach` from PyPI, so nothing there can pass until an
`in-reach` with `in_reach.api` (0.3.0) is published -- release `in-reach` first. `tests/hill_project.py` in `in-reach-ide` is a copy
of this repo's fixture and must be kept in step by hand. Only the cp314 native module is committed here; CI builds the others.

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
  - §7/§13.9: the design shows a fused trigger with `alias in_hill = allocate temporary number`; the linker emits
    `alias in_hill = temporaries.number[0]` (the compiler's own spelling). Block headings are only written for a
    block that has code of its own, and `saved` in `link_map.json` counts triggers and preambles, not
    actions/conditions.
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
