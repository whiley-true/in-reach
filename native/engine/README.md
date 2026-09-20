# Vendored ReachVariantTool engine

The non-UI half of [ReachVariantTool](https://github.com/DavidJCobb/ReachVariantEditor) (RVT), by David J.
Cobb -- the game-variant engine that reads and writes Halo: Reach `.bin` files and compiles/decompiles Megalo
-- copied here so `_reachvarianttool` can be built from this repository alone. RVT is GPLv3, as is in-reach
(see the repository's `LICENSE`); the licences of what RVT itself bundles are in `LICENSES/`.

| Folder | What it is |
|---|---|
| `ReachVariantTool/game_variants/` | the engine: variant formats, the Megalo trigger/opcode model, compiler and decompiler |
| `ReachVariantTool/formats/`, `helpers/` | file-format and utility code the engine uses (bitstreams, strings, INI) |
| `ReachVariantTool/services/` | only `ini.*` is compiled; the rest of RVT's services are UI-side and were left out |
| `zlib/` | zlib's C sources, compiled in directly |

Only what `../CMakeLists.txt` compiles (plus the headers those files include) is here: none of RVT's UI, help
files, resources or Visual Studio project files. Sources the build never compiled were dropped
(`helpers/qt/{color,string_scanner,tree_widget,widget}.cpp`, `services/{RVTThemeEngine,localization_library,
syntax_highlight_option}.cpp`); their headers stay so includes resolve.

Copied from the `mega-ide` prototype's tree (`mide/ReachVariantTool-src/native/src`), which tracked upstream
RVT with local changes; this repo's own changes to the engine, if any, are in git history from here on. The
Python bindings on top of it are `../bindings.cpp` and `../type_casters.h`.
