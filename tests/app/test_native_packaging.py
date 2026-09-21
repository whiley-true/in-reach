"""What is committed and what ships: no built native module in git, only this Python's module in a wheel, no sdist binaries,
and no more of the bundled ReachVariantTool than it loads."""
import importlib.util
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).parents[2]


def _load_setup():
    spec = importlib.util.spec_from_file_location("in_reach_setup_under_test", _ROOT / "setup.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # not run as __main__, so this builds nothing
    return module


def _tracked(pathspec: str) -> list[str]:
    if shutil.which("git") is None or not (_ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    result = subprocess.run(["git", "-C", str(_ROOT), "ls-files", "--", pathspec], capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip(f"git can't read this checkout: {result.stderr.strip()}")
    return result.stdout.split()


# -- the wheel carries only the running Python's module -------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "other"),
    [
        ("_reachvarianttool.cp312-win_amd64.pyd", True),
        ("_reachvarianttool.cp313-win_amd64.pyd", True),
        ("_reachvarianttool.cp314-win_amd64.pyd", False),
        ("Qt5Core.dll", False),
        ("qt.conf", False),
        ("z.dll", False),
        ("in_reach/app/rvt/native/_reachvarianttool.cp312-win_amd64.pyd", True),
        ("in_reach\\app\\rvt\\native\\_reachvarianttool.cp314-win_amd64.pyd", False),
    ],
)
def test_only_another_pythons_extension_is_left_out(name: str, other: bool) -> None:
    setup_module = _load_setup()

    assert setup_module.is_module_for_another_python(name, SimpleNamespace(major=3, minor=14)) is other


def test_the_running_python_is_the_default() -> None:
    import sys

    setup_module = _load_setup()
    own = f"_reachvarianttool.cp{sys.version_info.major}{sys.version_info.minor}-win_amd64.pyd"

    assert setup_module.is_module_for_another_python(own) is False
    assert setup_module.is_module_for_another_python("_reachvarianttool.cp299-win_amd64.pyd") is True


def test_importing_setup_py_does_not_run_a_build() -> None:
    setup_module = _load_setup()

    assert callable(setup_module.setup) and setup_module.build_py.__name__ == "build_py"


def test_the_wheel_is_still_tagged_for_the_interpreter() -> None:
    assert _load_setup().BinaryDistribution().has_ext_modules() is True


# -- nothing built is committed ---------------------------------------------------------------------------------------


def test_no_built_native_file_is_tracked_by_git() -> None:
    assert _tracked("src/in_reach/app/rvt/native") == []


def test_the_native_folder_is_ignored_and_pruned_from_the_sdist() -> None:
    gitignore = (_ROOT / ".gitignore").read_text(encoding="utf-8")
    manifest = (_ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    assert "/src/in_reach/app/rvt/native/" in gitignore and "!/src/in_reach/app/rvt/native" not in gitignore
    assert "prune src/in_reach/app/rvt/native" in manifest


def test_the_native_sources_are_still_tracked() -> None:
    tracked = _tracked("native")

    assert "native/bindings.cpp" in tracked and "native/CMakeLists.txt" in tracked and "native/build.py" in tracked


# -- the bundled ReachVariantTool ---------------------------------------------------------------------------------------

_BUNDLE = "src/in_reach/app/rvt_tool/bin"
#: What RVT was seen to load on a normal start (its loaded-module list), plus its licences.
_REQUIRED = {
    "ReachVariantTool.exe", "Qt5Core.dll", "Qt5Gui.dll", "Qt5Widgets.dll", "Qt5Svg.dll", "platforms/qwindows.dll",
    "styles/qwindowsvistastyle.dll",
}
#: Present in the upstream release, never loaded: a software OpenGL fallback, the ANGLE/Direct3D pieces and Qt's own
#: translations (~34 MB of the 62). RVT is a QtWidgets application and draws no OpenGL.
_LEFT_OUT = {"opengl32sw.dll", "D3Dcompiler_47.dll", "libEGL.dll", "libGLESv2.dll"}


def _bundled() -> set[str]:
    return {p.relative_to(_ROOT / _BUNDLE).as_posix() for p in (_ROOT / _BUNDLE).rglob("*") if p.is_file()}


def test_the_bundled_rvt_has_what_it_loads() -> None:
    bundled = _bundled()

    assert _REQUIRED <= bundled
    assert any(t.startswith("LICENSES/") for t in bundled)  # the licences of what is redistributed stay


def test_the_bundled_rvt_leaves_out_what_it_never_loads() -> None:
    bundled = _bundled()

    assert not (_LEFT_OUT & bundled) and not any(t.startswith("translations/") for t in bundled)
