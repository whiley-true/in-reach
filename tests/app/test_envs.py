"""Envs (``script/env/<name>.env``, once called profiles): creating and removing them, what ``api.envs`` reports, the
``in-reach env`` commands, and reading a project written before the rename."""
import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from in_reach import api
from in_reach.app import script_preprocess
from in_reach.app.script_project import load_project
from in_reach.cli import main

sys.path.insert(0, str(Path(__file__).parent / "script_project"))
from hill_project import PROJECT_TOML, hill_rush  # noqa: E402


def _folder(tmp_path: Path) -> Path:
    env = tmp_path / "script" / "env"
    env.mkdir(parents=True)
    (tmp_path / "script" / "output.mgl").write_text("game.end_round()\n", encoding="utf-8")
    (env / "dev.env").write_text("FLAGS=DEV,FAST\nSCORE=5\n", encoding="utf-8")
    return tmp_path


def test_a_new_env_is_empty_with_the_explanatory_header(tmp_path: Path) -> None:
    folder = _folder(tmp_path)

    path = script_preprocess.create_env(folder, "qa")

    env = script_preprocess.load_env(folder, "qa")
    assert path.name == "qa.env" and env.flags == frozenset() and env.constants == {}
    assert path.read_text(encoding="utf-8").startswith('# Env "qa"')
    assert script_preprocess.active_env_name(folder) is None  # adding one doesn't choose it


def test_a_new_env_can_start_as_a_copy(tmp_path: Path) -> None:
    folder = _folder(tmp_path)
    script_preprocess.create_env(folder, "dev2", copy_from="dev")
    assert script_preprocess.load_env(folder, "dev2").constants == {"SCORE": "5"}


@pytest.mark.parametrize("name", ["dev", "has space", "", "../up"])
def test_a_taken_or_unusable_name_is_refused(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError):
        script_preprocess.create_env(_folder(tmp_path), name)


def test_deleting_the_active_env_leaves_none_active(tmp_path: Path) -> None:
    folder = _folder(tmp_path)
    script_preprocess.set_active_env(folder, "dev")

    script_preprocess.delete_env(folder, "dev")

    assert script_preprocess.list_envs(folder) == [] and script_preprocess.active_env_name(folder) is None


def test_api_envs_reports_each_envs_flags_constants_or_error(tmp_path: Path) -> None:
    folder = _folder(tmp_path)
    (folder / "script" / "env" / "broken.env").write_text("SCORE=oops oops\n", encoding="utf-8")
    api.set_env(folder, "dev")

    info = api.envs(folder)

    assert info.names == ["broken", "dev"] and info.active == "dev"
    broken, dev = info.details
    assert broken.error.startswith("line 1:") and broken.flags == []
    assert (dev.flags, dev.constants, dev.path) == (["DEV", "FAST"], {"SCORE": "5"}, "script/env/dev.env")
    assert info.to_dict()["details"][1]["constants"] == {"SCORE": "5"}


def test_api_new_and_delete_env_raise_api_errors(tmp_path: Path) -> None:
    folder = _folder(tmp_path)
    assert "qa" in api.new_env(folder, "qa").names
    with pytest.raises(api.ApiError):
        api.new_env(folder, "qa")
    assert "qa" not in api.delete_env(folder, "qa").names
    with pytest.raises(api.ApiError):
        api.delete_env(folder, "qa")


def test_the_env_commands(tmp_path: Path) -> None:
    folder = _folder(tmp_path)
    runner = CliRunner()

    added = runner.invoke(main, ["env", "new", "qa", "--copy-from", "dev", "--folder", str(folder)])
    chosen = runner.invoke(main, ["env", "set", "qa", "--folder", str(folder)])
    listed = runner.invoke(main, ["env", "list", str(folder)])
    data = json.loads(runner.invoke(main, ["env", "list", str(folder), "--format", "json"]).output)
    removed = runner.invoke(main, ["env", "delete", "qa", "--folder", str(folder)])

    assert added.exit_code == 0 and chosen.exit_code == 0 and removed.exit_code == 0
    assert "* qa  flags=DEV,FAST  SCORE=5" in listed.output
    assert data["active"] == "qa" and data["schema"] == api.SCHEMA_VERSION
    assert script_preprocess.list_envs(folder) == ["dev"]


# -- projects from before the rename ------------------------------------------------------------------------


def test_an_old_active_profile_txt_is_still_read_and_is_replaced_by_the_next_choice(tmp_path: Path) -> None:
    folder = _folder(tmp_path)
    legacy = folder / "script" / "env" / "active_profile.txt"
    legacy.write_text("dev\n", encoding="utf-8")

    assert script_preprocess.active_env_name(folder) == "dev"
    script_preprocess.set_active_env(folder, "dev")

    assert not legacy.exists() and (folder / "script" / "env" / "active_env.txt").read_text(encoding="utf-8") == "dev\n"


def test_an_old_profile_key_in_project_toml_still_works_with_a_warning(tmp_path: Path) -> None:
    folder = hill_rush(tmp_path, project_dot_toml=PROJECT_TOML.replace('env = "dev"', 'profile = "dev"'))

    project = load_project(folder)

    assert project.env is not None and project.env.name == "dev"
    [warning] = [d for d in project.diagnostics if d.code == "env-key-renamed"]
    assert (warning.severity, warning.line) == ("warning", 3)


def test_what_a_new_env_file_explains_is_what_the_preprocessor_does() -> None:
    """The header of every env file teaches FLAGS and NAME=value by example; the examples must be true."""
    from in_reach.app import new_project

    header = new_project.env_file_text("x")
    assert "if current_player.score >= ${SCORE_TO_WIN} then" in header
    assert "is built as:  if current_player.score >= 5 then" in header
    with_value = script_preprocess.Env("x", frozenset(), {"SCORE_TO_WIN": "5"})
    assert script_preprocess.preprocess("if current_player.score >= ${SCORE_TO_WIN} then\n", with_value) == (
        "if current_player.score >= 5 then\n"
    )
    block = "-- @if DEV\ncurrent_player.score += 10\n-- @end\n"
    assert "current_player.score += 10" in script_preprocess.preprocess(block, script_preprocess.Env("x", frozenset({"DEV"})))
    assert "current_player.score += 10" not in script_preprocess.preprocess(block, script_preprocess.Env("x"))
    notes = new_project._ENV_HEADER.format(name="x")
    assert all(line.startswith("#") or not line.strip() for line in notes.splitlines())  # the explanation takes no effect


def test_a_copied_envs_header_names_the_copy(tmp_path: Path) -> None:
    from in_reach.app import new_project

    (tmp_path / "script" / "env").mkdir(parents=True)
    (tmp_path / "script" / "env" / "development.env").write_text(new_project.env_file_text("development", "\nFLAGS=DEV\n"), encoding="utf-8")

    script_preprocess.create_env(tmp_path, "release", copy_from="development")

    text = (tmp_path / "script" / "env" / "release.env").read_text(encoding="utf-8")
    assert text.startswith('# Env "release"') and "FLAGS=DEV" in text
