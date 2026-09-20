# Native extension (`_reachvarianttool`)

`src/in_reach/app/rvt/native/_reachvarianttool.cp314-win_amd64.pyd` is a prebuilt pybind11 module.
Its C++ source is **not in this repo**: it's built from the `mega-ide` prototype's own tree,
`mide/ReachVariantTool-src/native/` (ReachVariantTool's engine sources, GPLv3, plus
`python-bindings/bindings.cpp` and `CMakeLists.txt`). This folder records what this repo changed in that
source, so the binary can be reproduced and reviewed.

## What was added to the bindings

Two groups. The first is committed in `mega-ide` as `5d0fe97` ("feat(native): bindings for building
scripts from scratch, and script-defined tables"), which also commits the earlier construction bindings
the compiler relies on (`clear_triggers`, `mark_trigger_*`, `set_scope_by_format`, `AnyVariable.wrap`,
...) that had only ever existed in that repo's working tree. The second, variable declarations, is **not
yet committed in `mega-ide`** -- it is an uncommitted change to `python-bindings/bindings.cpp` there
(about 85 lines, inserted just above the `MultiplayerData` class). This repo's `.pyd` was built from
`5d0fe97` plus that change (SHA-256 begins `987fff7304a4e898`; the build before it began
`f4355fdd5f762dc2`, and the one before that `be515cc6dd04aa83`).

### Variable declarations

| Change | Why |
|---|---|
| `MultiplayerData.variable_declarations(scope)` | The `VariableDeclarationSet` for `VariableScope.global`/`player`/`object`/`team`; `ValueError` for any other scope. |
| `VariableDeclarationSet.count(type)` / `get(type, i)` / `grow_to(type, n)` / `clear()` | Read and size the five per-type lists. `grow_to` never shrinks (the engine's `VariableDeclarationList::resize()` leaks the dropped entries when it does) and raises `IndexError` past the scope's own maximum; `clear()` deletes them properly. |
| `VariableDeclaration.networking` (`VariableNetworkPriority.local`/`low`/`high`), `.has_network_type`, `.has_initial_value`, `.type`, `.initial_is_default()` | A timer has no network priority: setting one raises `RuntimeError`. |
| `VariableDeclaration.initial_number`, `.initial_team` | A number/timer's initial value is a live `ScalarVariable` -- retarget it with the existing `set_scope_by_format()` (`"%i"` for a constant, `"script_option[%i]"`, or a built-in's own text such as `"game.loadout_cam_time"`). A team's is an int: -1 no team, 0-7 `team[N]`, 8 neutral. |

These are what let the in-house compiler do what native `compile_script()` does with declarations --
rebuild all four sets from the script text -- without calling it; see
`src/in_reach/app/rvt/variable_declarations.py`.

### Script-defined tables

| Change | Why |
|---|---|
| `TimerRateArgument.value`: read-only -> read/write | The value is a plain `uint8_t` index into the engine's 27-entry rate table; a rate is found by trying indexes until `decompile()` matches, as every other enum here is. Previously a rate could only be cloned from an existing one. |
| `WidgetArgument.set_value(mp, index)`, `PlayerTraitsArgument.set_value(mp, index)` | Their `.value` is a refcount pointer into the variant's own table with no setter. Same pattern as the existing `ForgeLabelArgument.set_value()`. Raises `IndexError` past the table's end. |
| `MultiplayerData.add_scripted_option()` / `add_scripted_player_traits()` / `add_scripted_stat()` / `add_scripted_hud_widget()` | Nothing else can create an entry: native `compile_script()` fails with "Index N is out of bounds" for a table entry (unlike forge labels, which it creates on first mention). These do what RVT's own script-editor "add" buttons do (`emplace_back()`, `is_defined = true`, name defaulted to an empty script string; options go through the engine's own `create_script_option()`). Each raises `RuntimeError` at its engine cap (16 options, 16 trait sets, 4 stats, 4 widgets). |

`Variable.which` was already writable, so `current_player.script_stat[N]` needed no change to
`set_scope_by_format()`; the compiler copies `which` from a `current_player.number[N]` example.

## Rebuilding

From `python-bindings/` in the source tree (toolchain: CMake, vcpkg with Qt5 at `C:\vcpkg`, MSVC Build
Tools 2022 -- see that repo's `.claude/rules/native-bindings.md` for the full procedure and gotchas):

```
cmake --build build --config Release --parallel 8
```

then copy `build/Release/_reachvarianttool.cp314-win_amd64.pyd` over the one in
`src/in_reach/app/rvt/native/`. An incremental build after touching only `bindings.cpp` recompiles that
one file and relinks. Grep the log for `error C`/`error LNK` -- a zero exit code alone isn't proof.

The `.pyd` is ABI-locked to CPython 3.14 on 64-bit Windows.
