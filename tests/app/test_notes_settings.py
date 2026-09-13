from pathlib import Path

import pytest

from in_reach.app import notes_settings


@pytest.fixture
def env_path(tmp_path: Path) -> Path:
    project_dir = tmp_path / ".in-reach"
    project_dir.mkdir()
    path = project_dir / ".env"
    path.write_text("", encoding="utf-8")
    return path


def test_get_notes_format_defaults_to_txt(env_path: Path) -> None:
    assert notes_settings.get_notes_format(env_path) == notes_settings.FORMAT_TXT


def test_get_notes_format_defaults_for_an_unrecognized_value(env_path: Path) -> None:
    from in_reach.app import env_file

    env_file.update_env_value(env_path, notes_settings.NOTES_FORMAT_KEY, "rtf")

    assert notes_settings.get_notes_format(env_path) == notes_settings.FORMAT_TXT


def test_set_notes_format_round_trips_through_get(env_path: Path) -> None:
    notes_settings.set_notes_format(env_path, notes_settings.FORMAT_MD)

    assert notes_settings.get_notes_format(env_path) == notes_settings.FORMAT_MD


def test_set_notes_format_rejects_an_unknown_value(env_path: Path) -> None:
    with pytest.raises(ValueError):
        notes_settings.set_notes_format(env_path, "rtf")


def test_notes_filename_matches_the_format() -> None:
    assert notes_settings.notes_filename(notes_settings.FORMAT_TXT) == "Notes.txt"
    assert notes_settings.notes_filename(notes_settings.FORMAT_MD) == "Notes.md"


def test_ensure_notes_file_creates_a_missing_md_file(tmp_path: Path) -> None:
    from in_reach.app import new_project

    path = notes_settings.ensure_notes_file(tmp_path, notes_settings.FORMAT_MD)

    assert path == tmp_path / "Notes.md"
    assert path.read_text(encoding="utf-8") == new_project.NOTES_TEMPLATE


def test_ensure_notes_file_never_touches_an_already_existing_file(tmp_path: Path) -> None:
    (tmp_path / "Notes.txt").write_text("my own notes\n", encoding="utf-8")

    path = notes_settings.ensure_notes_file(tmp_path, notes_settings.FORMAT_TXT)

    assert path.read_text(encoding="utf-8") == "my own notes\n"
