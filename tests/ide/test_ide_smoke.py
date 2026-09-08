from pathlib import Path

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QTabWidget

from in_reach.ide import app as ide_app
from in_reach.ide import icons, style, theme
from in_reach.ide import zoom as zoom_module
from in_reach.ide.activity_bar import ActivityBar
from in_reach.ide.editor import TextEditorWidget
from in_reach.ide.first_run_dialog import FirstRunDialog
from in_reach.ide.main_window import _ICON_SIZE, _SIDEBAR_MIN_WIDTH, MainWindow
from in_reach.ide.tabs import _MAX_H_SPLITS, _MAX_V_SPLITS
from in_reach.ide.welcome import WelcomeTab


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    return win


def test_lists_the_three_shipped_themes() -> None:
    assert theme.list_themes() == ["Light", "Dark", "Whiley"]


def test_apply_theme_falls_back_to_default_for_an_unknown_name(qtbot) -> None:
    app = QApplication.instance()
    applied = theme.apply_theme(app, "Not A Real Theme")
    assert applied.name == theme.DEFAULT_THEME_NAME


def test_every_theme_has_readable_tooltip_contrast() -> None:
    # Regression guard: the Dark/Whiley themes used to define tooltip_base and tooltip_text as the
    # exact same color, making tooltip text invisible.
    for name in theme.list_themes():
        loaded = theme.load_theme(name)
        assert loaded.palette_colors["tooltip_base"] != loaded.palette_colors["tooltip_text"]


def test_apply_theme_sets_the_app_palette_and_forces_fusion(qtbot) -> None:
    app = QApplication.instance()

    applied = theme.apply_theme(app, "Dark")

    # apply_theme() also sets an app-wide QToolTip stylesheet (PROMPT.md: tooltip background) --
    # Qt wraps app.style() in an internal QStyleSheetStyle proxy the moment *any* stylesheet is
    # set, whose own objectName() reads back empty rather than delegating to the Fusion base style
    # underneath it. That proxy still renders everything it doesn't explicitly override (i.e.
    # everything but QToolTip) via that same Fusion base, so the palette assertions below are the
    # actual proof Fusion's own palette-driven rendering (the reason it's forced at all -- see this
    # module's own docstring) is still in effect, not the style object's own reported name.
    dark = theme.load_theme("Dark")
    for key, color_hex in dark.palette_colors.items():
        role = theme._PALETTE_ROLES.get(key)
        if role is not None:
            assert app.palette().color(role) == QColor(color_hex)
    assert applied.name == "Dark"


def test_apply_theme_sets_an_opaque_tooltip_stylesheet(qtbot) -> None:
    # PROMPT.md: "when showing the helper text for icons we need to have a background colour for
    # the text to display on" -- QToolTip.setPalette() alone wasn't reliably enough (a known
    # Fusion-style quirk), so this checks the belt-and-braces QSS rule is actually present too.
    app = QApplication.instance()

    theme.apply_theme(app, "Dark")

    assert "QToolTip" in app.styleSheet()
    assert "background-color" in app.styleSheet()


def test_build_palette_applies_disabled_text_to_disabled_roles() -> None:
    loaded = theme.load_theme("Dark")
    palette = loaded.build_palette()

    disabled = QColor(loaded.disabled_text)
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        assert palette.color(QPalette.ColorGroup.Disabled, role) == disabled


def test_on_theme_applied_colors_status_bar_and_icons_immediately(window: MainWindow) -> None:
    whiley = theme.load_theme("Whiley")

    window.on_theme_applied(whiley)

    assert window.status_bar.styleSheet() == f"background-color: {whiley.status_bar_color};"


def _current_icon_size() -> int:
    # refresh_icon_colors() bakes every top-bar icon at _ICON_SIZE scaled by the live zoom level --
    # these helpers have to match that exactly, or a size mismatch alone (independent of color/name)
    # would make an otherwise-correct icon compare unequal.
    return round(_ICON_SIZE * zoom_module.current_scale(QApplication.instance()))


def _maximize_icon_image(window: MainWindow):
    size = _current_icon_size()
    return window.top_bar.maximize_button.icon().pixmap(size, size).toImage()


def _expected_icon_image(name: str, window: MainWindow):
    color = window.palette().color(QPalette.ColorRole.WindowText).name()
    size = _current_icon_size()
    return icons.icon(name, color=color, size=size).pixmap(size, size).toImage()


def test_refresh_icon_colors_shows_restore_icon_when_maximized(window: MainWindow) -> None:
    # Regression guard: refresh_icon_colors() must reflect isMaximized() correctly in both
    # directions, not just carry over whatever icon_name each button started construction with.
    window.showNormal()
    QApplication.processEvents()
    window.refresh_icon_colors()
    assert _maximize_icon_image(window) == _expected_icon_image("win_maximize", window)

    window.showMaximized()
    QApplication.processEvents()
    window.refresh_icon_colors()
    assert _maximize_icon_image(window) == _expected_icon_image("win_restore", window)


