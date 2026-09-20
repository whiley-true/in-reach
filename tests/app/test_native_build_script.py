"""``native/build.py``: the script that builds ``_reachvarianttool`` and installs it into the package.

CMake and MSBuild are stubbed out -- what's checked is the script's own logic: where it builds, what it
installs, and what it refuses. Its first CI run built the module fine and then crashed deleting its
temporary build directory (MSBuild still held a handle on it), so the build directory is now a persistent,
git-ignored one; ``test_the_default_build_directory_is_persistent_and_ignored`` keeps it that way.
"""
import importlib.util
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def build_script(monkeypatch: pytest.MonkeyPatch):
    spec = importlib.util.spec_from_file_location("rvt_native_build", _REPO / "native" / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_run", lambda command: None)
    return module


@pytest.fixture
def vcpkg_root(tmp_path: Path) -> Path:
    toolchain = tmp_path / "vcpkg" / "scripts" / "buildsystems" / "vcpkg.cmake"
    toolchain.parent.mkdir(parents=True)
    toolchain.write_text("", encoding="utf-8")
    return tmp_path / "vcpkg"


def _fake_build_output(build_dir: Path, *modules: str, dlls: tuple[str, ...] = ("Qt5Core.dll", "z.dll")) -> None:
    release = build_dir / "Release"
    release.mkdir(parents=True)
    for name in (*modules, *dlls):
        (release / name).write_bytes(b"built")


def test_the_default_build_directory_is_persistent_and_ignored(build_script, monkeypatch: pytest.MonkeyPatch) -> None:
    used = []
    monkeypatch.setattr(build_script, "_require_pybind11", lambda: None)
    monkeypatch.setattr(build_script.sys, "platform", "win32")
    monkeypatch.setattr(build_script, "build", lambda vcpkg_root, build_dir, dest, *, jobs: used.append(build_dir) or dest)

    build_script.main([])

    assert used == [_REPO / "native" / "build"]  # not a TemporaryDirectory: nothing is deleted afterwards
    ignored = (_REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/native/build/" in ignored


def test_a_build_directory_can_be_chosen(build_script, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    used = []
    monkeypatch.setattr(build_script, "_require_pybind11", lambda: None)
    monkeypatch.setattr(build_script.sys, "platform", "win32")
    monkeypatch.setattr(build_script, "build", lambda vcpkg_root, build_dir, dest, *, jobs: used.append(build_dir) or dest)

    build_script.main(["--build-dir", str(tmp_path / "elsewhere")])

    assert used == [tmp_path / "elsewhere"]


def test_it_installs_the_module_the_dlls_and_a_qt_conf(build_script, vcpkg_root: Path, tmp_path: Path) -> None:
    _fake_build_output(tmp_path / "b", "_reachvarianttool.cp312-win_amd64.pyd")

    installed = build_script.build(vcpkg_root, tmp_path / "b", tmp_path / "dest", jobs=1)

    assert installed == tmp_path / "dest" / "_reachvarianttool.cp312-win_amd64.pyd"
    assert sorted(p.name for p in (tmp_path / "dest").iterdir()) == [
        "Qt5Core.dll", "_reachvarianttool.cp312-win_amd64.pyd", "qt.conf", "z.dll",
    ]
    assert (tmp_path / "dest" / "qt.conf").read_text(encoding="utf-8") == "[Paths]\n"


def test_a_module_built_for_another_python_is_removed(build_script, vcpkg_root: Path, tmp_path: Path) -> None:
    """The committed cp314 module would otherwise sit beside a freshly built cp312 one."""
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "_reachvarianttool.cp314-win_amd64.pyd").write_bytes(b"old")
    _fake_build_output(tmp_path / "b", "_reachvarianttool.cp312-win_amd64.pyd")

    build_script.build(vcpkg_root, tmp_path / "b", dest, jobs=1)

    assert [p.name for p in dest.glob("*.pyd")] == ["_reachvarianttool.cp312-win_amd64.pyd"]


@pytest.mark.parametrize(
    "modules",
    [(), ("_reachvarianttool.cp312-win_amd64.pyd", "_reachvarianttool.cp313-win_amd64.pyd")],
    ids=["none built", "ambiguous"],
)
def test_it_refuses_when_there_is_not_exactly_one_built_module(
    build_script, vcpkg_root: Path, tmp_path: Path, modules: tuple[str, ...]
) -> None:
    _fake_build_output(tmp_path / "b", *modules)

    with pytest.raises(SystemExit, match="expected exactly one built module"):
        build_script.build(vcpkg_root, tmp_path / "b", tmp_path / "dest", jobs=1)

    assert not (tmp_path / "dest").exists()  # nothing half-installed


def test_it_needs_a_vcpkg_toolchain(build_script, tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="no vcpkg toolchain"):
        build_script.build(tmp_path / "nowhere", tmp_path / "b", tmp_path / "dest", jobs=1)


def test_it_only_runs_on_windows(build_script, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_script.sys, "platform", "linux")

    with pytest.raises(SystemExit, match="only builds on Windows"):
        build_script.main([])


def test_the_workflow_installs_editable_so_the_tests_import_the_module_it_built() -> None:
    """A regular install put a copy in site-packages (with the committed cp314 module), so on Python
    3.12/3.13 every native test skipped and on 3.14 the committed module was tested instead."""
    workflow = (_REPO / ".github" / "workflows" / "native.yml").read_text(encoding="utf-8")

    assert '-e ".[dev]"' in workflow
    assert "QT_QPA_PLATFORM: offscreen" not in workflow  # the Windows job runs on the real Windows platform
