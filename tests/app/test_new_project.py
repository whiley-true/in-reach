from pathlib import Path

import pytest

from in_reach.app import env_file, new_project
from in_reach.app.categories import EngineCategory, EngineIcon


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    project = tmp_path / ".in-reach"
    project.mkdir()
    (project / ".env").write_text("", encoding="utf-8")
    return project


@pytest.mark.parametrize(
    "title",
    [
        "My Gametype",
        "a",
        "x" * new_project.MAX_TITLE_LENGTH,
        "CONTEST",
        # No longer folder-name rules -- a title can contain anything a Windows folder name
        # couldn't, since it no longer names the project folder (see is_valid_title's docstring).
        "no/slashes needed now",
        "trailing space ",
        "trailing dot.",
        "CON",
    ],
)
def test_valid_titles(title: str) -> None:
    assert new_project.is_valid_title(title) is True


@pytest.mark.parametrize("title", ["", "   ", "x" * (new_project.MAX_TITLE_LENGTH + 1)])
def test_invalid_titles(title: str) -> None:
    assert new_project.is_valid_title(title) is False


def test_create_gametype_project_names_the_folder_with_a_generated_id_not_the_title(
    project_dir: Path, tmp_path: Path
) -> None:
    folder, warning = new_project.create_gametype_project(project_dir, "Slayer Plus", "A better slayer")

    assert warning is None
    assert folder.parent == tmp_path
    assert folder.name != "Slayer Plus"
    assert len(folder.name) == new_project.PROJECT_ID_LENGTH
    assert (folder / "edit" / "settings").is_dir()
    assert (folder / "edit" / "rvt").is_dir()
    assert (folder / "build" / "dist").is_dir()
    assert (folder / "script").is_dir()
    # build/ is regenerated from edit/, so it ignores itself rather than relying on the user's repo.
    assert (folder / "build" / ".gitignore").read_text(encoding="utf-8") == "*\n!.gitignore\n"

    readme = (folder / "README.md").read_text(encoding="utf-8")
    assert "# Slayer Plus" in readme
    assert "A better slayer" in readme
    assert folder.name in readme


def test_create_gametype_project_points_project_dir_at_the_new_folder(project_dir: Path) -> None:
    folder, _warning = new_project.create_gametype_project(project_dir, "Slayer Plus")

    values = env_file.get_env_values(project_dir / ".env")
    assert values[new_project.PROJECT_DIR_KEY] == str(folder)


def test_create_gametype_project_without_a_description_still_writes_a_readme(project_dir: Path) -> None:
    folder, _warning = new_project.create_gametype_project(project_dir, "Blank One")

    assert "_No description._" in (folder / "README.md").read_text(encoding="utf-8")


def test_description_max_length_is_137_and_unrelated_to_windows_naming_rules() -> None:
    assert new_project.MAX_DESCRIPTION_LENGTH == 137


def test_description_accepts_characters_a_windows_folder_name_would_reject(project_dir: Path) -> None:
    description = 'Faster / stronger * better: now with "quotes" <and> a trailing dot.'

    folder, _warning = new_project.create_gametype_project(project_dir, "Slayer Plus", description)

    assert description in (folder / "README.md").read_text(encoding="utf-8")


def test_create_gametype_project_copies_the_source_variant_in_named_after_the_id(
    project_dir: Path, tmp_path: Path
) -> None:
    source = tmp_path / "variants" / "Original.bin"
    source.parent.mkdir()
    source.write_bytes(b"\x00variant")

    folder, _warning = new_project.create_gametype_project(
        project_dir, "Slayer Plus", source_variant=source
    )

    copied = project_dir / new_project.INIT_GAMETYPE_DIRNAME / f"{folder.name}.bin"
    assert copied.read_bytes() == b"\x00variant"


def test_create_gametype_project_rejects_an_empty_title(project_dir: Path) -> None:
    with pytest.raises(ValueError):
        new_project.create_gametype_project(project_dir, "   ")


