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
