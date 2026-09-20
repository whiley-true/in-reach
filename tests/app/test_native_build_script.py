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

    # Not a TemporaryDirectory (nothing is deleted afterwards), and one per Python version: CMake caches the
    # Python libraries it found, so a second interpreter must not reuse the first one's tree.
    assert used == [_REPO / "native" / "build" / build_script.python_tag()]
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

    installed = build_script.build(vcpkg_root, tmp_path / "b", tmp_path / "dest", jobs=1, tag="cp312")

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

    build_script.build(vcpkg_root, tmp_path / "b", dest, jobs=1, tag="cp312")

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
        build_script.build(vcpkg_root, tmp_path / "b", tmp_path / "dest", jobs=1, tag="cp312")

    assert not (tmp_path / "dest").exists()  # nothing half-installed


def test_it_refuses_a_module_built_for_a_different_python(build_script, vcpkg_root: Path, tmp_path: Path) -> None:
    """Building under 3.12 with CMake finding the 3.14 on PATH used to install a cp314 module without complaint,
    which then simply failed to load."""
    _fake_build_output(tmp_path / "b", "_reachvarianttool.cp314-win_amd64.pyd")
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "_reachvarianttool.cp312-win_amd64.pyd").write_bytes(b"a working module")

    with pytest.raises(SystemExit, match="this interpreter is cp312 and can't load it"):
        build_script.build(vcpkg_root, tmp_path / "b", dest, jobs=1, tag="cp312")

    assert [p.name for p in dest.iterdir()] == ["_reachvarianttool.cp312-win_amd64.pyd"]  # what was there is kept


def test_it_tells_cmake_which_python_by_every_name_it_answers_to(
    build_script, vcpkg_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = []
    monkeypatch.setattr(build_script, "_run", commands.append)
    _fake_build_output(tmp_path / "b", "_reachvarianttool.cp312-win_amd64.pyd")

    build_script.build(vcpkg_root, tmp_path / "b", tmp_path / "dest", jobs=1, tag="cp312")

    configure = next(command for command in commands if command[:1] == ["cmake"] and "-S" in command)
    me = Path(build_script.sys.executable).as_posix()
    for variable in ("PYTHON_EXECUTABLE", "Python_EXECUTABLE", "Python3_EXECUTABLE"):
        assert f"-D{variable}={me}" in configure


def test_the_tag_is_this_interpreters(build_script) -> None:
    assert build_script.python_tag() == f"cp{build_script.sys.version_info.major}{build_script.sys.version_info.minor}"


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


# -- native/verify.py -------------------------------------------------------------------------------------
# CI's first check of the module it had just built was a one-liner that imported `_reachvarianttool` before
# rvt_bridge had put its folder on sys.path, so it failed on a perfectly good build.


@pytest.fixture
def verify_script():
    spec = importlib.util.spec_from_file_location("rvt_native_verify", _REPO / "native" / "verify.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_verify_accepts_the_module_installed_in_the_package(verify_script, monkeypatch, capsys) -> None:
    fake = type("Module", (), {"__file__": str(verify_script.INSTALL_DIR / "_reachvarianttool.cp312-win_amd64.pyd")})
    monkeypatch.setattr("in_reach.app.rvt.rvt_bridge.get_rvt", lambda: fake)

    assert verify_script.main() == 0
    assert "_reachvarianttool.cp312-win_amd64.pyd" in capsys.readouterr().out


def test_verify_fails_and_says_why_when_the_module_does_not_load(verify_script, monkeypatch, capsys) -> None:
    def broken():
        raise ImportError("DLL load failed while importing _reachvarianttool")

    monkeypatch.setattr("in_reach.app.rvt.rvt_bridge.get_rvt", broken)

    assert verify_script.main() == 1
    err = capsys.readouterr().err
    assert "DLL load failed" in err  # the real reason, not just "unavailable"
    assert "did not load" in err


def test_verify_fails_when_a_different_copy_of_the_module_was_loaded(verify_script, monkeypatch, tmp_path, capsys) -> None:
    """E.g. a regular install in site-packages: the tests would run against that instead of the build."""
    fake = type("Module", (), {"__file__": str(tmp_path / "site-packages" / "_reachvarianttool.cp312-win_amd64.pyd")})
    monkeypatch.setattr("in_reach.app.rvt.rvt_bridge.get_rvt", lambda: fake)

    assert verify_script.main() == 1
    assert "not the module build.py installed" in capsys.readouterr().err


@pytest.mark.skipif(
    not __import__("in_reach.app.rvt.rvt_bridge", fromlist=["x"]).is_available(),
    reason="native _reachvarianttool extension not available on this platform",
)
def test_verify_passes_against_the_real_module(verify_script, capsys) -> None:
    assert verify_script.main() == 0
    assert capsys.readouterr().out.strip().endswith(".pyd")


def test_the_workflow_runs_verify_between_the_build_and_the_tests() -> None:
    steps = (_REPO / ".github" / "workflows" / "native.yml").read_text(encoding="utf-8")

    assert steps.index("python native/build.py") < steps.index("python native/verify.py") < steps.index("pytest")
    assert "import _reachvarianttool" not in steps  # the one-liner that ran before rvt_bridge set up sys.path
