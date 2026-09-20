from pathlib import Path

import pytest
from PyQt6.QtGui import QColor

from in_reach.ide import file_icons


def _has_opaque_pixel(image) -> bool:
    return any(
        image.pixelColor(x, y).alpha() > 0
        for x in range(image.width())
        for y in range(image.height())
    )


def _skip_unless_emoji_render_distinctly() -> None:
    """Most icons are emoji drawn through the platform's font. A Qt platform with no emoji font -- Windows'
    ``offscreen`` plugin, say -- draws every one as the same missing-glyph box, so comparing rendered icons
    proves nothing there; say so instead of failing. (``test_every_mapped_glyph_is_distinct`` checks the table
    itself everywhere.)"""
    first = file_icons._glyph_icon("📄").pixmap(32, 32).toImage()
    second = file_icons._glyph_icon("📝").pixmap(32, 32).toImage()
    if first == second:
        pytest.skip("this Qt platform has no emoji font: every emoji renders as the same box")


def test_every_mapped_glyph_is_distinct() -> None:
    """What the rendered-icon comparisons below check, without needing a font to draw them."""
    glyphs = [text for text, _color in file_icons._GLYPH_BY_SUFFIX.values()]

    assert len(set(glyphs)) == len(glyphs)
    assert file_icons._FOLDER_EMOJI_CLOSED not in glyphs
    assert file_icons._FOLDER_EMOJI_CLOSED != file_icons._FOLDER_EMOJI_OPEN


def test_icon_for_suffix_renders_something_for_every_mapped_extension(qtbot) -> None:
    for suffix in (".txt", ".md", ".json", ".mvar", ".bin", ".gitignore", ".pkl", ".mglo"):
        icon = file_icons.icon_for_suffix(suffix)
        pixmap = icon.pixmap(32, 32)
        assert not pixmap.isNull()
        assert _has_opaque_pixel(pixmap.toImage())


def test_txt_md_and_json_each_render_a_distinct_icon(qtbot) -> None:
    _skip_unless_emoji_render_distinctly()
    images = {
        suffix: file_icons.icon_for_suffix(suffix).pixmap(32, 32).toImage()
        for suffix in (".txt", ".md", ".json")
    }
    assert images[".txt"] != images[".md"]
    assert images[".txt"] != images[".json"]
    assert images[".md"] != images[".json"]


def test_icon_for_suffix_is_case_insensitive() -> None:
    lower = file_icons.icon_for_suffix(".bin").pixmap(32, 32).toImage()
    upper = file_icons.icon_for_suffix(".BIN").pixmap(32, 32).toImage()

    assert lower == upper


def test_different_mapped_suffixes_render_different_icons(qtbot) -> None:
    _skip_unless_emoji_render_distinctly()
    bin_icon = file_icons.icon_for_suffix(".bin").pixmap(32, 32).toImage()
    mvar_icon = file_icons.icon_for_suffix(".mvar").pixmap(32, 32).toImage()

    assert bin_icon != mvar_icon


def test_json_icon_is_yellow_braces(qtbot) -> None:
    # PROMPT.md: "for the icons please use yellow {} for json".
    image = file_icons.icon_for_suffix(".json").pixmap(32, 32).toImage()

    colors = [image.pixelColor(x, y) for x in range(32) for y in range(32) if image.pixelColor(x, y).alpha() > 0]
    expected = QColor(file_icons._JSON_COLOR)
    assert any(
        abs(c.red() - expected.red()) < 10 and abs(c.green() - expected.green()) < 10 and abs(c.blue() - expected.blue()) < 10
        for c in colors
    )


def test_icon_for_suffix_falls_back_for_an_unknown_extension(qtbot) -> None:
    generic = file_icons.icons.icon(file_icons._GENERIC_FILE_ICON_NAME, size=16).pixmap(16, 16).toImage()
    rendered = file_icons.icon_for_suffix(".xyz123").pixmap(16, 16).toImage()

    assert rendered == generic


def test_icon_for_path_uses_a_folder_glyph_for_a_directory(tmp_path: Path, qtbot) -> None:
    _skip_unless_emoji_render_distinctly()
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


def test_a_drive_that_denies_access_still_gets_an_icon(monkeypatch) -> None:
    """Qt's file model asks for an icon for every drive root, including one Windows won't let us look at (a
    locked or card-reader drive). ``Path.is_dir()`` raises ``PermissionError`` for it on Python 3.12/3.13
    (3.14 returns ``False``); out of this Qt virtual method that surfaced as "Exceptions caught in Qt event
    loop" and failed every test that showed the Explorer, on a machine with such a drive."""

    def denied(self) -> bool:
        raise PermissionError(5, "Access is denied", str(self))

    monkeypatch.setattr(Path, "is_dir", denied)

    icon = file_icons.icon_for_path(Path("G:/"))

    assert not icon.isNull()


def test_the_explorer_icon_provider_survives_an_unreadable_path(monkeypatch) -> None:
    from PyQt6.QtCore import QFileInfo

    def denied(self) -> bool:
        raise PermissionError(5, "Access is denied", str(self))

    monkeypatch.setattr(Path, "is_dir", denied)

    assert not file_icons.ExplorerIconProvider().icon(QFileInfo("G:/")).isNull()
