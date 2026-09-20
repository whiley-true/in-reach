cmake_minimum_required(VERSION 3.20)
project(reachvarianttool_py LANGUAGES CXX C)

# Builds `_reachvarianttool`, the pybind11 module in_reach.app.rvt.rvt_bridge loads: ReachVariantTool's
# non-UI game-variant engine (parsing/writing .bin files, the Megalo compiler/decompiler) plus bindings.cpp.
# See native/README.md for how to build it and what was added on top of the upstream engine.

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# The upstream project (DavidJCobb/ReachVariantEditor) is a Qt VS Tools project, not CMake. Only the
# non-UI subset is vendored (see engine/README.md), and it's compiled directly from source here.
set(ENGINE_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/engine/ReachVariantTool)

# helpers/qt/ini.h declares a Q_OBJECT class (cobb::qt::ini::file); everything else we pull in is plain
# QtCore (QString/QFile/QSaveFile/QDataStream/QMultiMap), no other moc'd types.
set(CMAKE_AUTOMOC ON)

# Qt5::Widgets is linked only because services/ini.cpp has an unused `#include <QApplication>` left over
# from the GUI app; nothing compiled here constructs a QApplication or touches the widgets subsystem, and
# the built module doesn't import Qt5Widgets.dll at runtime.
find_package(Qt5 5.15 COMPONENTS Core Widgets REQUIRED)

execute_process(
   COMMAND "${Python3_EXECUTABLE}" -m pybind11 --cmakedir
   OUTPUT_VARIABLE pybind11_ROOT_RAW
   OUTPUT_STRIP_TRAILING_WHITESPACE
)
if(NOT pybind11_ROOT_RAW)
   # Python3_EXECUTABLE isn't set until find_package(Python3) runs; fall back to plain "python".
   find_package(Python3 COMPONENTS Interpreter REQUIRED)
   execute_process(
      COMMAND "${Python3_EXECUTABLE}" -m pybind11 --cmakedir
      OUTPUT_VARIABLE pybind11_ROOT_RAW
      OUTPUT_STRIP_TRAILING_WHITESPACE
   )
endif()
list(APPEND CMAKE_PREFIX_PATH "${pybind11_ROOT_RAW}")
find_package(pybind11 CONFIG REQUIRED)

file(GLOB_RECURSE ENGINE_GAME_VARIANTS_SOURCES CONFIGURE_DEPENDS "${ENGINE_ROOT}/game_variants/*.cpp")
file(GLOB ENGINE_FORMATS_SOURCES CONFIGURE_DEPENDS "${ENGINE_ROOT}/formats/*.cpp")
# Recursive: helpers/ has its own subfolders (e.g. helpers/ini/) with real .cpp files, not just
# helpers/qt/ (filtered back out below -- only helpers/qt/ini.cpp and helpers/qt/string.cpp are needed).
file(GLOB_RECURSE ENGINE_HELPERS_SOURCES CONFIGURE_DEPENDS "${ENGINE_ROOT}/helpers/*.cpp")
list(FILTER ENGINE_HELPERS_SOURCES EXCLUDE REGEX "helpers/qt/")

# Bundled zlib (used by the string table/block compression code), built as plain C sources instead of via
# its own project like the upstream solution does.
file(GLOB ENGINE_ZLIB_SOURCES CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/engine/zlib/*.c")

set(ENGINE_SOURCES
   ${ENGINE_GAME_VARIANTS_SOURCES}
   ${ENGINE_FORMATS_SOURCES}
   ${ENGINE_HELPERS_SOURCES}
   ${ENGINE_ZLIB_SOURCES}
   ${ENGINE_ROOT}/helpers/qt/ini.cpp
   ${ENGINE_ROOT}/helpers/qt/string.cpp
   ${ENGINE_ROOT}/services/ini.cpp
)

pybind11_add_module(_reachvarianttool
   bindings.cpp
   type_casters.h
   ${ENGINE_SOURCES}
)

target_include_directories(_reachvarianttool PRIVATE ${ENGINE_ROOT})

target_compile_definitions(_reachvarianttool PRIVATE
   _CONSOLE
   NOMINMAX
   WIN32_LEAN_AND_MEAN
)

if(MSVC)
   target_compile_options(_reachvarianttool PRIVATE /std:c++latest /Zc:__cplusplus /utf-8 /bigobj)
endif()

# Debugging only: an AddressSanitizer build for tracking down memory-safety bugs that show up inside the
# engine's own read()/write() code. Configure with -DRVT_ENABLE_ASAN=ON in a *separate* build directory --
# ASan changes the ABI and adds real overhead, and is never something to ship.
option(RVT_ENABLE_ASAN "Build with MSVC AddressSanitizer instrumentation (debugging only)" OFF)
if(RVT_ENABLE_ASAN AND MSVC)
   target_compile_options(_reachvarianttool PRIVATE /fsanitize=address /Zi)
   target_link_options(_reachvarianttool PRIVATE /INCREMENTAL:NO /DEBUG)
endif()

target_link_libraries(_reachvarianttool PRIVATE Qt5::Core Qt5::Widgets)
