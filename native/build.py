"""Builds ``_reachvarianttool`` from this folder and installs it into the package.

    python native/build.py                      # uses this interpreter, C:/vcpkg (or $VCPKG_ROOT)
    python native/build.py --build-dir out/nb   # keep the build tree somewhere else (default: native/build/<cpXY>)

It configures and builds with CMake, then copies the built module and the Qt runtime DLLs it needs into
``src/in_reach/app/rvt/native/`` -- where :mod:`in_reach.app.rvt.rvt_bridge` looks for them. The module is
built for *this* interpreter (``cp314`` for Python 3.14), so run it with the Python you'll run in-reach with.
CI (``.github/workflows/native.yml``) calls exactly this script, so a local build and a released one can't
drift apart.

Needs: Windows, CMake, Visual Studio 2022's C++ tools, `vcpkg <https://vcpkg.io>`_ with ``qt5-base:x64-windows``
installed, and ``pip install pybind11`` in the interpreter running this. See ``native/README.md``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

NATIVE_DIR = Path(__file__).resolve().parent
DEFAULT_DEST = NATIVE_DIR.parent / "src" / "in_reach" / "app" / "rvt" / "native"
#: Kept between runs (git-ignored), so a second build is incremental. Deliberately not a temporary directory:
#: MSBuild leaves helper processes holding handles on its build tree for a while after the build, so deleting
#: one straight afterwards fails on Windows -- which failed CI with a finished, installed build. One
#: subdirectory per Python version (``build/cp312``, ...): CMake caches the Python libraries it found, so
#: building for a second interpreter into the same tree would quietly reuse the first one's.
BUILD_ROOT = NATIVE_DIR / "build"
#: What's next to the built module that it needs at runtime -- vcpkg copies these beside it.
_RUNTIME_DLL_PATTERNS = ("*.dll",)
#: Qt reads this next to Qt5Core.dll; an empty [Paths] section stops it searching for a Qt install.
_QT_CONF = "[Paths]\n"


def _run(command: list[str]) -> None:
    print("+", " ".join(str(part) for part in command), flush=True)
    subprocess.run(command, check=True)


def python_tag() -> str:
    """``cp312`` for Python 3.12 -- what the built module's filename must carry to load in this interpreter."""
    return f"cp{sys.version_info.major}{sys.version_info.minor}"


def _require_pybind11() -> None:
    try:
        import pybind11  # noqa: F401
    except ImportError:
        sys.exit("pybind11 isn't installed in this interpreter -- run: python -m pip install pybind11")


def build(vcpkg_root: Path, build_dir: Path, dest: Path, *, jobs: int, tag: str | None = None) -> Path:
    """Builds the module for *this* interpreter and installs it into ``dest``. Returns the installed path.

    ``tag`` is the ``cpXY`` the built module must carry (default: this interpreter's, see
    :func:`python_tag`); anything else is refused rather than installed.
    """
    tag = tag or python_tag()
    python = Path(sys.executable).as_posix()
    toolchain = vcpkg_root / "scripts" / "buildsystems" / "vcpkg.cmake"
    if not toolchain.is_file():
        sys.exit(f"no vcpkg toolchain at {toolchain} -- pass --vcpkg-root or set VCPKG_ROOT")

    _run(
        [
            "cmake", "-S", str(NATIVE_DIR), "-B", str(build_dir),
            "-G", "Visual Studio 17 2022", "-A", "x64",
            f"-DCMAKE_TOOLCHAIN_FILE={toolchain.as_posix()}",
            "-DVCPKG_TARGET_TRIPLET=x64-windows",
            # Every spelling, because which one counts depends on how pybind11 was told to find Python (the legacy
            # finder reads PYTHON_EXECUTABLE, FindPython reads Python_/Python3_EXECUTABLE). Left out, CMake falls
            # back to the first `python` on PATH -- and silently builds for the wrong interpreter whenever that
            # isn't this one.
            f"-DPYTHON_EXECUTABLE={python}",
            f"-DPython_EXECUTABLE={python}",
            f"-DPython3_EXECUTABLE={python}",
        ]
    )
    _run(["cmake", "--build", str(build_dir), "--config", "Release", "--parallel", str(jobs)])

    release_dir = build_dir / "Release"
    modules = sorted(release_dir.glob("_reachvarianttool*.pyd"))
    if len(modules) != 1:
        sys.exit(f"expected exactly one built module in {release_dir}, found {[m.name for m in modules]}")
    if f".{tag}-" not in modules[0].name:
        sys.exit(
            f"built {modules[0].name}, but this interpreter is {tag} and can't load it -- CMake used a different "
            f"Python; delete {build_dir} and check which python it found"
        )

    dest.mkdir(parents=True, exist_ok=True)
    for stale in dest.glob("_reachvarianttool*.pyd"):
        stale.unlink()  # an old build for another Python version would otherwise sit beside the new one
    installed = dest / modules[0].name
    shutil.copy2(modules[0], installed)
    for pattern in _RUNTIME_DLL_PATTERNS:
        for dll in release_dir.glob(pattern):
            shutil.copy2(dll, dest / dll.name)
    (dest / "qt.conf").write_text(_QT_CONF, encoding="utf-8")
    return installed


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--vcpkg-root", type=Path, default=Path(os.environ.get("VCPKG_ROOT", "C:/vcpkg")))
    parser.add_argument("--build-dir", type=Path, default=None, help=f"default: {BUILD_ROOT}/<cpXY>")
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST, help=f"default: {DEFAULT_DEST}")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    args = parser.parse_args(argv)

    if sys.platform != "win32":
        sys.exit("_reachvarianttool only builds on Windows (MSVC, and in-reach itself targets Windows)")
    _require_pybind11()

    build_dir = args.build_dir if args.build_dir is not None else BUILD_ROOT / python_tag()
    installed = build(args.vcpkg_root, build_dir, args.dest, jobs=args.jobs)
    print(f"installed {installed}")


if __name__ == "__main__":
    main()
