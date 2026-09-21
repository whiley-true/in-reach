"""The layering this package keeps: the library and CLI never import a GUI, and importing the script tooling never loads the
native extension. The IDE is a separate package (``in-reach-ide``) that depends on this one, not the other way round."""
import subprocess
import sys
import textwrap


def _run(code: str) -> str:
    result = subprocess.run([sys.executable, "-c", textwrap.dedent(code)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_importing_the_api_and_cli_loads_no_qt_and_no_native_module() -> None:
    loaded = _run(
        """
        import sys
        import in_reach.api, in_reach.cli
        print(sorted(m for m in sys.modules if m.split('.')[0] in ('PyQt6', 'PyQt5', 'PySide6', '_reachvarianttool')))
        """
    )

    assert loaded == "[]"


def test_importing_the_script_tooling_never_loads_the_native_extension() -> None:
    loaded = _run(
        """
        import sys
        import in_reach.app.script_project, in_reach.app.rvt.megalo_ast, in_reach.app.script_preprocess
        print([m for m in sys.modules if '_reachvarianttool' in m])
        """
    )

    assert loaded == "[]"


def test_no_module_of_the_library_imports_a_gui() -> None:
    offenders = _run(
        """
        import importlib, pkgutil, sys
        import in_reach
        for info in pkgutil.walk_packages(in_reach.__path__, 'in_reach.'):
            try:
                importlib.import_module(info.name)
            except ImportError:
                pass  # e.g. an optional native piece; only a GUI import matters here
        print(sorted(m for m in sys.modules if m.split('.')[0] in ('PyQt6', 'PyQt5', 'PySide6')))
        """
    )

    assert offenders == "[]"


def test_the_library_does_not_import_the_ide_package() -> None:
    import pathlib
    import re

    source = pathlib.Path(__file__).parents[1] / "src" / "in_reach"
    pattern = re.compile(r"^\s*(?:from|import)\s+in_reach_ide\b", re.M)
    offenders = [
        p.relative_to(source).as_posix() for p in source.rglob("*.py") if pattern.search(p.read_text(encoding="utf-8"))
    ]

    assert offenders == []  # cli.py reaches it through importlib, by name, only when asked to run it


# -- system detection belongs to within-reach ---------------------------------------------------------------------------


def test_this_package_has_no_copy_of_the_system_detection() -> None:
    import importlib.util

    assert importlib.util.find_spec("in_reach.app.system_verify") is None
    assert importlib.util.find_spec("in_reach.app.vdf") is None  # only the detection ever read Steam's config files


def test_the_dependency_on_within_reach_is_declared() -> None:
    import pathlib

    pyproject = (pathlib.Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")

    assert '"within-reach>=0.2.0,<0.3"' in pyproject


def test_verify_reports_what_within_reach_says_is_verified(tmp_path, monkeypatch) -> None:
    import json

    from click.testing import CliRunner
    from within_reach import system_verify

    from in_reach.cli import main

    monkeypatch.setattr(system_verify, "verified_keys", lambda project_dir: {"STEAM_INSTALL_LOC": True, "TESSERACT_LOC": False})

    result = CliRunner().invoke(main, ["verify", "--root", str(tmp_path), "--format", "json"])

    assert json.loads(result.output)["verified"] == {"STEAM_INSTALL_LOC": True, "TESSERACT_LOC": False}
