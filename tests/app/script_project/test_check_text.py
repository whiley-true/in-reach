"""``api.check_text``: an editor's unsaved buffer checked in place of its file, for problems as you type."""
from pathlib import Path

import pytest
from hill_project import hill_rush

from in_reach import api


def _single(tmp_path: Path, text: str = "game.end_round()\n") -> Path:
    (tmp_path / "script").mkdir()
    (tmp_path / "script" / "output.mgl").write_text(text, encoding="utf-8")
    return tmp_path


def test_a_single_files_buffer_is_checked_instead_of_what_is_saved(tmp_path: Path) -> None:
    folder = _single(tmp_path)

    result = api.check_text(folder, "output.mgl", "declare global.number[0]\ndeclare global.number[0]\n")

    assert not result.ok and [(d.code, d.file, d.line) for d in result.errors] == [("IR006", "output.mgl", 2)]
    assert api.check(folder).ok  # the file on disk is still fine
    assert not (folder / "build").exists()


def test_an_absolute_path_inside_script_is_accepted(tmp_path: Path) -> None:
    folder = _single(tmp_path)

    result = api.check_text(folder, folder / "script" / "output.mgl", "x = true\n")

    assert [d.code for d in result.diagnostics] == ["IR007"]


def test_a_path_outside_script_is_refused(tmp_path: Path) -> None:
    folder = _single(tmp_path)
    with pytest.raises(api.ApiError):
        api.check_text(folder, tmp_path.parent / "elsewhere.txt", "")


def test_a_block_buffer_in_a_script_project_is_checked_with_the_rest_of_the_project(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path)
    assert api.check(folder).ok

    result = api.check_text(folder, "blocks/setup.mgl", "-- @number t_hill_buff\n")

    [clash] = result.errors
    assert clash.code == "IR006" and clash.file in ("blocks/setup.mgl", "modules/hill_buff/hill_buff.mgl")


def test_a_manifest_buffer_is_read_too(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path)
    toml = (folder / "script" / "project.toml").read_text(encoding="utf-8")

    result = api.check_text(folder, "project.toml", toml.replace('name = "hill_buff"', 'name = "no_such_module"'))

    assert "module-missing" in [d.code for d in result.errors]


def test_an_env_buffer_is_checked_on_its_own(tmp_path: Path) -> None:
    folder = _single(tmp_path)

    bad = api.check_text(folder, "env/dev.env", "FLAGS=DEV\nSCORE=oops oops\n")
    good = api.check_text(folder, "env/dev.env", "FLAGS=DEV\nSCORE=5\n")

    assert [(d.code, d.file, d.line) for d in bad.diagnostics] == [("env-invalid", "env/dev.env", 2)]
    assert good.ok and good.diagnostics == []
