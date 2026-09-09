from pathlib import Path

import pytest

from in_reach.app import env_file, open_projects


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    project = tmp_path / ".in-reach"
    project.mkdir()
    (project / ".env").write_text("", encoding="utf-8")
    return project


def _make_projects(tmp_path: Path, count: int) -> list[Path]:
    folders = [tmp_path / f"Project{i}" for i in range(count)]
    for folder in folders:
        folder.mkdir()
    return folders


def test_list_open_starts_empty(project_dir: Path) -> None:
    assert open_projects.list_open(project_dir) == []


def test_set_open_round_trips_in_order(project_dir: Path, tmp_path: Path) -> None:
    first, second, third = _make_projects(tmp_path, 3)

    open_projects.set_open(project_dir, [first, second, third])

    assert open_projects.list_open(project_dir) == [first, second, third]


def test_set_open_overwrites_the_previous_list(project_dir: Path, tmp_path: Path) -> None:
    first, second = _make_projects(tmp_path, 2)
    open_projects.set_open(project_dir, [first, second])

    open_projects.set_open(project_dir, [second])

    assert open_projects.list_open(project_dir) == [second]


def test_set_open_with_an_empty_list_clears_it(project_dir: Path, tmp_path: Path) -> None:
    (folder,) = _make_projects(tmp_path, 1)
    open_projects.set_open(project_dir, [folder])

    open_projects.set_open(project_dir, [])

    assert open_projects.list_open(project_dir) == []


def test_folders_that_no_longer_exist_are_filtered_out_but_not_forgotten(
    project_dir: Path, tmp_path: Path
) -> None:
    kept, gone = _make_projects(tmp_path, 2)
    open_projects.set_open(project_dir, [kept, gone])
    gone.rmdir()

    assert open_projects.list_open(project_dir) == [kept]
    # A drive that simply isn't mounted right now shouldn't lose the entry for good.
    assert str(gone) in env_file.get_env_values(project_dir / ".env")[open_projects.OPEN_PROJECTS_KEY]
