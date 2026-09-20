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
