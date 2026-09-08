from pathlib import Path

from in_reach.ide import file_icons


def _has_opaque_pixel(image) -> bool:
    return any(
        image.pixelColor(x, y).alpha() > 0
        for x in range(image.width())
        for y in range(image.height())
    )


def test_icon_for_suffix_renders_something_for_every_mapped_extension(qtbot) -> None:
    for suffix in (".mvar", ".bin", ".gitignore", ".pkl", ".mglo"):
        icon = file_icons.icon_for_suffix(suffix)
        pixmap = icon.pixmap(32, 32)
        assert not pixmap.isNull()
        assert _has_opaque_pixel(pixmap.toImage())


def test_icon_for_suffix_is_case_insensitive() -> None:
    lower = file_icons.icon_for_suffix(".bin").pixmap(32, 32).toImage()
    upper = file_icons.icon_for_suffix(".BIN").pixmap(32, 32).toImage()

    assert lower == upper


def test_different_mapped_suffixes_render_different_icons(qtbot) -> None:
    bin_icon = file_icons.icon_for_suffix(".bin").pixmap(32, 32).toImage()
    mvar_icon = file_icons.icon_for_suffix(".mvar").pixmap(32, 32).toImage()

    assert bin_icon != mvar_icon


def test_icon_for_suffix_falls_back_to_the_generic_file_glyph_for_txt_md_json(qtbot) -> None:
    generic = file_icons.icons.icon(file_icons._GENERIC_FILE_ICON_NAME, size=16).pixmap(16, 16).toImage()
    for suffix in (".txt", ".md", ".json"):
        rendered = file_icons.icon_for_suffix(suffix).pixmap(16, 16).toImage()
        assert rendered == generic


def test_icon_for_suffix_falls_back_for_an_unknown_extension(qtbot) -> None:
    generic = file_icons.icons.icon(file_icons._GENERIC_FILE_ICON_NAME, size=16).pixmap(16, 16).toImage()
    rendered = file_icons.icon_for_suffix(".xyz123").pixmap(16, 16).toImage()

    assert rendered == generic


def test_icon_for_path_uses_a_folder_glyph_for_a_directory(tmp_path: Path, qtbot) -> None:
    folder_icon = file_icons.icon_for_path(tmp_path).pixmap(32, 32).toImage()
    (tmp_path / "file.bin").write_bytes(b"")
    file_icon = file_icons.icon_for_path(tmp_path / "file.bin").pixmap(32, 32).toImage()

    assert folder_icon != file_icon


def test_icon_for_path_handles_a_dotfile_with_no_further_suffix(tmp_path: Path, qtbot) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("*\n", encoding="utf-8")

    icon = file_icons.icon_for_path(gitignore).pixmap(32, 32).toImage()
    mapped = file_icons.icon_for_suffix(".gitignore").pixmap(32, 32).toImage()

    assert icon == mapped
