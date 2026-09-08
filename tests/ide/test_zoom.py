from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QKeySequence
from PyQt6.QtWidgets import QApplication

from in_reach.app import env_file
from in_reach.ide import zoom
from in_reach.ide.main_window import MainWindow


@pytest.fixture
def env_path(tmp_path: Path) -> Path:
    project_dir = tmp_path / ".in-reach"
    project_dir.mkdir()
    path = project_dir / ".env"
    path.write_text("", encoding="utf-8")
    return path


def test_default_zoom_is_122_percent() -> None:
    # PROMPT.md: a fresh project should open at 150% of the plain app font (not true 100%), reduced
    # 10% twice since to 122% -- and MAX_ZOOM has to leave real headroom above that default, not
    # sit one step above it.
    assert zoom.DEFAULT_ZOOM == 1.22
    assert zoom.MAX_ZOOM > zoom.DEFAULT_ZOOM + zoom.ZOOM_STEP


# -- get_zoom / set_zoom -----------------------------------------------------------------------


def test_get_zoom_defaults_when_nothing_is_stored(env_path: Path) -> None:
    assert zoom.get_zoom(env_path) == zoom.DEFAULT_ZOOM


def test_get_zoom_defaults_for_an_unparsable_value(env_path: Path) -> None:
    env_file.update_env_value(env_path, zoom.ZOOM_KEY, "not-a-number")

    assert zoom.get_zoom(env_path) == zoom.DEFAULT_ZOOM


def test_set_zoom_round_trips_through_get_zoom(env_path: Path) -> None:
    zoom.set_zoom(env_path, 1.3)

    assert zoom.get_zoom(env_path) == 1.3
    assert env_file.get_env_values(env_path)[zoom.ZOOM_KEY] == "1.30"


def test_set_zoom_clamps_to_the_max(env_path: Path) -> None:
    stored = zoom.set_zoom(env_path, zoom.MAX_ZOOM + 1)

    assert stored == zoom.MAX_ZOOM
    assert zoom.get_zoom(env_path) == zoom.MAX_ZOOM


def test_set_zoom_clamps_to_the_min(env_path: Path) -> None:
    stored = zoom.set_zoom(env_path, zoom.MIN_ZOOM - 1)

    assert stored == zoom.MIN_ZOOM
    assert zoom.get_zoom(env_path) == zoom.MIN_ZOOM


# -- apply_zoom ---------------------------------------------------------------------------------


def test_apply_zoom_scales_the_app_font_from_the_given_baseline(qtbot) -> None:
    app = QApplication.instance()
    base_font = QFont()
    base_font.setPointSizeF(10.0)

    zoom.apply_zoom(app, 1.5, base_font=base_font)

    assert app.font().pointSizeF() == pytest.approx(15.0)


def test_apply_zoom_always_scales_from_the_same_baseline_not_the_last_applied_font(qtbot) -> None:
    # Repeated zoom-in/zoom-out cycles must not drift -- each call scales from the fixed baseline,
    # never from whatever the previous apply_zoom() call left app.font() at.
    app = QApplication.instance()
    base_font = QFont()
    base_font.setPointSizeF(10.0)

    zoom.apply_zoom(app, 1.5, base_font=base_font)
    zoom.apply_zoom(app, 1.1, base_font=base_font)

    assert app.font().pointSizeF() == pytest.approx(11.0)