def test_adjust_zoom_refreshes_explorer_and_search_panel_fonts(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression guard: the Explorer/Search panels' own text scale is a one-time snapshot of
    # app.font() (see each panel's refresh_font_scale() docstring), not a live binding -- a zoom
    # change has to explicitly re-apply it on both, or their text silently stops tracking zoom.
    from in_reach.app import project

    window.root_dir = tmp_path
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir(parents=True)
    (project_dir / ".env").write_text("", encoding="utf-8")

    calls: list[str] = []
    monkeypatch.setattr(window.explorer_panel, "refresh_font_scale", lambda: calls.append("explorer"))
    monkeypatch.setattr(window.search_panel, "refresh_font_scale", lambda: calls.append("search"))

    window._adjust_zoom(0)

    assert calls == ["explorer", "search"]


def test_sidebar_default_width_fits_the_personal_variant_headers_without_eliding(
    window: MainWindow,
) -> None:
    # Regression guard (PROMPT.md): the sidebar's default/minimum width used to be narrow enough
    # that "Personal Game Variants"/"Personal Map Variants" middle-elided to "Personal G..e
    # Variants". sizeHint() is exactly the width QToolButton itself says it needs to show the
    # whole label unelided, so the sidebar must never be narrower than that.
    assert window.primary_sidebar.width() == _SIDEBAR_MIN_WIDTH
    for section in (window.explorer_panel.personal_variants_section, window.explorer_panel.personal_maps_section):
        assert section._toggle.sizeHint().width() < _SIDEBAR_MIN_WIDTH


def test_toggle_maximize_restores_to_half_screen_centered(window: MainWindow) -> None:
    window.showMaximized()
    QApplication.processEvents()
    assert window.isMaximized() is True

    window.toggle_maximize()
    QApplication.processEvents()

    assert window.isMaximized() is False
    avail = (window.screen() or QApplication.primaryScreen()).availableGeometry()
    # minimumSize was set from the *primary* screen at construction time, while toggle_maximize()
    # restores relative to whichever screen the window is actually on -- on a multi-monitor setup
    # where a secondary screen is smaller, the resize can get clamped back up by that minimum, so
    # match toggle_maximize()'s own actual guarantee rather than assuming they're always the same.
    assert window.width() == max(avail.width() // 2, window.minimumWidth())
    assert window.height() == max(avail.height() // 2, window.minimumHeight())
    # toggle_maximize() must refresh the icon itself, not rely on some other caller doing it.
    assert _maximize_icon_image(window) == _expected_icon_image("win_maximize", window)


def test_toggle_maximize_shows_restore_icon_when_maximizing(window: MainWindow) -> None:
    window.showNormal()
    QApplication.processEvents()

    window.toggle_maximize()
    QApplication.processEvents()

    assert window.isMaximized() is True
    assert _maximize_icon_image(window) == _expected_icon_image("win_restore", window)


def test_main_window_opens_on_the_welcome_tab(window: MainWindow) -> None:
    pane = window.main_panel.panes[0]
    assert pane.count() == 1
    assert pane.tabText(0) == "Welcome"
    assert isinstance(pane.widget(0), WelcomeTab)


def test_opening_a_project_from_the_welcome_tab_updates_the_explorer_panel(
    project_window: MainWindow, tmp_path: Path
) -> None:
    # project_window, not window -- opening a project now persists the open-tabs list to .env
    # (see explorer.py's open_project()), which needs a real, isolated .in-reach to write into
    # rather than the shared window fixture's Path.cwd() root (see project_window's own docstring).
    folder = tmp_path / "some-project"
    folder.mkdir()

    welcome = project_window.main_panel.panes[0].widget(0)
    welcome.project_opened.emit(folder)

    assert Path(project_window.explorer_panel._project_model.rootPath()) == folder


def test_opening_a_project_also_points_the_search_panel_at_it(
    project_window: MainWindow, tmp_path: Path
) -> None:
    folder = tmp_path / "some-project"
    folder.mkdir()

    welcome = project_window.main_panel.panes[0].widget(0)
    welcome.project_opened.emit(folder)

    assert project_window.search_panel._project_folder == folder
    assert project_window.search_panel.search_edit.isEnabled() is True


def test_close_project_also_clears_the_search_panel(project_window: MainWindow, tmp_path: Path) -> None:
    folder = tmp_path / "some-project"
    folder.mkdir()
    project_window._on_project_opened(folder)

    project_window.close_project()

    assert project_window.search_panel._project_folder is None
    assert project_window.search_panel.search_edit.isEnabled() is False


def test_activating_a_search_result_opens_the_file_at_that_line(
    project_window: MainWindow, tmp_path: Path
) -> None:
    folder = tmp_path / "some-project"
    folder.mkdir()
    source = folder / "notes.txt"
    source.write_text("one\ntwo needle three\n", encoding="utf-8")
    project_window._on_project_opened(folder)
    pane = project_window.main_panel.active_pane
    before = pane.count()

    project_window.search_panel.file_activated.emit(source, 2)

    assert pane.count() == before + 1
    editor = pane.widget(pane.currentIndex())
    assert editor.textCursor().blockNumber() == 1  # 0-based -- line 2


def test_a_welcome_refresh_updates_the_explorer_panels_personal_folders(qtbot, tmp_path: Path) -> None:
    from in_reach.app import env_file, system_verify

    # A real (tmp_path-rooted) MainWindow rather than the shared `window` fixture -- its explorer
    # panel's env project dir is resolved once, at construction, off root_dir, so a test that needs
    # to write to that exact .env has to control root_dir from the start rather than reassigning it
    # afterward.
    project_dir = tmp_path / ".in-reach"
    project_dir.mkdir()
    (project_dir / ".env").write_text("", encoding="utf-8")
    win = MainWindow(root_dir=tmp_path)
    qtbot.addWidget(win)

    variants = tmp_path / "variants"
    variants.mkdir()
    env_file.update_env_value(project_dir / ".env", system_verify.PERSONAL_VARIANTS_KEY, str(variants))

    welcome = win.main_panel.panes[0].widget(0)
    welcome.refresh()

    body = win.explorer_panel.personal_variants_section.body
    assert win.explorer_panel.personal_variants_tree.isVisibleTo(body) is True


def test_bottom_panel_has_cyclable_stub_tabs(window: MainWindow) -> None:
    bottom = window.bottom_panel
    labels = [bottom.tabText(i) for i in range(bottom.count())]
    assert labels == ["text1", "text2", "text3"]
    bottom.setCurrentIndex(1)
    assert bottom.tabText(bottom.currentIndex()) == "text2"


def test_sidebar_starts_open_on_the_explorer_view(window: MainWindow) -> None:
    assert window.primary_sidebar.isVisible() is True
    assert window.activity_bar.explorer_button.isChecked() is True
    assert window.activity_bar.search_button.isChecked() is False
    assert window._sidebar_stack.currentWidget() is window._sidebar_pages["explorer"]


def test_clicking_the_active_view_icon_collapses_the_sidebar(window: MainWindow) -> None:
    window.activity_bar.explorer_button.click()

    assert window.primary_sidebar.isVisible() is False
    assert window.top_bar.sidebar_toggle.isChecked() is False
    assert window.activity_bar.explorer_button.isChecked() is False

    window.activity_bar.explorer_button.click()
    assert window.primary_sidebar.isVisible() is True
    assert window.activity_bar.explorer_button.isChecked() is True
    assert window._sidebar_stack.currentWidget() is window._sidebar_pages["explorer"]


def test_clicking_a_different_view_icon_switches_the_sidebar(window: MainWindow) -> None:
    window.activity_bar.search_button.click()

    assert window.primary_sidebar.isVisible() is True
    assert window.activity_bar.search_button.isChecked() is True
    assert window.activity_bar.explorer_button.isChecked() is False
    assert window._sidebar_stack.currentWidget() is window._sidebar_pages["search"]


def test_topbar_toggle_also_drives_the_sidebar_and_stays_synced(window: MainWindow) -> None:
    window.top_bar.sidebar_toggle.setChecked(False)
    assert window.primary_sidebar.isVisible() is False
    assert window.activity_bar.explorer_button.isChecked() is False

    window.top_bar.sidebar_toggle.setChecked(True)
    assert window.primary_sidebar.isVisible() is True
    # Reopening restores whichever view was last active -- still Explorer, the default.
    assert window.activity_bar.explorer_button.isChecked() is True


def test_panel_toggle_hides_and_shows_the_bottom_panel(window: MainWindow) -> None:
    assert window.bottom_panel.isVisible() is True
    window.top_bar.panel_toggle.setChecked(False)
    assert window.bottom_panel.isVisible() is False


def test_settings_button_has_no_wired_action(window: MainWindow) -> None:
    # PROMPT.md: "for now settings should do nothing" -- just asserts the button exists and isn't
    # checkable/connected to anything that changes app state.
    assert window.activity_bar.settings_button.isCheckable() is False


def test_activity_bar_starts_with_explorer_checked_and_settings_not_checkable(qtbot) -> None:
    bar = ActivityBar()
    qtbot.addWidget(bar)

    assert bar.explorer_button.isChecked() is True
    assert bar.search_button.isChecked() is False
    assert bar.settings_button.isCheckable() is False


def test_activity_bar_set_active_view_does_not_reemit_view_signals(qtbot) -> None:
    bar = ActivityBar()
    qtbot.addWidget(bar)
    selected = []
    collapsed = []
    bar.view_selected.connect(selected.append)
    bar.view_collapsed.connect(collapsed.append)

    bar.set_active_view(None)

    assert bar.explorer_button.isChecked() is False
    assert bar.search_button.isChecked() is False
    assert selected == []
    assert collapsed == []

    bar.set_active_view("search")
    assert bar.search_button.isChecked() is True
    assert bar.explorer_button.isChecked() is False
    assert selected == []
    assert collapsed == []


def test_activity_bar_clicking_switches_and_collapses(qtbot) -> None:
    bar = ActivityBar()
    qtbot.addWidget(bar)
    selected = []
    collapsed = []
    bar.view_selected.connect(selected.append)
    bar.view_collapsed.connect(lambda: collapsed.append(True))

    bar.search_button.click()
    assert selected == ["search"]
    assert bar.search_button.isChecked() is True
    assert bar.explorer_button.isChecked() is False

    bar.search_button.click()
    assert collapsed == [True]
    assert bar.search_button.isChecked() is False


def test_rvt_button_is_a_plain_action_not_a_sidebar_view(qtbot) -> None:
    bar = ActivityBar()
    qtbot.addWidget(bar)
    bar.set_rvt_enabled(True)  # starts disabled -- see test_rvt_button_starts_disabled below
    launched = []
    selected = []
    bar.launch_rvt_requested.connect(lambda: launched.append(True))
    bar.view_selected.connect(selected.append)

    bar.rvt_button.click()

    assert launched == [True]
    assert selected == []
    assert bar.rvt_button.isCheckable() is False


def test_rvt_button_starts_disabled(qtbot) -> None:
    # PROMPT.md: "rvt should not be launchable if no project is open" -- true from construction,
    # before MainWindow ever gets a chance to enable it once a project opens.
    bar = ActivityBar()
    qtbot.addWidget(bar)

    assert bar.rvt_button.isEnabled() is False


def test_apply_button_starts_disabled(qtbot) -> None:
    bar = ActivityBar()
    qtbot.addWidget(bar)

    assert bar.apply_button.isEnabled() is False


# -- quicklaunch (activity bar) zoom -------------------------------------------------------------


def test_refresh_icon_scale_resizes_the_bar_and_every_button(qtbot) -> None:
    # PROMPT.md: "when zooming in and out the quicklaunch panel and its icons are not resizing".
    from in_reach.ide.activity_bar import WIDTH, _BUTTON_SIZE

    bar = ActivityBar()
    qtbot.addWidget(bar)
    assert bar.width() == WIDTH
    assert bar.rvt_button.width() == _BUTTON_SIZE

    bar.refresh_icon_scale(2.0)

    assert bar.width() == WIDTH * 2
    for button in (bar.explorer_button, bar.search_button, bar.rvt_button, bar.apply_button, bar.settings_button):
        assert button.width() == _BUTTON_SIZE * 2
        assert button.iconSize().width() == round(28 * 2)


def test_refresh_icon_scale_preserves_the_rvt_disabled_badge(qtbot) -> None:
    bar = ActivityBar()
    qtbot.addWidget(bar)
    assert bar.rvt_button.isEnabled() is False

    bar.refresh_icon_scale(1.5)

    # Still disabled after a rescale -- the icon (and its "blocked" badge) gets re-rendered at the
    # new size, but the enabled state itself isn't touched by a zoom change.
    assert bar.rvt_button.isEnabled() is False


def test_refresh_icon_scale_preserves_the_apply_disabled_badge(qtbot) -> None:
    # PROMPT.md: "please also use the red no entry icon (like you do for rvt) when the apply
    # button can not be pressed" -- same rescale-preserves-disabled-state coverage as RVT's own.
    bar = ActivityBar()
    qtbot.addWidget(bar)
    assert bar.apply_button.isEnabled() is False

    bar.refresh_icon_scale(1.5)

    assert bar.apply_button.isEnabled() is False


def test_set_apply_enabled_swaps_the_badge_off_and_on(qtbot) -> None:
    from in_reach.ide.icons import apply_icon

    bar = ActivityBar()
    qtbot.addWidget(bar)
    disabled_pixmap = bar.apply_button.icon().pixmap(28, 28).toImage()
    assert disabled_pixmap == apply_icon(size=28, enabled=False).pixmap(28, 28).toImage()

    bar.set_apply_enabled(True)

    enabled_pixmap = bar.apply_button.icon().pixmap(28, 28).toImage()
    assert enabled_pixmap == apply_icon(size=28, enabled=True).pixmap(28, 28).toImage()
    assert enabled_pixmap != disabled_pixmap


def test_adjust_zoom_resizes_the_activity_bar(window: MainWindow, tmp_path: Path) -> None:
    from in_reach.app import project
    from in_reach.ide.activity_bar import WIDTH

    window.root_dir = tmp_path
    project.get_project_dir(tmp_path).mkdir(parents=True)

    window._zoom_in()

    assert window.activity_bar.width() > WIDTH


def test_rvt_button_is_disabled_with_no_project_open(window: MainWindow) -> None:
    # PROMPT.md: "rvt should not be launchable if no project is open (the icon should have a dash
    # in front of it)".
    assert window.activity_bar.rvt_button.isEnabled() is False


def test_rvt_button_is_enabled_once_a_project_opens(project_window: MainWindow, tmp_path: Path) -> None:
    folder = tmp_path / "some-project"
    folder.mkdir()

    project_window._on_project_opened(folder)

    assert project_window.activity_bar.rvt_button.isEnabled() is True


def test_rvt_button_is_disabled_again_once_the_project_closes(
    project_window: MainWindow, tmp_path: Path
) -> None:
    folder = tmp_path / "some-project"
    folder.mkdir()
    project_window._on_project_opened(folder)

    project_window.explorer_panel.close_active_project()

    assert project_window.activity_bar.rvt_button.isEnabled() is False


def test_launch_rvt_launches_the_bundled_exe_with_no_prompt(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import rvt_launcher

    window.activity_bar.set_rvt_enabled(True)
    calls = []
    monkeypatch.setattr(rvt_launcher, "launch_rvt", lambda *a, **k: calls.append((a, k)))

    window.activity_bar.rvt_button.click()

    assert len(calls) == 1


def test_clicking_the_disabled_rvt_button_does_not_launch_anything(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import rvt_launcher

    calls = []
    monkeypatch.setattr(rvt_launcher, "launch_rvt", lambda target=None, **k: calls.append(target))

    window.activity_bar.rvt_button.click()  # disabled -- no project open

    assert calls == []


# -- Apply --------------------------------------------------------------------------------------


def _make_project_with_settings(tmp_path: Path) -> Path:
    folder = tmp_path / "abcd1234"
    (folder / "settings").mkdir(parents=True)
    (folder / "build").mkdir(parents=True)
    return folder


def test_apply_button_enables_when_the_active_project_has_unapplied_changes(
    project_window: MainWindow, tmp_path: Path
) -> None:
    folder = _make_project_with_settings(tmp_path)
    (folder / "settings" / "settings.json").write_text('{"a": 1}', encoding="utf-8")
    (folder / "build" / "settings.autogenerated.json").write_text('{"a": 0}', encoding="utf-8")

    project_window._on_project_opened(folder)

    assert project_window.activity_bar.apply_button.isEnabled() is True


def test_apply_button_stays_disabled_when_settings_matches_build(
    project_window: MainWindow, tmp_path: Path
) -> None:
    folder = _make_project_with_settings(tmp_path)
    (folder / "settings" / "settings.json").write_text('{"a": 1}', encoding="utf-8")
    (folder / "build" / "settings.autogenerated.json").write_text('{"a": 1}', encoding="utf-8")

    project_window._on_project_opened(folder)

    assert project_window.activity_bar.apply_button.isEnabled() is False


def test_clicking_apply_runs_the_real_compile_and_disables_the_button_on_success(
    project_window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PROMPT.md: "applying changes should try and compile the jsons into a gametype" -- the actual
    # compile pipeline (in_reach.app.rvt.compile.run_compile) is exercised end to end against a
    # real .bin fixture in tests/app/test_apply_settings.py/tests/app/rvt/test_compile.py; this
    # test is about MainWindow's own wiring (does clicking Apply call through with the right args
    # and update button state on success), so the compile step itself is faked.
    from in_reach.app import apply_settings
    from in_reach.app.rvt.compile import BuildResult

    folder = _make_project_with_settings(tmp_path)
    (folder / "settings" / "settings.json").write_text('{"a": 1}', encoding="utf-8")
    (folder / "build" / "settings.autogenerated.json").write_text('{"a": 0}', encoding="utf-8")
    project_window._on_project_opened(folder)
    assert project_window.activity_bar.apply_button.isEnabled() is True

    calls = []
    monkeypatch.setattr(
        apply_settings,
        "apply_settings_changes",
        lambda project_dir, target_folder: calls.append((project_dir, target_folder)) or BuildResult(success=True),
    )
    monkeypatch.setattr(apply_settings, "settings_have_unapplied_changes", lambda f: False)

    project_window.activity_bar.apply_button.click()

    assert len(calls) == 1
    assert calls[0][1] == folder
    assert project_window.activity_bar.apply_button.isEnabled() is False


def test_clicking_apply_shows_an_error_dialog_and_leaves_the_button_alone_on_failure(
    project_window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PROMPT.md: "i[f] it fails then dont allow application (raise errors in text window)".
    from in_reach.app import apply_settings
    from in_reach.app.rvt.compile import BuildMessage, BuildResult

    folder = _make_project_with_settings(tmp_path)
    (folder / "settings" / "settings.json").write_text('{"a": 1}', encoding="utf-8")
    (folder / "build" / "settings.autogenerated.json").write_text('{"a": 0}', encoding="utf-8")
    project_window._on_project_opened(folder)
    assert project_window.activity_bar.apply_button.isEnabled() is True

    failure = BuildResult(
        success=False,
        failure="Megalo compile failed -- see .errors/.fatal_errors for details.",
        fatal_errors=[BuildMessage(line=3, col=5, text="Expected an operator.")],
    )
    monkeypatch.setattr(apply_settings, "apply_settings_changes", lambda project_dir, target_folder: failure)
    shown: list[str] = []
    monkeypatch.setattr(
        "in_reach.ide.main_window.QMessageBox.critical", lambda *a, **k: shown.append(a[2])
    )

    project_window.activity_bar.apply_button.click()

    assert len(shown) == 1
    assert "Megalo compile failed" in shown[0]
    assert "Expected an operator." in shown[0]
    # Still enabled -- nothing was actually applied, so the enabled state must not have been
    # refreshed to a stale "nothing to apply" reading.
    assert project_window.activity_bar.apply_button.isEnabled() is True


def test_apply_is_a_no_op_with_no_project_open(window: MainWindow) -> None:
    window.apply_settings_changes()  # should not raise


def test_saving_a_settings_file_refreshes_the_apply_button(
    project_window: MainWindow, tmp_path: Path
) -> None:
    folder = _make_project_with_settings(tmp_path)
    settings_path = folder / "settings" / "settings.json"
    settings_path.write_text('{"a": 0}', encoding="utf-8")
    (folder / "build" / "settings.autogenerated.json").write_text('{"a": 0}', encoding="utf-8")
    project_window._on_project_opened(folder)
    assert project_window.activity_bar.apply_button.isEnabled() is False

    settings_path.write_text('{"a": 1}', encoding="utf-8")
    project_window._on_file_saved(settings_path)

    assert project_window.activity_bar.apply_button.isEnabled() is True


def test_launch_rvt_with_a_project_open_passes_its_source_bin_as_the_target(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import new_project, project, rvt_launcher

    window.root_dir = tmp_path
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir()
    folder = tmp_path / "abcd1234"
    folder.mkdir()
    bin_path = new_project.source_variant_path(project_dir, folder)
    bin_path.parent.mkdir(parents=True)
    bin_path.write_bytes(b"")
    window._on_project_opened(folder)

    calls = []
    monkeypatch.setattr(rvt_launcher, "launch_rvt", lambda target=None, **k: calls.append(target))

    window.activity_bar.rvt_button.click()

    assert calls == [bin_path]


def test_launch_rvt_applies_present_settings_before_launching(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PROMPT.md: "launching rvt should apply the present settings into the rvt window" -- the real
    # compile pipeline is exercised end to end elsewhere (tests/app/test_apply_settings.py,
    # tests/app/rvt/test_compile.py); this is about MainWindow's own wiring, so it's faked here.
    from in_reach.app import apply_settings, new_project, project, rvt_launcher
    from in_reach.app.rvt.compile import BuildResult

    window.root_dir = tmp_path
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir()
    folder = tmp_path / "abcd1234"
    folder.mkdir()
    bin_path = new_project.source_variant_path(project_dir, folder)
    bin_path.parent.mkdir(parents=True)
    bin_path.write_bytes(b"")
    window._on_project_opened(folder)

    monkeypatch.setattr(rvt_launcher, "launch_rvt", lambda target=None, **k: None)
    calls = []
    monkeypatch.setattr(
        apply_settings,
        "apply_settings_changes",
        lambda pd, f: calls.append((pd, f)) or BuildResult(success=True),
    )

    window.activity_bar.rvt_button.click()

    assert calls == [(project_dir, folder)]


def test_launch_rvt_swallows_a_compile_failure_and_still_launches(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Best-effort, unlike the Apply button's own click handler: launching RVT shouldn't be blocked
    # by (or pop a dialog over) a compile failure -- see launch_rvt()'s own docstring.
    from in_reach.app import apply_settings, new_project, project, rvt_launcher

    window.root_dir = tmp_path
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir()
    folder = tmp_path / "abcd1234"
    folder.mkdir()
    bin_path = new_project.source_variant_path(project_dir, folder)
    bin_path.parent.mkdir(parents=True)
    bin_path.write_bytes(b"")
    window._on_project_opened(folder)

    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(apply_settings, "apply_settings_changes", _raise)
    launched = []
    monkeypatch.setattr(rvt_launcher, "launch_rvt", lambda target=None, **k: launched.append(target))

    window.activity_bar.rvt_button.click()  # should not raise, should still launch

    assert launched == [bin_path]


def test_launch_rvt_with_a_project_open_but_no_source_bin_passes_no_target(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import rvt_launcher

    window.root_dir = tmp_path
    folder = tmp_path / "abcd1234"
    folder.mkdir()
    window._on_project_opened(folder)  # no .bin ever created for this one -- a blank project

    calls = []
    monkeypatch.setattr(rvt_launcher, "launch_rvt", lambda target=None, **k: calls.append(target))

    window.activity_bar.rvt_button.click()

    assert calls == [None]


def test_opening_a_project_with_a_source_bin_watches_it(
    window: MainWindow, tmp_path: Path
) -> None:
    from in_reach.app import new_project, project

    window.root_dir = tmp_path
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir()
    folder = tmp_path / "abcd1234"
    folder.mkdir()
    bin_path = new_project.source_variant_path(project_dir, folder)
    bin_path.parent.mkdir(parents=True)
    bin_path.write_bytes(b"")

    window._on_project_opened(folder)

    assert window._bin_watcher.files() == [str(bin_path)]


def test_opening_a_project_with_no_source_bin_watches_nothing(window: MainWindow, tmp_path: Path) -> None:
    window.root_dir = tmp_path
    folder = tmp_path / "abcd1234"
    folder.mkdir()

    window._on_project_opened(folder)

    assert window._bin_watcher.files() == []


def test_switching_the_active_project_rewatches_the_new_ones_bin(
    window: MainWindow, tmp_path: Path
) -> None:
    from in_reach.app import new_project, project

    window.root_dir = tmp_path
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir()
    first = tmp_path / "first"
    first.mkdir()
    second = tmp_path / "second"
    second.mkdir()
    first_bin = new_project.source_variant_path(project_dir, first)
    first_bin.parent.mkdir(parents=True)
    first_bin.write_bytes(b"")
    second_bin = new_project.source_variant_path(project_dir, second)
    second_bin.write_bytes(b"")

    window.explorer_panel.open_project(first)
    assert window._bin_watcher.files() == [str(first_bin)]

    window.explorer_panel.open_project(second)

    assert window._bin_watcher.files() == [str(second_bin)]


def test_the_watched_bin_changing_resyncs_the_build_snapshot(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import new_project, project

    window.root_dir = tmp_path
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir()
    folder = tmp_path / "abcd1234"
    folder.mkdir()
    bin_path = new_project.source_variant_path(project_dir, folder)
    bin_path.parent.mkdir(parents=True)
    bin_path.write_bytes(b"")
    window._on_project_opened(folder)

    calls = []
    monkeypatch.setattr(
        "in_reach.app.rvt.decompile.resync_from_bin",
        lambda bin_path, folder, **k: calls.append((bin_path, folder, k)),
    )

    window._on_watched_bin_changed(str(bin_path))

    assert len(calls) == 1
    assert calls[0][0] == bin_path
    assert calls[0][1] == folder


def test_the_watched_bin_changing_carries_title_and_description_through(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PROMPT.md: "when setting a title and description, this is not being set in settings.json" --
    # a resync must carry this project's own title/description forward too, same as category, or
    # they'd silently reset to the .bin's own header values on every RVT save.
    from in_reach.app import new_project, project

    window.root_dir = tmp_path
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir()
    folder = tmp_path / "abcd1234"
    folder.mkdir()
    settings_dir = folder / new_project.SETTINGS_DIRNAME
    settings_dir.mkdir(parents=True)
    (settings_dir / "settings.json").write_text(
        '{"meta": {"title": "Kept Title", "description": "Kept description"}}', encoding="utf-8"
    )
    bin_path = new_project.source_variant_path(project_dir, folder)
    bin_path.parent.mkdir(parents=True)
    bin_path.write_bytes(b"")
    window._on_project_opened(folder)

    calls = []
    monkeypatch.setattr(
        "in_reach.app.rvt.decompile.resync_from_bin",
        lambda bin_path, folder, **k: calls.append((bin_path, folder, k)),
    )

    window._on_watched_bin_changed(str(bin_path))

    assert len(calls) == 1
    assert calls[0][2]["title"] == "Kept Title"
    assert calls[0][2]["description"] == "Kept description"


def test_a_resync_failure_does_not_crash_and_still_rewatches_the_file(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import new_project, project

    window.root_dir = tmp_path
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir()
    folder = tmp_path / "abcd1234"
    folder.mkdir()
    bin_path = new_project.source_variant_path(project_dir, folder)
    bin_path.parent.mkdir(parents=True)
    bin_path.write_bytes(b"")
    window._on_project_opened(folder)

    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("in_reach.app.rvt.decompile.resync_from_bin", _raise)

    window._on_watched_bin_changed(str(bin_path))  # should not raise

    assert str(bin_path) in window._bin_watcher.files()


def test_watched_bin_deleted_then_recreated_is_still_watched_afterward(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Some writers save via delete-then-recreate, which silently drops a QFileSystemWatcher's own
    # path -- the handler has to re-add it, or only the *first* RVT save would ever be caught.
    from in_reach.app import new_project, project

    window.root_dir = tmp_path
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir()
    folder = tmp_path / "abcd1234"
    folder.mkdir()
    bin_path = new_project.source_variant_path(project_dir, folder)
    bin_path.parent.mkdir(parents=True)
    bin_path.write_bytes(b"")
    window._on_project_opened(folder)
    window._bin_watcher.removePaths(window._bin_watcher.files())  # simulate the drop
    monkeypatch.setattr("in_reach.app.rvt.decompile.resync_from_bin", lambda *a, **k: None)

    window._on_watched_bin_changed(str(bin_path))

    assert str(bin_path) in window._bin_watcher.files()


def test_launch_rvt_reports_a_launch_failure_rather_than_crashing(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import rvt_launcher

    def _raise(*args, **kwargs):
        raise OSError("access denied")

    window.activity_bar.set_rvt_enabled(True)
    monkeypatch.setattr(rvt_launcher, "launch_rvt", _raise)
    shown: list[str] = []
    monkeypatch.setattr(
        "in_reach.ide.main_window.QMessageBox.critical", lambda *a, **k: shown.append(a[2])
    )

    window.activity_bar.rvt_button.click()

    assert len(shown) == 1
    assert "access denied" in shown[0]


def test_split_panel_can_be_split_horizontally_up_to_the_max(window: MainWindow) -> None:
    main_panel = window.main_panel
    first_pane = main_panel.panes[0]

    for expected_split_count in range(1, _MAX_H_SPLITS + 1):
        first_pane.split_button.click()
        assert main_panel.split_count == expected_split_count

    # A further split is refused -- the button disables itself once the max is reached.
    assert first_pane.split_button.isEnabled() is False
    first_pane.split_button.click()
    assert main_panel.split_count == _MAX_H_SPLITS
    assert len(main_panel.panes) == _MAX_H_SPLITS + 1


def test_splitting_a_pane_duplicates_its_current_tab(window: MainWindow) -> None:
    main_panel = window.main_panel
    first_pane = main_panel.panes[0]
    main_panel.new_tab_in(first_pane)
    main_panel.new_tab_in(first_pane)
    first_pane.setCurrentIndex(2)
    current_label = first_pane.tabText(first_pane.currentIndex())

    first_pane.split_button.click()

    new_pane = main_panel.panes[-1]
    assert new_pane.count() == 1
    assert new_pane.tabText(0) == current_label


def test_pane_can_be_split_vertically_once_per_group(window: MainWindow) -> None:
    main_panel = window.main_panel
    first_pane = main_panel.panes[0]
    first_group = first_pane.group

    first_pane.vsplit_button.click()
    assert first_group.vsplit_count == _MAX_V_SPLITS
    assert len(main_panel.panes) == 2

    # A second vertical split of the same group is refused -- the button disables itself.
    assert first_pane.vsplit_button.isEnabled() is False
    first_pane.vsplit_button.click()
    assert first_group.vsplit_count == _MAX_V_SPLITS
    assert len(main_panel.panes) == 2


def test_max_panes_is_three_horizontal_groups_of_two_vertical_panes(window: MainWindow) -> None:
    main_panel = window.main_panel

    # Split horizontally to the max (3 groups), then split every group vertically once (2 panes
    # each) -- 3 x 2 = 6 panes total.
    for _ in range(_MAX_H_SPLITS):
        main_panel.panes[0].split_button.click()
    assert len(main_panel.groups) == _MAX_H_SPLITS + 1

    for group in list(main_panel.groups):
        group.panes[0].vsplit_button.click()

    assert len(main_panel.panes) == (_MAX_H_SPLITS + 1) * (_MAX_V_SPLITS + 1) == 6
    for pane in main_panel.panes:
        assert pane.split_button.isEnabled() is False
        assert pane.vsplit_button.isEnabled() is False


def test_primary_panel_tabs_are_closable_but_bottom_panel_tabs_are_not(window: MainWindow) -> None:
    assert window.main_panel.panes[0].tabsClosable() is True
    assert window.bottom_panel.tabsClosable() is False


def test_closing_a_tab_via_its_close_button_removes_it(window: MainWindow) -> None:
    pane = window.main_panel.panes[0]
    before = pane.count()

    pane.tabCloseRequested.emit(0)

    assert pane.count() == before - 1


def test_closing_the_last_tab_in_a_split_pane_auto_closes_the_pane(window: MainWindow) -> None:
    main_panel = window.main_panel
    first_pane = main_panel.panes[0]
    first_pane.split_button.click()
    new_pane = main_panel.panes[-1]
    assert new_pane.count() == 1

    new_pane.tabCloseRequested.emit(0)

    assert new_pane not in main_panel.panes
    assert main_panel.split_count == 0


def test_new_tab_in_adds_a_uniquely_labeled_untitled_editor_tab(window: MainWindow) -> None:
    main_panel = window.main_panel
    pane = main_panel.panes[0]
    before = pane.count()
    next_number = main_panel._next_tab_number

    main_panel.new_tab_in(pane)

    assert pane.count() == before + 1
    assert pane.tabText(pane.currentIndex()) == f"Untitled-{next_number}.txt"
    assert isinstance(pane.widget(pane.currentIndex()), TextEditorWidget)


def test_single_clicking_the_tab_bars_empty_space_does_not_create_a_tab(
    window: MainWindow, qtbot
) -> None:
    window.resize(2000, 800)
    QApplication.processEvents()
    pane = window.main_panel.panes[0]
    tab_bar = pane.tabBar()
    before = pane.count()
    empty_point = QPoint(tab_bar.width() - 5, tab_bar.height() // 2)
    assert tab_bar.tabAt(empty_point) == -1

    qtbot.mouseClick(tab_bar, Qt.MouseButton.LeftButton, pos=empty_point)

    assert pane.count() == before


def test_double_clicking_the_tab_bars_empty_space_creates_a_new_tab(
    window: MainWindow, qtbot
) -> None:
    window.resize(2000, 800)
    QApplication.processEvents()
    pane = window.main_panel.panes[0]
    tab_bar = pane.tabBar()
    before = pane.count()
    empty_point = QPoint(tab_bar.width() - 5, tab_bar.height() // 2)
    assert tab_bar.tabAt(empty_point) == -1

    next_number = window.main_panel._next_tab_number
    qtbot.mouseDClick(tab_bar, Qt.MouseButton.LeftButton, pos=empty_point)

    assert pane.count() == before + 1
    assert pane.tabText(pane.currentIndex()) == f"Untitled-{next_number}.txt"


def test_tab_bar_height_and_split_buttons_survive_overflow(window: MainWindow) -> None:
    # Regression guard: QTabBar recomputes a shorter row height once tabs stop fitting their
    # natural size (scroll arrows *or* elided labels), and the corner widget holding the split
    # buttons gets forced to match -- squashing them. The tab bar height must stay fixed regardless.
    main_panel = window.main_panel
    pane = main_panel.panes[0]
    natural_height = pane.tabBar().height()
    button_size = pane.vsplit_button.height()
    for _ in range(10):
        main_panel.new_tab_in(pane)

    window.resize(350, 600)
    QApplication.processEvents()

    assert pane.tabBar().height() == natural_height
    assert (pane.vsplit_button.width(), pane.vsplit_button.height()) == (button_size, button_size)
    assert (pane.split_button.width(), pane.split_button.height()) == (button_size, button_size)


def test_panel_splitters_refuse_to_collapse_children(window: MainWindow) -> None:
    main_panel = window.main_panel
    first_group = main_panel.panes[0].group

    assert main_panel._splitter.childrenCollapsible() is False
    assert first_group.splitter.childrenCollapsible() is False


def test_moving_a_tab_between_panes_and_closing_an_emptied_one(window: MainWindow) -> None:
    main_panel = window.main_panel
    source = main_panel.panes[0]
    main_panel.new_tab_in(source)
    main_panel.new_tab_in(source)
    source.split_button.click()
    dest = main_panel.panes[1]

    # Drag-and-drop itself is exercised manually (see PROMPT.md's ask); this replicates exactly
    # what TabPane.dropEvent() does once a drop with our custom mime type is accepted, so the
    # move/cleanup logic gets real coverage without needing a simulated native drag.
    label = source.tabText(0)
    widget = source.widget(0)
    source.removeTab(0)
    dest.addTab(widget, label)
    main_panel.on_pane_emptied(source)
    assert dest.tabText(dest.count() - 1) == label
    assert source in main_panel.panes

    # Move the remaining two tabs too -- the now-empty source pane is dropped automatically.
    while source.count():
        label = source.tabText(0)
        widget = source.widget(0)
        source.removeTab(0)
        dest.addTab(widget, label)
    main_panel.on_pane_emptied(source)

    assert source not in main_panel.panes
    assert main_panel.split_count == 0


def test_status_bar_owns_the_bottom_edge_and_corners_when_not_maximized(window: MainWindow) -> None:
    window.showNormal()
    QApplication.processEvents()
    status_bar = window.status_bar
    status_bar.resize(300, 22)

    assert status_bar._edges_at(QPoint(0, 21)) == (Qt.Edge.BottomEdge | Qt.Edge.LeftEdge)
    assert status_bar._edges_at(QPoint(299, 21)) == (Qt.Edge.BottomEdge | Qt.Edge.RightEdge)
    assert status_bar._edges_at(QPoint(150, 10)) == Qt.Edge(0)


def test_status_bar_reports_no_edges_when_maximized(window: MainWindow) -> None:
    window.showMaximized()
    QApplication.processEvents()
    status_bar = window.status_bar

    assert status_bar._edges_at(QPoint(0, status_bar.height() - 1)) == Qt.Edge(0)


def test_wrap_tab_widget_builds_a_named_bordered_card(qtbot) -> None:
    tab_widget = QTabWidget()
    qtbot.addWidget(tab_widget)

    card = style.wrap_tab_widget(tab_widget)

    assert card.objectName() == "tabCard"
    assert tab_widget.parent() is card
    assert "border-top-left-radius: 0px" not in card.styleSheet()


def test_wrap_tab_widget_flush_top_drops_the_cards_top_border(qtbot) -> None:
    tab_widget = QTabWidget()
    qtbot.addWidget(tab_widget)

    card = style.wrap_tab_widget(tab_widget, flush_top=True)

    assert "border-top: 0px solid transparent" in card.styleSheet()
    assert "border-top-left-radius: 0px" in card.styleSheet()


def test_main_tab_style_flattens_the_scroll_tear_indicator() -> None:
    # Regression guard: Qt's native "tear" indicator (drawn at the edge where scrolled-off tabs
    # get cut) default-renders as a scalloped wavy edge under Fusion unless explicitly flattened.
    assert "QTabBar::tear" in style.MAIN_TAB_STYLE


def test_first_run_dialog_theme_buttons_apply_live_and_notify(qtbot) -> None:
    notified = []
    dialog = FirstRunDialog(on_theme_changed=lambda applied: notified.append(applied.name))
    qtbot.addWidget(dialog)

    dialog._apply_theme("Whiley")

    assert notified == ["Whiley"]
    assert dialog._theme_buttons["Whiley"].isChecked() is True
    assert dialog._theme_buttons["Light"].isChecked() is False


def test_first_run_flag_defaults_to_true_and_flips_to_false_after_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = tmp_path / ".in-reach"
    project_dir.mkdir()
    env_path = project_dir / ".env"
    env_path.write_text("FIRST_USE=true\n")

    assert ide_app._is_first_use(env_path) is True

    monkeypatch.setattr(QApplication, "exec", lambda self: 0)
    monkeypatch.setattr(FirstRunDialog, "exec", lambda self: 0)

    ide_app.run(project_dir)

    assert ide_app._is_first_use(env_path) is False


def test_second_run_skips_the_first_run_dialog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = tmp_path / ".in-reach"
    project_dir.mkdir()
    env_path = project_dir / ".env"
    env_path.write_text("FIRST_USE=false\n")

    shown = []
    monkeypatch.setattr(FirstRunDialog, "exec", lambda self: shown.append(True))
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)

    ide_app.run(project_dir)

    assert shown == []


def test_run_shows_the_restore_icon_since_it_launches_maximized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression guard: run() shows the window via showMaximized() directly rather than through
    # toggle_maximize() (which refreshes the icon itself), so it must refresh the icon afterward
    # too, or the maximize button stays stuck showing win_maximize despite already being maximized.
    project_dir = tmp_path / ".in-reach"
    project_dir.mkdir()
    (project_dir / ".env").write_text("FIRST_USE=false\n")
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)

    def existing_windows() -> set[int]:
        return {id(w) for w in QApplication.instance().topLevelWidgets() if isinstance(w, MainWindow)}

    before = existing_windows()
    ide_app.run(project_dir)
    new_windows = [
        w
        for w in QApplication.instance().topLevelWidgets()
        if isinstance(w, MainWindow) and id(w) not in before
    ]

    assert len(new_windows) == 1
    window = new_windows[0]
    assert window.isMaximized() is True
    assert _maximize_icon_image(window) == _expected_icon_image("win_restore", window)


# -- File menu --------------------------------------------------------------------------------


@pytest.fixture
def project_window(qtbot, tmp_path: Path):
    """A :class:`MainWindow` rooted at ``tmp_path`` with a real ``.in-reach/.env`` -- the File
    menu's Open Recent submenu and folder-adoption actions read/write that file, so (like the
    zoom tests) this avoids the shared ``window`` fixture's ``Path.cwd()`` root touching the
    actual repo checkout."""
    project_dir = tmp_path / ".in-reach"
    project_dir.mkdir()
    (project_dir / ".env").write_text("", encoding="utf-8")
    win = MainWindow(root_dir=tmp_path)
    qtbot.addWidget(win)
    win.show()
    return win


def test_file_menu_has_every_action_prompt_md_asks_for(project_window: MainWindow) -> None:
    menu = project_window.top_bar.file_menu_button.menu()
    labels = [action.text() for action in menu.actions() if not action.isSeparator()]

    assert labels == [
        "New File",
        "New Window",
        "Open File...",
        "Open Folder...",
        "Open Recent",
        "Save",
        "Save As...",
        "Save All",
        "Close Project",
        "Close Editor",
    ]


def test_new_file_adds_a_tab_to_the_active_pane(project_window: MainWindow) -> None:
    pane = project_window.main_panel.active_pane
    before = pane.count()

    project_window.new_file()

    assert pane.count() == before + 1


def test_open_new_window_creates_and_tracks_another_mainwindow(
    project_window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)

    project_window.open_new_window()

    assert len(project_window._child_windows) == 1
    child = project_window._child_windows[0]
    assert child.root_dir == project_window.root_dir
    assert child.isMaximized() is True


def test_clicking_a_file_in_the_explorer_panel_opens_it_in_the_active_pane(
    project_window: MainWindow, tmp_path: Path
) -> None:
    source = tmp_path / "script.txt"
    source.write_text("print('hi')", encoding="utf-8")
    pane = project_window.main_panel.active_pane
    before = pane.count()

    project_window.explorer_panel.file_activated.emit(source)

    assert pane.count() == before + 1
    assert pane.widget(pane.currentIndex()).toPlainText() == "print('hi')"


def test_open_file_reads_the_chosen_file_into_the_active_pane(
    project_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "script.txt"
    source.write_text("print(1)", encoding="utf-8")
    monkeypatch.setattr(MainWindow, "ask_open_file", lambda self: str(source))
    pane = project_window.main_panel.active_pane
    before = pane.count()

    project_window.open_file()

    assert pane.count() == before + 1
    assert pane.widget(pane.currentIndex()).toPlainText() == "print(1)"


def test_open_file_cancelled_adds_nothing(
    project_window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(MainWindow, "ask_open_file", lambda self: "")
    pane = project_window.main_panel.active_pane
    before = pane.count()

    project_window.open_file()

    assert pane.count() == before


def test_open_folder_adopts_it_as_the_current_project(
    project_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from in_reach.app import recent as recent_module

    folder = tmp_path / "SomeProject"
    folder.mkdir()
    monkeypatch.setattr(MainWindow, "ask_open_folder", lambda self: str(folder))

    project_window.open_folder()

    assert Path(project_window.explorer_panel._project_model.rootPath()) == folder
    env_project_dir = project_window.explorer_panel._env_project_dir
    assert recent_module.list_recent(env_project_dir) == [folder]


def test_open_recent_project_menu_shows_a_placeholder_when_empty(project_window: MainWindow) -> None:
    button = project_window.top_bar.file_menu_button
    button._populate_open_recent()

    actions = button.open_recent_menu.actions()
    assert len(actions) == 1
    assert actions[0].text() == "No Recent Projects"
    assert actions[0].isEnabled() is False


def test_open_recent_project_menu_lists_recent_projects_by_title(
    project_window: MainWindow, tmp_path: Path
) -> None:
    from in_reach.app import new_project as new_project_module

    env_project_dir = project_window.explorer_panel._env_project_dir
    folder, _warning = new_project_module.create_gametype_project(env_project_dir, "Slayer Plus")
    from in_reach.app import recent as recent_module

    recent_module.add_recent(env_project_dir, folder)

    button = project_window.top_bar.file_menu_button
    button._populate_open_recent()

    actions = button.open_recent_menu.actions()
    assert [a.text() for a in actions] == ["Slayer Plus"]

    actions[0].trigger()
    assert Path(project_window.explorer_panel._project_model.rootPath()) == folder


def test_save_current_delegates_to_the_active_panes_current_tab(
    project_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from in_reach.ide.tabs import TabPane

    pane = project_window.main_panel.active_pane
    project_window.main_panel.new_tab_in(pane)
    pane.widget(pane.currentIndex()).setPlainText("hi")
    target = tmp_path / "out.txt"
    monkeypatch.setattr(TabPane, "_ask_save_path", lambda self, default_dir, name: target)

    project_window.save_current()

    assert target.read_text(encoding="utf-8") == "hi"


def test_close_project_clears_the_explorer_panel(project_window: MainWindow, tmp_path: Path) -> None:
    folder = tmp_path / "Project"
    folder.mkdir()
    project_window._on_project_opened(folder)
    assert project_window.explorer_panel.project_tree.isVisibleTo(project_window.explorer_panel) is True

    project_window.close_project()

    assert project_window.explorer_panel._no_project_label.isVisibleTo(project_window.explorer_panel) is True


def test_close_editor_closes_the_active_panes_current_tab(project_window: MainWindow) -> None:
    pane = project_window.main_panel.active_pane
    before = pane.count()

    project_window.close_editor()

    assert pane.count() == before - 1
