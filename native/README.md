# Native extension (`_reachvarianttool`)

`_reachvarianttool` is a pybind11 module: ReachVariantTool's game-variant engine (read/write `.bin` files, the
Megalo compiler and decompiler) plus Python bindings for it. `in_reach.app.rvt.rvt_bridge` loads it from
`src/in_reach/app/rvt/native/`.

Everything needed to build it is in this folder:

| Path | What it is |
|---|---|
| `engine/` | the vendored, non-UI half of ReachVariantTool (GPLv3, like this repo) -- see `engine/README.md` |
| `bindings.cpp`, `type_casters.h` | the pybind11 bindings written for in-reach |
| `CMakeLists.txt` | compiles the two into `_reachvarianttool` |
| `build.py` | builds it and installs the module and its Qt runtime DLLs into the package |
| `verify.py` | checks the installed module is the one in-reach actually loads (CI runs it between build and tests) |

Wheels from PyPI contain a built module, so nobody installing in-reach needs any of this; it's for changing
the bindings, or for building on a Python version a wheel wasn't published for. CI builds it too
(`.github/workflows/native.yml`), on Windows, for Python 3.12-3.14, and runs the whole test suite against
the result. The module is ABI-locked to the CPython version it was built with (`cp314` for 3.14) and only
builds on 64-bit Windows.

## What was added to the bindings

The bindings came over from the `mega-ide` prototype (its commit `5d0fe97`, "feat(native): bindings for
building scripts from scratch, and script-defined tables", plus the construction bindings the compiler relies
on -- `clear_triggers`, `mark_trigger_*`, `set_scope_by_format`, `AnyVariable.wrap`, ... -- that had only ever
existed in that repo's working tree) and have been changed here since; git history from the commit that
vendored them is the record of what is ours. Two groups are worth describing, because the compiler depends on
them and they aren't obvious from the names:

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

### Names and shape of scripted options and trait sets

| Change | Why |
|---|---|
| `ScriptedPlayerTraits.name`/`.desc`, `ScriptedOption.name`/`.desc`, `ScriptedOptionValue.name`/`.desc`: read-only -> read/write | A new entry points at the script-strings table's one shared empty string; setting text on that string would rename every entry. The setter takes a `ReachString` (e.g. one from `script_strings.add_new()`) so an entry can have its own, which is what `resource_text.py` does. |
| `ScriptedOption.add_value()` | The engine's own `ReachMegaloOption::add_value()`; a toggle needs a second value and `add_scripted_option()` makes one. `RuntimeError` for a range option or at the value limit. |
| `ScriptedOption.make_range()` | The engine's own `make_range()` (what RVT's range switch does): creates `range_min`/`range_max`/`range_default`. Set `is_range` too. |

`Variable.which` was already writable, so `current_player.script_stat[N]` needed no change to
`set_scope_by_format()`; the compiler copies `which` from a `current_player.number[N]` example.

## Building

Needs Windows, CMake, Visual Studio 2022's C++ build tools, and [vcpkg](https://vcpkg.io) with Qt5
(`vcpkg install qt5-base:x64-windows`). Then, with the interpreter you run in-reach with:

```
python -m pip install pybind11
python native/build.py                       # --vcpkg-root C:/vcpkg (or $VCPKG_ROOT), --build-dir, --jobs
```

That configures and builds with CMake and copies `_reachvarianttool.cp3XX-win_amd64.pyd`, `Qt5Core.dll`,
`z.dll`, `pcre2-16.dll`, `double-conversion.dll` and `qt.conf` into `src/in_reach/app/rvt/native/`. The
build tree is kept in `native/build/cp3XX/` (git-ignored, one per Python version; `--build-dir` puts it
elsewhere), so later builds are
incremental: touching only `bindings.cpp` recompiles that one file and relinks (a couple of minutes); the
first build compiles the whole engine (several). A zero exit code is not proof of a good build if you drive CMake yourself -- grep the log for `error C` /
`error LNK`; `build.py` stops on a failed build and on a missing or ambiguous module.

The `.pyd` and DLLs currently in the repo are committed build output, so a checkout works without building.
Rebuilding replaces them; commit the result only when the bindings changed.