def test_two_projects_created_in_a_row_get_different_ids(project_dir: Path) -> None:
    first, _warning = new_project.create_gametype_project(project_dir, "One")
    second, _warning = new_project.create_gametype_project(project_dir, "Two")

    assert first != second


# -- category / category_icon ------------------------------------------------------------------


def test_create_gametype_project_defaults_to_no_category_and_no_warning(project_dir: Path) -> None:
    folder, warning = new_project.create_gametype_project(project_dir, "Blank")

    assert warning is None
    document = (folder / "user_settings.json").read_text(encoding="utf-8")
    assert '"category": "none"' in document


def test_create_gametype_project_writes_a_matching_category_and_icon_by_default(
    project_dir: Path,
) -> None:
    folder, warning = new_project.create_gametype_project(project_dir, "Slayer Plus", category=EngineCategory.slayer)

    assert warning is None
    document = (folder / "user_settings.json").read_text(encoding="utf-8")
    assert '"category": "slayer"' in document
    assert '"category_icon": "slayer"' in document


def test_create_gametype_project_reports_a_deliberate_mismatch(project_dir: Path) -> None:
    folder, warning = new_project.create_gametype_project(
        project_dir, "Odd Slayer", category=EngineCategory.slayer, category_icon=EngineIcon.oddball
    )

    assert warning is not None
    assert "Slayer" in warning and "Oddball" in warning
    document = (folder / "user_settings.json").read_text(encoding="utf-8")
    assert '"category_icon": "oddball"' in document


def test_create_gametype_project_writes_title_and_description_to_user_settings(project_dir: Path) -> None:
    folder, _warning = new_project.create_gametype_project(project_dir, "Slayer Plus", "A better slayer")

    document = (folder / "user_settings.json").read_text(encoding="utf-8")
    assert '"title": "Slayer Plus"' in document
    assert '"description": "A better slayer"' in document


# -- maps.json ------------------------------------------------------------------------------------


def test_create_gametype_project_scans_map_folders_into_maps_json(
    project_dir: Path, tmp_path: Path
) -> None:
    from mvar_fixtures import build_chdr_bytes

    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    (maps_dir / "Forge.mvar").write_bytes(build_chdr_bytes(title="My Forge Map", map_id=3006))

    folder, _warning = new_project.create_gametype_project(
        project_dir, "Slayer Plus", personal_maps_dir=maps_dir
    )

    assert (folder / "maps.json").is_file()
    assert (folder / "maps" / "master.json").is_file()
    document = (folder / "maps.json").read_text(encoding="utf-8")
    assert "My Forge Map" in document


def test_create_gametype_project_with_no_map_folders_still_writes_an_empty_maps_json(
    project_dir: Path,
) -> None:
    folder, _warning = new_project.create_gametype_project(project_dir, "Blank")

    document = (folder / "maps.json").read_text(encoding="utf-8")
    assert '"maps": []' in document


# -- read_project_title -----------------------------------------------------------------------


def test_read_project_title_reads_back_the_readmes_heading(project_dir: Path) -> None:
    folder, _warning = new_project.create_gametype_project(project_dir, "Slayer Plus")

    assert new_project.read_project_title(folder) == "Slayer Plus"


def test_read_project_title_falls_back_to_the_folder_name_without_a_readme(tmp_path: Path) -> None:
    folder = tmp_path / "abcd1234"
    folder.mkdir()

    assert new_project.read_project_title(folder) == "abcd1234"


# -- list_variants ----------------------------------------------------------------------------


def test_list_variants_returns_bins_by_name_case_insensitively(tmp_path: Path) -> None:
    folder = tmp_path / "game_variants"
    folder.mkdir()
    for name in ("zulu.bin", "Alpha.bin", "notes.txt"):
        (folder / name).write_bytes(b"")
    (folder / "nested").mkdir()

    assert new_project.list_variants(folder) == [
        ("Alpha", folder / "Alpha.bin"),
        ("zulu", folder / "zulu.bin"),
    ]


def test_list_variants_of_a_missing_folder_is_empty(tmp_path: Path) -> None:
    assert new_project.list_variants(tmp_path / "nope") == []
