from pathlib import Path

import pytest

from in_reach.app import env_file, recent


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


def test_recent_starts_empty(project_dir: Path) -> None:
    assert recent.list_recent(project_dir) == []


def test_add_recent_puts_the_newest_first(project_dir: Path, tmp_path: Path) -> None:
    first, second = _make_projects(tmp_path, 2)

    recent.add_recent(project_dir, first)
    recent.add_recent(project_dir, second)

    assert recent.list_recent(project_dir) == [second, first]


def test_re_adding_a_project_moves_it_to_the_front_without_duplicating(
    project_dir: Path, tmp_path: Path
) -> None:
    first, second = _make_projects(tmp_path, 2)
    recent.add_recent(project_dir, first)
    recent.add_recent(project_dir, second)

    recent.add_recent(project_dir, first)

    assert recent.list_recent(project_dir) == [first, second]


def test_recent_is_capped(project_dir: Path, tmp_path: Path) -> None:
    folders = _make_projects(tmp_path, recent.MAX_RECENT + 3)
    for folder in folders:
        recent.add_recent(project_dir, folder)

    entries = recent.list_recent(project_dir)
    assert len(entries) == recent.MAX_RECENT
    assert entries[0] == folders[-1]


def test_folders_that_no_longer_exist_are_filtered_out_but_not_forgotten(
    project_dir: Path, tmp_path: Path
) -> None:
    kept, gone = _make_projects(tmp_path, 2)
    recent.add_recent(project_dir, kept)
    recent.add_recent(project_dir, gone)
    gone.rmdir()

    assert recent.list_recent(project_dir) == [kept]
    # A drive that simply isn't mounted right now shouldn't lose the entry for good.
    assert str(gone) in env_file.get_env_values(project_dir / ".env")[recent.RECENT_KEY]
