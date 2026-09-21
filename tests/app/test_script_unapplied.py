"""When a linked script project has changes Apply hasn't built (``apply_settings.script_has_unapplied_changes``)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "script_project"))
from hill_project import hill_rush  # noqa: E402

from in_reach.app import apply_settings, new_project  # noqa: E402
from in_reach.app.script_project import link  # noqa: E402


def _built(folder: Path) -> None:
    """Pretend an Apply just built ``folder``: link it and drop a ``.bin`` newer than everything."""
    assert link(folder).ok
    binary = new_project.compiled_variant_path(folder)
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"bin")
    later = (folder / "build" / "Compiled.txt").stat().st_mtime_ns + 1_000_000
    os.utime(binary, ns=(later, later))


def test_a_single_file_project_is_never_reported_by_this_check(tmp_path: Path) -> None:
    (tmp_path / "script").mkdir()
    (tmp_path / "script" / "output.txt").write_text("x = 1\n", encoding="utf-8")

    assert apply_settings.script_has_unapplied_changes(tmp_path) is False


def test_a_linked_project_nothing_has_built_is_unapplied(tmp_path: Path) -> None:
    hill_rush(tmp_path)

    assert apply_settings.script_has_unapplied_changes(tmp_path) is True


def test_a_freshly_built_linked_project_has_nothing_to_apply(tmp_path: Path) -> None:
    hill_rush(tmp_path)
    _built(tmp_path)

    assert apply_settings.script_has_unapplied_changes(tmp_path) is False


def test_editing_a_module_makes_it_unapplied_again(tmp_path: Path) -> None:
    hill_rush(tmp_path)
    _built(tmp_path)

    (tmp_path / "script" / "blocks" / "setup.mgl").write_text(
        "-- @number g_phase priority=low\non init: do\n   g_phase = 9\nend\n", encoding="utf-8"
    )

    assert apply_settings.script_has_unapplied_changes(tmp_path) is True


def test_a_link_that_now_fails_is_unapplied_so_apply_can_say_why(tmp_path: Path) -> None:
    hill_rush(tmp_path)
    _built(tmp_path)

    (tmp_path / "script" / "project.toml").write_text("[project\n", encoding="utf-8")

    assert apply_settings.script_has_unapplied_changes(tmp_path) is True


def test_a_link_the_last_build_never_finished_is_unapplied(tmp_path: Path) -> None:
    """``Compiled.txt`` was written (the link succeeded) but the compile after it failed: the ``.bin`` is older."""
    hill_rush(tmp_path)
    _built(tmp_path)
    compiled = tmp_path / "build" / "Compiled.txt"
    binary = new_project.compiled_variant_path(tmp_path)
    older = compiled.stat().st_mtime_ns - 5_000_000_000
    os.utime(binary, ns=(older, older))

    assert apply_settings.script_has_unapplied_changes(tmp_path) is True


def test_a_declared_resource_the_settings_lack_is_unapplied(tmp_path: Path) -> None:
    hill_rush(tmp_path)
    _built(tmp_path)
    (tmp_path / "settings" / "script_settings.json").unlink()

    assert apply_settings.script_has_unapplied_changes(tmp_path) is True