def test_apply_zoom_without_an_explicit_baseline_captures_one_lazily(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(zoom, "_base_font", None)
    app = QApplication.instance()
    starting_size = app.font().pointSizeF()

    zoom.apply_zoom(app, 1.2)

    assert app.font().pointSizeF() == pytest.approx(starting_size * 1.2)
    # A second call (still no explicit baseline) scales from that same captured baseline, not from
    # the now-1.2x-zoomed app.font() -- otherwise this would compound to 1.2 * 1.2.
    zoom.apply_zoom(app, 1.0)
    assert app.font().pointSizeF() == pytest.approx(starting_size)


# -- current_scale ------------------------------------------------------------------------------


def test_current_scale_reflects_the_live_font_against_the_captured_baseline(qtbot, monkeypatch) -> None:
    app = QApplication.instance()
    base_font = QFont()
    base_font.setPointSizeF(10.0)
    # current_scale() only ever reads the module's own captured baseline (never an explicit
    # base_font= override) -- seed that baseline directly so this test doesn't depend on whatever
    # an earlier test in the shared QApplication session already captured it as.
    monkeypatch.setattr(zoom, "_base_font", QFont(base_font))

    zoom.apply_zoom(app, 1.4)
    assert zoom.current_scale(app) == pytest.approx(1.4)

    zoom.apply_zoom(app, 0.8)
    assert zoom.current_scale(app) == pytest.approx(0.8)


def test_current_scale_defaults_to_1_when_zoom_was_never_applied(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(zoom, "_base_font", None)
    assert zoom.current_scale(QApplication.instance()) == 1.0


# -- MainWindow wiring ----------------------------------------------------------------------------


@pytest.fixture
def project_window(qtbot, tmp_path: Path):
    project_dir = tmp_path / ".in-reach"
    project_dir.mkdir()
    (project_dir / ".env").write_text("", encoding="utf-8")
    win = MainWindow(root_dir=tmp_path)
    qtbot.addWidget(win)
    win.show()
    return win


def _normalize_zoom(monkeypatch) -> float:
    """Resets the module's captured baseline and re-captures it against the app's current font, so
    a test's "before" point size is deterministic regardless of what an earlier test in this shared
    QApplication session already zoomed to."""
    monkeypatch.setattr(zoom, "_base_font", None)
    app = QApplication.instance()
    zoom.apply_zoom(app, 1.0)
    return app.font().pointSizeF()


def test_ctrl_plus_zooms_in_and_persists_to_the_projects_env(
    project_window: MainWindow, tmp_path: Path, monkeypatch
) -> None:
    base_size = _normalize_zoom(monkeypatch)

    project_window._zoom_in()

    app = QApplication.instance()
    assert app.font().pointSizeF() == pytest.approx(base_size * (zoom.DEFAULT_ZOOM + zoom.ZOOM_STEP))
    env_path = tmp_path / ".in-reach" / ".env"
    assert env_file.get_env_values(env_path)[zoom.ZOOM_KEY] == f"{zoom.DEFAULT_ZOOM + zoom.ZOOM_STEP:.2f}"


def test_ctrl_minus_zooms_out_and_persists(project_window: MainWindow, tmp_path: Path, monkeypatch) -> None:
    base_size = _normalize_zoom(monkeypatch)

    project_window._zoom_out()

    app = QApplication.instance()
    assert app.font().pointSizeF() == pytest.approx(base_size * (zoom.DEFAULT_ZOOM - zoom.ZOOM_STEP))
    env_path = tmp_path / ".in-reach" / ".env"
    assert env_file.get_env_values(env_path)[zoom.ZOOM_KEY] == f"{zoom.DEFAULT_ZOOM - zoom.ZOOM_STEP:.2f}"


def test_zooming_resizes_the_top_left_mark_icon(
    project_window: MainWindow, monkeypatch
) -> None:
    # Regression guard: apply_zoom() only rescales the live QFont -- the top-left mark is a fixed
    # QPixmap baked once at construction, so a zoom change left it stuck at its original size until
    # refresh_icon_colors() was taught to also re-render it (see _adjust_zoom()).
    _normalize_zoom(monkeypatch)
    # _normalize_zoom() only resets the *font* baseline -- this window's icons were already baked
    # once at construction, against whatever scale was live then (possibly a previous test's), so
    # they need their own explicit refresh to establish a clean "before" at the reset baseline.
    project_window.refresh_icon_colors()
    before = project_window.top_bar.mark_label.pixmap().width()

    project_window._zoom_in()

    after = project_window.top_bar.mark_label.pixmap().width()
    assert after > before


def test_zooming_keeps_the_explorer_panel_at_its_own_10_percent_scale(
    project_window: MainWindow, monkeypatch
) -> None:
    from in_reach.ide.explorer import ExplorerPanel

    base_size = _normalize_zoom(monkeypatch)
    project_window.explorer_panel.refresh_font_scale()
    assert project_window.explorer_panel.font().pointSizeF() == pytest.approx(
        base_size * ExplorerPanel.TEXT_SCALE
    )

    project_window._zoom_in()

    app = QApplication.instance()
    expected = app.font().pointSizeF() * ExplorerPanel.TEXT_SCALE
    assert project_window.explorer_panel.font().pointSizeF() == pytest.approx(expected)


def test_zooming_resizes_the_top_bar_toggle_icons_too(project_window: MainWindow, monkeypatch) -> None:
    # Each toggle/window-control icon is backed by a single fixed-size source pixmap (baked by
    # icons.icon()), so its own availableSizes() reports that actual baked size -- unlike
    # icon().pixmap(w, h), which happily upscales/downscales to whatever size is asked for and so
    # can't tell "grew" from "was resampled".
    _normalize_zoom(monkeypatch)
    project_window.refresh_icon_colors()
    before = project_window.top_bar.sidebar_toggle.icon().availableSizes()[0].width()

    project_window._zoom_in()

    after = project_window.top_bar.sidebar_toggle.icon().availableSizes()[0].width()
    assert after > before


def test_zoom_stops_at_the_max_rather_than_climbing_forever(
    project_window: MainWindow, tmp_path: Path, monkeypatch
) -> None:
    _normalize_zoom(monkeypatch)

    for _ in range(50):
        project_window._zoom_in()

    env_path = tmp_path / ".in-reach" / ".env"
    assert env_file.get_env_values(env_path)[zoom.ZOOM_KEY] == f"{zoom.MAX_ZOOM:.2f}"


def test_zoom_stops_at_the_min_rather_than_shrinking_forever(
    project_window: MainWindow, tmp_path: Path, monkeypatch
) -> None:
    _normalize_zoom(monkeypatch)

    for _ in range(50):
        project_window._zoom_out()

    env_path = tmp_path / ".in-reach" / ".env"
    assert env_file.get_env_values(env_path)[zoom.ZOOM_KEY] == f"{zoom.MIN_ZOOM:.2f}"


def test_a_saved_zoom_level_is_picked_up_by_a_later_window_on_the_same_project(
    tmp_path: Path, qtbot, monkeypatch
) -> None:
    project_dir = tmp_path / ".in-reach"
    project_dir.mkdir()
    env_file.update_env_value(project_dir / ".env", zoom.ZOOM_KEY, "1.30")

    win = MainWindow(root_dir=tmp_path)
    qtbot.addWidget(win)

    assert zoom.get_zoom(project_dir / ".env") == 1.3


def test_the_zoom_in_shortcut_is_bound_to_ctrl_plus_and_ctrl_equals(project_window: MainWindow) -> None:
    keys = [seq.toString() for seq in project_window._zoom_in_shortcut.keys()]
    assert "Ctrl++" in keys
    assert "Ctrl+=" in keys


def test_the_zoom_out_shortcut_is_bound_to_ctrl_minus(project_window: MainWindow) -> None:
    keys = [seq.toString() for seq in project_window._zoom_out_shortcut.keys()]
    assert "Ctrl+-" in keys


@pytest.mark.parametrize("shortcut_name", ["_zoom_in_shortcut", "_zoom_out_shortcut"])
def test_no_shortcut_binds_the_same_key_sequence_twice(
    project_window: MainWindow, shortcut_name: str
) -> None:
    # Regression guard: a QShortcut with a *duplicate* key sequence in its own key list treats a
    # matching press as two matches for that key, which Qt resolves as ambiguous -- it fires
    # activatedAmbiguously instead of activated, and the shortcut silently never triggers. This is
    # exactly what made Ctrl+- never work: QKeySequence.StandardKey.ZoomOut and the literal
    # QKeySequence("Ctrl+-") resolve to the identical sequence on this platform, so the key list
    # `[StandardKey.ZoomOut, "Ctrl+-"]` was really the same entry listed twice.
    keys = [seq.toString() for seq in getattr(project_window, shortcut_name).keys()]
    assert len(keys) == len(set(keys))


def test_activating_the_zoom_in_shortcut_signal_zooms_in(
    project_window: MainWindow, tmp_path: Path, monkeypatch
) -> None:
    # Fires the QShortcut's own signal rather than calling the handler directly -- this is what
    # proves the shortcut is actually wired to the handler, not just that the handler works.
    base_size = _normalize_zoom(monkeypatch)

    project_window._zoom_in_shortcut.activated.emit()

    app = QApplication.instance()
    assert app.font().pointSizeF() == pytest.approx(base_size * (zoom.DEFAULT_ZOOM + zoom.ZOOM_STEP))


@pytest.mark.parametrize(
    ("key", "modifier", "expected_delta"),
    [
        (Qt.Key.Key_Equal, Qt.KeyboardModifier.ControlModifier, zoom.ZOOM_STEP),
        (Qt.Key.Key_Minus, Qt.KeyboardModifier.ControlModifier, -zoom.ZOOM_STEP),
    ],
)
def test_a_real_keypress_triggers_the_zoom_shortcut(
    qtbot, project_window: MainWindow, tmp_path: Path, key, modifier, expected_delta
) -> None:
    # Delivers an actual key event through Qt's own shortcut dispatch (unlike the .activated.emit()
    # tests above, which call the connected slot directly and can't detect an ambiguous-shortcut
    # match) -- this is the level a duplicate key sequence in a shortcut's own key list breaks at:
    # Qt counts a duplicate as two matches for that key and treats it as ambiguous, so it fires
    # activatedAmbiguously instead of activated and the handler never runs.
    project_window.show()
    project_window.raise_()
    project_window.activateWindow()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is project_window, timeout=2000)

    env_path = tmp_path / ".in-reach" / ".env"
    before = zoom.get_zoom(env_path)

    qtbot.keyClick(project_window, key, modifier)

    assert zoom.get_zoom(env_path) == pytest.approx(before + expected_delta)
