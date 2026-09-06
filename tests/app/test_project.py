from pathlib import Path

import pytest

from in_reach.app import project


def test_get_project_dir_defaults_to_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert project.get_project_dir() == tmp_path / ".in-reach"


def test_get_project_dir_uses_the_given_root(tmp_path: Path) -> None:
    assert project.get_project_dir(tmp_path) == tmp_path / ".in-reach"


def test_project_exists_is_false_until_created(tmp_path: Path) -> None:
    assert project.project_exists(tmp_path) is False

    project.create_project(tmp_path)

    assert project.project_exists(tmp_path) is True


def test_create_project_copies_the_template_and_renames_example_env(tmp_path: Path) -> None:
    project_dir = project.create_project(tmp_path)

    assert project_dir == tmp_path / ".in-reach"
    assert project_dir.is_dir()
    assert (project_dir / ".env").is_file()
    assert not (project_dir / "example.env").exists()


def test_create_project_raises_if_already_exists(tmp_path: Path) -> None:
    project.create_project(tmp_path)

    with pytest.raises(FileExistsError):
        project.create_project(tmp_path)


def test_ensure_gitignore_writes_a_bare_wildcard_if_missing(tmp_path: Path) -> None:
    project_dir = project.create_project(tmp_path)
    gitignore_path = project_dir / ".gitignore"
    gitignore_path.unlink(missing_ok=True)

    project.ensure_gitignore(project_dir)

    assert gitignore_path.read_text() == "*\n"


def test_ensure_gitignore_leaves_an_existing_file_untouched(tmp_path: Path) -> None:
    project_dir = project.create_project(tmp_path)
    gitignore_path = project_dir / ".gitignore"
    gitignore_path.write_text("custom content\n")

    project.ensure_gitignore(project_dir)

    assert gitignore_path.read_text() == "custom content\n"
