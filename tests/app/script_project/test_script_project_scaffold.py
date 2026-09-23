"""Creating a script project from a single-file one, and adding modules to it."""
import json
from pathlib import Path

import pytest

from in_reach.app.script_project import create_module, create_project, is_linked, link, load_project

_SCRIPT = "-- my game\non init: do\n   global.number[0] = 1\nend\n"


def _single_file_project(folder: Path, script: str | None = _SCRIPT, title: str = "My Game") -> Path:
    (folder / "settings").mkdir(parents=True)
    (folder / "settings" / "settings.json").write_text(json.dumps({"meta": {"title": title}}), encoding="utf-8")
    (folder / "script").mkdir()
    if script is not None:
        (folder / "script" / "output.txt").write_text(script, encoding="utf-8")
    return folder


def test_creating_a_project_keeps_the_existing_script_as_the_main_block(tmp_path: Path) -> None:
    folder = _single_file_project(tmp_path)

    written = create_project(folder)

    assert [p.relative_to(folder).as_posix() for p in written] == ["script/project.toml", "script/blocks/main.mgl"]
    assert (folder / "script" / "blocks" / "main.mgl").read_text(encoding="utf-8") == _SCRIPT
    assert is_linked(folder)


def test_the_new_project_loads_and_links_to_the_same_script(tmp_path: Path) -> None:
    folder = _single_file_project(tmp_path)
    create_project(folder)

    project = load_project(folder)
    result = link(folder, write=False)

    assert project.diagnostics == [] and project.order == ["MAIN"]
    assert result.ok
    assert "on init: do\n   global.number[0] = 1\nend" in result.compiled


def test_the_project_is_named_after_its_title(tmp_path: Path) -> None:
    folder = _single_file_project(tmp_path, title='The "Best" Game')

    create_project(folder)

    assert load_project(folder).manifest.project.name == 'The "Best" Game'


def test_directives_in_the_old_script_are_kept_as_written(tmp_path: Path) -> None:
    script = "-- @if DEV\nglobal.number[0] = 1\n-- @end\n"
    folder = _single_file_project(tmp_path, script)

    create_project(folder)

    assert (folder / "script" / "blocks" / "main.mgl").read_text(encoding="utf-8") == script


@pytest.mark.parametrize("script", [None, "", "  \n\n"])
def test_a_project_with_no_script_gets_a_starter(tmp_path: Path, script: str | None) -> None:
    folder = _single_file_project(tmp_path, script)

    create_project(folder)

    assert (folder / "script" / "blocks" / "main.mgl").read_text(encoding="utf-8").startswith("-- The project's own script")
    assert load_project(folder).diagnostics == []


def test_creating_a_project_twice_is_refused(tmp_path: Path) -> None:
    folder = _single_file_project(tmp_path)
    create_project(folder)

    with pytest.raises(ValueError, match="already has a script/project.toml"):
        create_project(folder)


def test_a_folder_with_no_script_directory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no script/ folder"):
        create_project(tmp_path)


def test_an_existing_main_block_is_never_overwritten(tmp_path: Path) -> None:
    folder = _single_file_project(tmp_path)
    (folder / "script" / "blocks").mkdir()
    (folder / "script" / "blocks" / "main.mgl").write_text("mine\n", encoding="utf-8")

    with pytest.raises(ValueError, match="already exists"):
        create_project(folder)

    assert (folder / "script" / "blocks" / "main.mgl").read_text(encoding="utf-8") == "mine\n"
    assert not is_linked(folder)


# -- modules --------------------------------------------------------------------------------------------


def test_a_module_gets_a_manifest_a_starter_and_a_place_in_the_project(tmp_path: Path) -> None:
    folder = _single_file_project(tmp_path)
    create_project(folder)

    written = create_module(folder, "hill_score")

    assert [p.relative_to(folder).as_posix() for p in written] == [
        "script/modules/hill_score/module.toml", "script/modules/hill_score/hill_score.mgl", "script/project.toml",
    ]
    project = load_project(folder)
    assert project.diagnostics == [] and [m.name for m in project.modules] == ["hill_score"]
    assert project.modules[0].manifest.module.version == "0.1.0"


def test_the_starter_module_links_cleanly_and_adds_nothing(tmp_path: Path) -> None:
    folder = _single_file_project(tmp_path)
    create_project(folder)
    before = link(folder, write=False).compiled

    create_module(folder, "hill_score")

    assert link(folder, write=False).compiled == before


def test_project_toml_keeps_what_was_already_in_it(tmp_path: Path) -> None:
    folder = _single_file_project(tmp_path)
    create_project(folder)
    toml = folder / "script" / "project.toml"
    toml.write_text(toml.read_text(encoding="utf-8") + "\n# keep me\n[constants]\nX = 1\n", encoding="utf-8")

    create_module(folder, "a")
    create_module(folder, "b")

    text = toml.read_text(encoding="utf-8")
    assert "# keep me" in text and text.count("[[modules]]") == 2
    assert [m.name for m in load_project(folder).modules] == ["a", "b"]


@pytest.mark.parametrize("name", ["", "9lives", "has space", "dash-ed", "a/b", "..", "ünï"])
def test_a_bad_module_name_is_refused_before_anything_is_written(tmp_path: Path, name: str) -> None:
    folder = _single_file_project(tmp_path)
    create_project(folder)

    with pytest.raises(ValueError, match="valid module name"):
        create_module(folder, name)

    assert not (folder / "script" / "modules").exists()


def test_an_existing_module_is_refused(tmp_path: Path) -> None:
    folder = _single_file_project(tmp_path)
    create_project(folder)
    create_module(folder, "a")

    with pytest.raises(ValueError, match="already exists"):
        create_module(folder, "a")


def test_a_module_needs_a_script_project_first(tmp_path: Path) -> None:
    folder = _single_file_project(tmp_path)

    with pytest.raises(ValueError, match="no script/project.toml"):
        create_module(folder, "a")


# -- a backup before converting -----------------------------------------------------------------------------


def test_backup_script_copies_script_outside_the_project(tmp_path: Path) -> None:
    from in_reach import api

    folder = tmp_path / "game"
    (folder / "script" / "env").mkdir(parents=True)
    (folder / "script" / "output.txt").write_text("x = 1\n", encoding="utf-8")
    (folder / "script" / "env" / "dev.env").write_text("FLAGS=DEV\n", encoding="utf-8")

    first = api.backup_script(folder)
    second = api.backup_script(folder)

    assert first.parent == tmp_path / ".in-reach" / "backups" / "game" and first.name.startswith("script-")
    assert (first / "output.txt").read_text(encoding="utf-8") == "x = 1\n" and (first / "env" / "dev.env").is_file()
    assert second != first  # two in the same second don't collide


def test_create_project_with_backup_reports_where_the_copy_went(tmp_path: Path) -> None:
    import json

    from click.testing import CliRunner

    from in_reach.cli import main

    folder = tmp_path / "game"
    (folder / "script").mkdir(parents=True)
    (folder / "script" / "output.txt").write_text("x = 1\n", encoding="utf-8")

    result = CliRunner().invoke(main, ["create-project", str(folder), "--backup", "--format", "json"])

    data = json.loads(result.output)
    assert result.exit_code == 0 and Path(data["backup"]).is_dir() and (folder / "script" / "project.toml").is_file()
