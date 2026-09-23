# Sample script project

A small, complete script project to try. It gives every player a point per second, makes everyone 50% faster, and
ends the round at 10 points.

## Try it

1. Make a new in-reach project (or use one you don't mind changing).
2. Copy everything in this folder's `script/` into that project's `script/` folder, replacing `project.toml`.
   (If you already pressed "Create Script Project", delete `script/blocks/main.mgl` first, or keep it: it is
   built after the sample's blocks.)
3. In the IDE: the **Problems** tab should say "No problems"; the **Scripts** view lists two modules and three
   blocks, and shows `TICK` as one fused trigger.
4. **Apply** (Ctrl+Shift+B), then open **View Compiled** to read the script that was built. Expect one
   `for each player` loop holding both modules' code, a `declare player.timer[0] = 1`, and an `alias` for the trait.
5. Launch RVT / MCC to play it.

## What each file shows

| File | Shows |
|---|---|
| `project.toml` | block order, a `${CONSTANT}`, the module list |
| `blocks/setup.mgl` | a block file; `@number` storage the linker allocates a slot for |
| `blocks/win_check.mgl` | plain Megalo using a constant (`${SCORE_TO_WIN}`) |
| `modules/scoring/` | `@ptimer` storage, and a `@fragment` (a loop body added to a block) |
| `README.md`, `-- @doc`, `-- @tags` | documentation: `in-reach docs` writes `build/docs/overview.md` from them |
| `modules/speed_boost/` | `@trait` -- a trait set created and named for you -- and a second fragment that is fused with the first |

## Things to try

- Change `value_150` in `speed_boost.mgl` to `value_200` and Apply: the trait set in
  `settings/script_settings.json` follows.
- Change `SCORE_TO_WIN` in `project.toml`, or put `SCORE_TO_WIN=50` in `script/env/release.env` and choose the
  `release` env (the Envs section of the Scripts view, or `in-reach env set release`): the release build wins at 50.
- Add `-- @fusion never` under `-- @loop player` in one fragment: the Scripts view then shows them as two
  triggers, and says why.
- Put a mistake in `win_check.mgl` (say `game.no_such_action()`): Apply reports it at that file and line.

- Add `-- @option o_bonus { type = "toggle", default = 0, name = "Bonus round" }` to a block or module, then use it as
  `if o_bonus == 1 then ... end`: a script option is created, and named, for you.
