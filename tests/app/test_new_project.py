from pathlib import Path

import pytest

from in_reach.app import env_file, new_project


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    project = tmp_path / ".in-reach"
    project.mkdir()
    (project / ".env").write_text("", encoding="utf-8")
    return project


@pytest.mark.parametrize("title", ["My Gametype", "a", "x" * new_project.MAX_TITLE_LENGTH, "CONTEST"])
def test_valid_titles(title: str) -> None:
    assert new_project.is_valid_title(title) is True


@pytest.mark.parametrize(
    "title",
    [
        "",
        "x" * (new_project.MAX_TITLE_LENGTH + 1),
        "trailing space ",
        "trailing dot.",
        "slash/es",
        "back\\slash",
        "co:lon",
        "CON",
        "nul.txt",
        "com1",
    ],
)
def test_invalid_titles(title: str) -> None:
    assert new_project.is_valid_title(title) is False


def test_create_gametype_project_scaffolds_edit_build_and_readme(project_dir: Path, tmp_path: Path) -> None:
    folder = new_project.create_gametype_project(project_dir, "Slayer Plus", "A better slayer")

    assert folder == tmp_path / "Slayer Plus"
    assert (folder / "edit" / "settings").is_dir()
    assert (folder / "edit" / "rvt").is_dir()
    assert (folder / "build" / "dist").is_dir()
    # build/ is regenerated from edit/, so it ignores itself rather than relying on the user's repo.
    assert (folder / "build" / ".gitignore").read_text(encoding="utf-8") == "*\n!.gitignore\n"

    readme = (folder / "README.md").read_text(encoding="utf-8")
    assert "# Slayer Plus" in readme
    assert "A better slayer" in readme


def test_create_gametype_project_points_project_dir_at_the_new_folder(project_dir: Path) -> None:
    folder = new_project.create_gametype_project(project_dir, "Slayer Plus")

    values = env_file.get_env_values(project_dir / ".env")
    assert values[new_project.PROJECT_DIR_KEY] == str(folder)


def test_create_gametype_project_without_a_description_still_writes_a_readme(project_dir: Path) -> None:
    folder = new_project.create_gametype_project(project_dir, "Blank One")

    assert "_No description._" in (folder / "README.md").read_text(encoding="utf-8")


def test_description_max_length_is_137_and_unrelated_to_windows_naming_rules() -> None:
    assert new_project.MAX_DESCRIPTION_LENGTH == 137


def test_description_accepts_characters_a_windows_folder_name_would_reject(project_dir: Path) -> None:
    # Unlike the title (which names a real folder -- see is_valid_title), the description is only
    # ever written into the README's body text, so it has no reason to follow those rules.
    description = 'Faster / stronger * better: now with "quotes" <and> a trailing dot.'

    folder = new_project.create_gametype_project(project_dir, "Slayer Plus", description)

    assert description in (folder / "README.md").read_text(encoding="utf-8")


def test_create_gametype_project_copies_the_source_variant_in(project_dir: Path, tmp_path: Path) -> None:
    source = tmp_path / "variants" / "Original.bin"
    source.parent.mkdir()
    source.write_bytes(b"\x00variant")

    new_project.create_gametype_project(project_dir, "Slayer Plus", source_variant=source)

    copied = project_dir / new_project.INIT_GAMETYPE_DIRNAME / "Slayer Plus.bin"
    assert copied.read_bytes() == b"\x00variant"


def test_create_gametype_project_rejects_an_illegal_title(project_dir: Path) -> None:
    with pytest.raises(ValueError):
        new_project.create_gametype_project(project_dir, "no/slashes")


def test_create_gametype_project_refuses_to_overwrite_an_existing_folder(
    project_dir: Path, tmp_path: Path
) -> None:
    (tmp_path / "Taken").mkdir()

    with pytest.raises(FileExistsError):
        new_project.create_gametype_project(project_dir, "Taken")


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
