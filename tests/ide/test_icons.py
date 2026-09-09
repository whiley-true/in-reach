from in_reach.ide import icons


def _has_opaque_pixel(image) -> bool:
    return any(
        image.pixelColor(x, y).alpha() > 0
        for x in range(image.width())
        for y in range(image.height())
    )


def test_icon_renders_a_known_glyph(qtbot) -> None:
    icon = icons.icon("search", color="#ff0000", size=16)
    pixmap = icon.pixmap(16, 16)

    assert not pixmap.isNull()
    assert _has_opaque_pixel(pixmap.toImage())


def test_icon_falls_back_to_a_blank_pixmap_for_an_unknown_name(qtbot) -> None:
    icon = icons.icon("not-a-real-icon", size=16)
    pixmap = icon.pixmap(16, 16)

    assert not pixmap.isNull()
    assert not _has_opaque_pixel(pixmap.toImage())


def test_icon_color_changes_the_rendered_pixels(qtbot) -> None:
    red = icons.icon("search", color="#ff0000", size=16).pixmap(16, 16).toImage()
    blue = icons.icon("search", color="#0000ff", size=16).pixmap(16, 16).toImage()

    assert red != blue


def test_every_window_control_glyph_renders(qtbot) -> None:
    for name in ("win_minimize", "win_maximize", "win_restore", "win_close"):
        pixmap = icons.icon(name, size=16).pixmap(16, 16)
        assert not pixmap.isNull()
        assert _has_opaque_pixel(pixmap.toImage())


def test_app_icon_and_topbar_icon_load(qtbot) -> None:
    assert not icons.app_icon().isNull()
    assert not icons.topbar_icon().isNull()


def test_rvt_icon_loads(qtbot) -> None:
    assert not icons.rvt_icon().isNull()


def _has_red_badge_pixel(image) -> bool:
    # icons._with_disabled_badge() paints its "blocked" badge in #e51400 -- look for something in
    # that same red family (not white/grey/transparent) rather than an exact color match, since
    # antialiasing blends the badge's edge pixels toward the icon underneath it.
    return any(
        (pixel := image.pixelColor(x, y)).alpha() > 0 and pixel.red() > 180 and pixel.green() < 80
        for x in range(image.width())
        for y in range(image.height())
    )


def test_apply_icon_enabled_has_no_badge(qtbot) -> None:
    pixmap = icons.apply_icon(size=32, enabled=True).pixmap(32, 32)
    assert not _has_red_badge_pixel(pixmap.toImage())


def test_apply_icon_disabled_shows_a_red_no_entry_badge(qtbot) -> None:
    # PROMPT.md: "please also use the red no entry icon (like you do for rvt) when the apply
    # button can not be pressed".
    pixmap = icons.apply_icon(size=32, enabled=False).pixmap(32, 32)
    assert _has_red_badge_pixel(pixmap.toImage())


def test_apply_icon_disabled_badge_survives_disabled_icon_mode(qtbot) -> None:
    # Same fix as rvt_icon(): a disabled QToolButton renders the icon's Disabled-mode pixmap, which
    # Qt would otherwise auto-desaturate from Normal and wash the badge out.
    from PyQt6.QtGui import QIcon

    icon = icons.apply_icon(size=32, enabled=False)
    pixmap = icon.pixmap(32, 32, mode=QIcon.Mode.Disabled)
    assert _has_red_badge_pixel(pixmap.toImage())
