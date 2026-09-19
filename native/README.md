# Native extension (`_reachvarianttool`)

`src/in_reach/app/rvt/native/_reachvarianttool.cp314-win_amd64.pyd` is a prebuilt pybind11 module.
Its C++ source is **not in this repo**: it's built from the `mega-ide` prototype's own tree,
`mide/ReachVariantTool-src/native/` (ReachVariantTool's engine sources, GPLv3, plus
`python-bindings/bindings.cpp` and `CMakeLists.txt`). This folder records what this repo changed in that
source, so the binary can be reproduced and reviewed.

## What was added to the bindings

Committed in `mega-ide` as `5d0fe97` ("feat(native): bindings for building scripts from scratch, and
script-defined tables"), which also commits the earlier construction bindings the compiler relies on
(`clear_triggers`, `mark_trigger_*`, `set_scope_by_format`, `AnyVariable.wrap`, ...) that had only ever
existed in that repo's working tree. This repo's `.pyd` was built from that commit (SHA-256 begins
`f4355fdd5f762dc2`; the build before it began `be515cc6dd04aa83`). The script-defined-table group:

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
