from pathlib import Path

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QMessageBox, QTabWidget

from in_reach.app.rvt import rvt_bridge
from in_reach.ide import app as ide_app
from in_reach.ide import icons, style, theme
from in_reach.ide import zoom as zoom_module
from in_reach.ide.activity_bar import ActivityBar
from in_reach.ide.editor import TextEditorWidget
from in_reach.ide.first_run_dialog import FirstRunDialog
from in_reach.ide.main_window import _ICON_SIZE, _SIDEBAR_MIN_WIDTH, MainWindow
from in_reach.ide.tabs import _MAX_H_SPLITS, _MAX_V_SPLITS
from in_reach.ide.welcome import WelcomeTab

_NEEDS_NATIVE_RVT = pytest.mark.skipif(
    not rvt_bridge.is_available(), reason="native _reachvarianttool extension not available on this platform"
)


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    return win


def test_lists_the_three_shipped_themes() -> None:
    assert theme.list_themes() == ["Light", "Dark", "Whiley"]


def test_whiley_theme_matches_the_vs_red_png_reference() -> None:
    # PROMPT.md: "for the whiley theme, please make the colour scheme closer match vs_red.png
    # example" -- values sampled directly from that reference screenshot's own pixels (background/
    # sidebar/editor fill, the title-bar/selected-row/status-bar red accent, the toolbar button
    # fill, and the panel-divider color), not eyeballed. "window" was later brightened further --
    # "make the furthest background (the 'screen' on which panels lay on top) a brighter shade of
    # red" -- so it no longer matches that original sample on its own.
    whiley = theme.load_theme("Whiley")
    assert whiley.palette_colors["base"] == "#390000"
    assert whiley.palette_colors["highlight"] == "#770000"
    assert whiley.palette_colors["button"] == "#883333"
    assert whiley.palette_colors["mid"] == "#862424"
    assert whiley.status_bar_color == "#700000"


def test_whiley_theme_window_background_is_a_brighter_red_than_its_panels(qtbot) -> None:
    # "please make the furthest background (the 'screen' on which panels lay on top) a brighter
    # shade of red in whiley theme" -- the gap/outer background (QPalette Window) should read as a
    # visibly brighter red than the darker #330000 it used to share the same hue family with, and
    # brighter than the panel fill (Base) it sits behind.
    from PyQt6.QtGui import QColor

    whiley = theme.load_theme("Whiley")
    window_color = QColor(whiley.palette_colors["window"])
    base_color = QColor(whiley.palette_colors["base"])
    assert window_color.lightness() > QColor("#330000").lightness()
    assert window_color.lightness() > base_color.lightness()


def test_apply_theme_falls_back_to_default_for_an_unknown_name(qtbot) -> None:
    app = QApplication.instance()
    applied = theme.apply_theme(app, "Not A Real Theme")
    assert applied.name == theme.DEFAULT_THEME_NAME


def _assert_scoped_not_bare(sheet: str, object_name: str) -> None:
    """A *bare* (unscoped) ``background-color`` declaration in a widget's own local stylesheet
    (e.g. ``widget.setStyleSheet("background-color: X;")``) shadows the app-level ``QToolTip``
    stylesheet for every tooltip shown by that widget *or any descendant* -- confirmed in
    isolation: a plain widget with only a bare background-color stylesheet set makes a child's
    tooltip render with that background, regardless of the app-level QToolTip rule (see
    style.TOOLTIP_STYLE's own docstring). This is what made the activity bar's own tooltips
    render with its hardcoded #2c2c2c background instead of the current theme's tooltip colors
    (PROMPT.md: "the text help background needs to have contrast to the text help colour" / "the
    helper text has lo[st] its coloured background"). Asserting the stylesheet uses a real
    ``#objectName { ... }`` selector block (not a bare declaration) is a deterministic proxy for
    that fix -- actually rendering and grabbing a real OS tooltip popup in a test process turned
    out to depend on window-manager focus/activation this suite can't reliably control.
    """
    assert "background-color" in sheet
    assert f"#{object_name}" in sheet
    assert sheet.strip().startswith(f"QWidget#{object_name}") or f"#{object_name} {{" in sheet


def test_activity_bar_background_stylesheet_is_scoped_not_bare(qtbot) -> None:
    bar = ActivityBar()
    qtbot.addWidget(bar)
    assert bar.objectName() == "activityBar"
    _assert_scoped_not_bare(bar.styleSheet(), "activityBar")


def test_activity_bar_checked_buttons_get_a_grey_border_not_a_pale_fill(qtbot) -> None:
    # PROMPT.md: "icon backgrounds are becoming pale when selected in light theme[;] this is
    # undesirable, they should have a grey boarder when selected instead" -- overrides Fusion's
    # own default :checked fill (which follows the active theme's highlight color) with a fixed
    # grey border, so a checked view icon looks the same regardless of theme.
    from in_reach.ide.activity_bar import _CHECKED_BORDER_COLOR

    bar = ActivityBar()
    qtbot.addWidget(bar)
    sheet = bar.styleSheet()

    assert "QToolButton:checked" in sheet
    assert f"border: 1px solid {_CHECKED_BORDER_COLOR}" in sheet
    # The checked rule's own background must be transparent -- not a bare declaration elsewhere
    # that could shadow tooltip resolution (style.TOOLTIP_STYLE's own docstring) and not a
    # palette-driven fill that would still read as "pale" under Light.
    checked_rule_start = sheet.index("QToolButton:checked")
    checked_rule = sheet[checked_rule_start : sheet.index("}", checked_rule_start) + 1]
    assert "background-color: transparent" in checked_rule


def test_top_bar_background_stylesheet_is_scoped_not_bare(window: MainWindow) -> None:
    assert window.top_bar.objectName() == "topBar"
    _assert_scoped_not_bare(window.top_bar.styleSheet(), "topBar")


def test_primary_sidebar_background_stylesheet_is_scoped_not_bare(window: MainWindow) -> None:
    assert window.primary_sidebar.objectName() == "primarySidebar"
    _assert_scoped_not_bare(window.primary_sidebar.styleSheet(), "primarySidebar")


def test_status_bar_background_stylesheet_is_scoped_not_bare(window: MainWindow) -> None:
    window.status_bar.set_color("#007acc")

    assert window.status_bar.objectName() == "statusBar"
    _assert_scoped_not_bare(window.status_bar.styleSheet(), "statusBar")


def test_app_level_stylesheet_carries_the_shared_tooltip_style(qtbot) -> None:
    from in_reach.ide import style

    app = QApplication.instance()
    theme.apply_theme(app, "Light")

    assert style.TOOLTIP_STYLE in app.styleSheet()


def test_every_theme_has_readable_tooltip_contrast() -> None:
    # Regression guard: the Dark/Whiley themes used to define tooltip_base and tooltip_text as the
    # exact same color, making tooltip text invisible.
    for name in theme.list_themes():
        loaded = theme.load_theme(name)
        assert loaded.palette_colors["tooltip_base"] != loaded.palette_colors["tooltip_text"]


def test_every_theme_defines_a_placeholder_text_color_distinct_from_its_base(qtbot) -> None:
    # Regression guard: QPalette::PlaceholderText was never set per-theme, so a QLineEdit's own
    # placeholder ("My Gametype", "Optional", ...) fell back to Qt's compiled-in default (a color
    # picked for the stock light palette) regardless of the active theme -- unreadably dark against
    # the Dark/Whiley themes' own dark backgrounds ("background text is still dark/unreadable...
    # when creating new project").
    for name in theme.list_themes():
        loaded = theme.load_theme(name)
        assert "placeholder_text" in loaded.palette_colors
        palette = loaded.build_palette()
        placeholder = palette.color(QPalette.ColorRole.PlaceholderText)
        base = palette.color(QPalette.ColorRole.Base)
        assert placeholder != base
        assert abs(placeholder.lightness() - base.lightness()) > 20


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


def test_apply_theme_sets_a_menu_stylesheet_that_only_changes_background_on_selection(qtbot) -> None:
    # PROMPT.md: "for the drop down menu options, instead of changing highlighted text colour,
    # please apply background" -- QMenu::item:selected should pin color to the same
    # palette(window-text) every other state uses, so only the background changes.
    app = QApplication.instance()

    theme.apply_theme(app, "Dark")

    sheet = app.styleSheet()
    assert "QMenu::item:selected" in sheet
    assert "background-color: palette(highlight)" in sheet
    import re

    selected_rule = re.search(r"QMenu::item:selected\s*\{([^}]*)\}", sheet)
    assert selected_rule is not None
    assert "color: palette(window-text)" in selected_rule.group(1)


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

    assert window.status_bar.styleSheet() == f"QWidget#statusBar {{ background-color: {whiley.status_bar_color}; }}"


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


def test_sidebar_default_width_fits_the_dashboard_headers_without_eliding(
    window: MainWindow,
) -> None:
    # Regression guard (PROMPT.md): the sidebar's default/minimum width used to be narrow enough
    # that a section header's own text middle-elided. sizeHint() is exactly the width QToolButton
    # itself says it needs to show the whole label unelided, so the sidebar must never be narrower
    # than that.
    assert window.primary_sidebar.width() == _SIDEBAR_MIN_WIDTH
    for section in (
        window.explorer_panel.stats_section,
        window.explorer_panel.settings_section,
    ):
        assert section._toggle.sizeHint().width() < _SIDEBAR_MIN_WIDTH


def test_sidebar_default_width_fits_triple_digit_stats_counts_without_wrapping(
    window: MainWindow,
) -> None:
    # Regression guard (PROMPT.md): "fix the panel icon width so that trigger conditions and
    # actions should always display on the same line" -- sized against the widest this line is
    # ever realistically going to get (see explorer.py's own ExplorerPanel.__init__ comment).
    window.explorer_panel.stats_counts_label.setText("Triggers: 999   Conditions: 999   Actions: 999")

    assert window.explorer_panel.stats_counts_label.sizeHint().width() < _SIDEBAR_MIN_WIDTH


def test_sidebar_max_width_is_a_quarter_of_the_screen(window: MainWindow) -> None:
    # PROMPT.md: "dont allow [the sidebar to be] extendable more than 1/3 of the screen width",
    # later revised to 1/4 -- checked against the same constant main_window.py's own
    # _build_primary_sidebar() divides by, not a hardcoded fraction, so a later revision to that
    # constant doesn't leave this test silently checking the wrong ratio.
    from in_reach.ide.main_window import _SIDEBAR_MAX_WIDTH_FRACTION

    screen = QApplication.primaryScreen()
    assert window.primary_sidebar.maximumWidth() == screen.availableGeometry().width() // _SIDEBAR_MAX_WIDTH_FRACTION


def test_dragging_the_sidebar_wider_than_the_max_width_is_clamped(window: MainWindow) -> None:
    max_width = window.primary_sidebar.maximumWidth()

    window._side_splitter.setSizes([max_width + 500, 1000])
    QApplication.processEvents()

    assert window.primary_sidebar.width() <= max_width


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

    assert Path(project_window.explorer_panel._settings_model.rootPath()) == folder / "settings"


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


def test_bottom_panel_has_cyclable_stub_tabs(window: MainWindow) -> None:
    bottom = window.bottom_panel
    labels = [bottom.tabText(i) for i in range(bottom.count())]
    assert labels == ["text1", "text2", "text3"]
    bottom.setCurrentIndex(1)
    assert bottom.tabText(bottom.currentIndex()) == "text2"


# -- gating the sidebar views on a project being open --------------------------------------------


def test_sidebar_starts_collapsed_but_its_views_stay_clickable_with_no_project_open(
    window: MainWindow,
) -> None:
    # Dashboard/Locations/Search all have nothing but a "no project opened yet" placeholder to
    # show without one, so the sidebar starts collapsed -- but the view buttons (and the top bar's
    # own sidebar toggle) stay clickable, since clicking one still pops the sidebar open onto an
    # "Open a Project to use ..." placeholder (see the test below).
    assert window.primary_sidebar.isVisible() is False
    assert window.activity_bar.explorer_button.isEnabled() is True
    assert window.activity_bar.locations_button.isEnabled() is True
    assert window.activity_bar.search_button.isEnabled() is True
    assert window.top_bar.sidebar_toggle.isEnabled() is True


def test_clicking_a_view_with_no_project_open_pops_out_a_blank_placeholder(window: MainWindow) -> None:
    window.activity_bar.locations_button.click()

    assert window.primary_sidebar.isVisible() is True
    assert window._sidebar_stack.currentWidget() is window._no_project_page
    assert window._no_project_page._label.text() == "Open a Project to use Locations"

    window.activity_bar.search_button.click()

    assert window._sidebar_stack.currentWidget() is window._no_project_page
    assert window._no_project_page._label.text() == "Open a Project to use Search"

    window.activity_bar.explorer_button.click()

    assert window._sidebar_stack.currentWidget() is window._no_project_page
    assert window._no_project_page._label.text() == "Open a Project to use Dashboard"


def test_opening_the_first_project_reveals_the_dashboard(
    project_window: MainWindow, tmp_path: Path
) -> None:
    folder = tmp_path / "project"
    folder.mkdir()

    project_window._on_project_opened(folder)

    assert project_window.activity_bar.explorer_button.isEnabled() is True
    assert project_window.activity_bar.locations_button.isEnabled() is True
    assert project_window.activity_bar.search_button.isEnabled() is True
    assert project_window.top_bar.sidebar_toggle.isEnabled() is True
    # The panels were just unlocked -- reveals the Dashboard automatically rather than leaving the
    # user to notice the now-enabled icons themselves.
    assert project_window.primary_sidebar.isVisible() is True
    assert project_window.activity_bar.explorer_button.isChecked() is True
    assert project_window._sidebar_stack.currentWidget() is project_window._sidebar_pages["explorer"]


def test_opening_the_first_project_swaps_an_already_popped_out_blank_placeholder_for_the_dashboard(
    project_window: MainWindow, tmp_path: Path
) -> None:
    # Same "reveals the Dashboard automatically" behavior as opening the first project with the
    # sidebar fully collapsed -- a view popped open onto the blank placeholder beforehand isn't
    # special-cased to stay on that same view once a project actually exists.
    project_window.activity_bar.search_button.click()
    assert project_window._sidebar_stack.currentWidget() is project_window._no_project_page
    folder = tmp_path / "project"
    folder.mkdir()

    project_window._on_project_opened(folder)

    assert project_window._sidebar_stack.currentWidget() is project_window._sidebar_pages["explorer"]


def test_closing_the_last_project_collapses_the_sidebar_but_leaves_the_views_clickable(
    project_window: MainWindow, tmp_path: Path
) -> None:
    folder = tmp_path / "project"
    folder.mkdir()
    project_window._on_project_opened(folder)

    project_window.close_project()

    assert project_window.primary_sidebar.isVisible() is False
    assert project_window.activity_bar.explorer_button.isEnabled() is True
    assert project_window.activity_bar.locations_button.isEnabled() is True
    assert project_window.activity_bar.search_button.isEnabled() is True
    assert project_window.top_bar.sidebar_toggle.isEnabled() is True


def test_switching_between_two_open_projects_does_not_force_the_sidebar_back_open(
    project_window: MainWindow, tmp_path: Path
) -> None:
    # The has-project/no-project transition is what unlocks/reveals the sidebar -- switching
    # between two already-open projects (neither transition is "no project") must not re-open a
    # sidebar the user deliberately collapsed.
    first = tmp_path / "first"
    first.mkdir()
    second = tmp_path / "second"
    second.mkdir()
    project_window._on_project_opened(first)
    project_window._on_project_opened(second)
    project_window.activity_bar.explorer_button.click()  # user collapses it
    assert project_window.primary_sidebar.isVisible() is False

    project_window.explorer_panel.open_project(first)  # switch back to the first tab

    assert project_window.primary_sidebar.isVisible() is False


def test_clicking_the_active_view_icon_collapses_the_sidebar(
    project_window: MainWindow, tmp_path: Path
) -> None:
    folder = tmp_path / "project"
    folder.mkdir()
    project_window._on_project_opened(folder)
    assert project_window.primary_sidebar.isVisible() is True  # Dashboard opened automatically

    project_window.activity_bar.explorer_button.click()

    assert project_window.primary_sidebar.isVisible() is False
    assert project_window.top_bar.sidebar_toggle.isChecked() is False
    assert project_window.activity_bar.explorer_button.isChecked() is False

    project_window.activity_bar.explorer_button.click()
    assert project_window.primary_sidebar.isVisible() is True
    assert project_window.activity_bar.explorer_button.isChecked() is True
    assert project_window._sidebar_stack.currentWidget() is project_window._sidebar_pages["explorer"]


def test_clicking_a_different_view_icon_switches_the_sidebar(
    project_window: MainWindow, tmp_path: Path
) -> None:
    folder = tmp_path / "project"
    folder.mkdir()
    project_window._on_project_opened(folder)

    project_window.activity_bar.search_button.click()

    assert project_window.primary_sidebar.isVisible() is True
    assert project_window.activity_bar.search_button.isChecked() is True
    assert project_window.activity_bar.explorer_button.isChecked() is False
    assert project_window._sidebar_stack.currentWidget() is project_window._sidebar_pages["search"]


def test_clicking_the_locations_icon_switches_the_sidebar_to_the_stub_panel(
    project_window: MainWindow, tmp_path: Path
) -> None:
    # PROMPT.md: "please also add a side icon of a bookshelf (titled Locations) stub the panel
    # expanded view for now" -- a real sidebar-view toggle, same as Explorer/Search.
    folder = tmp_path / "project"
    folder.mkdir()
    project_window._on_project_opened(folder)

    project_window.activity_bar.locations_button.click()

    assert project_window.primary_sidebar.isVisible() is True
    assert project_window.activity_bar.locations_button.isChecked() is True
    assert project_window.activity_bar.explorer_button.isChecked() is False
    assert project_window._sidebar_stack.currentWidget() is project_window._sidebar_pages["locations"]
    assert project_window._sidebar_stack.currentWidget() is project_window.locations_panel


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


def test_help_button_has_no_wired_action(window: MainWindow) -> None:
    # PROMPT.md: "please then add a help (?) icon above the settings icon" -- stubbed, same
    # "does nothing yet" treatment as settings_button above.
    assert window.activity_bar.help_button.isCheckable() is False


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


def test_explorer_button_is_labeled_and_iconed_as_dashboard(qtbot) -> None:
    # PROMPT.md: "file explorer is renamed to dashboard (and the icon is changed to be a svg of
    # a dashboard)".
    from in_reach.ide import icons

    bar = ActivityBar()
    qtbot.addWidget(bar)

    assert bar.explorer_button.toolTip() == "Dashboard (toggle primary sidebar)"
    expected = icons.icon("dashboard", color="#cccccc", size=28).pixmap(28, 28).toImage()
    assert bar.explorer_button.icon().pixmap(28, 28).toImage() == expected


def test_refresh_icon_scale_keeps_the_dashboard_icon_not_the_old_explorer_one(qtbot) -> None:
    # Regression guard: refresh_icon_scale() used to re-render every _buttons-dict button's icon
    # from its own dict *key* ("explorer") rather than the icon name actually passed to
    # _bar_button() ("dashboard") -- a zoom change would silently revert the icon.
    from in_reach.ide import icons

    bar = ActivityBar()
    qtbot.addWidget(bar)

    bar.refresh_icon_scale(1.5)

    icon_size = round(28 * 1.5)
    expected = icons.icon("dashboard", color="#cccccc", size=icon_size).pixmap(icon_size, icon_size).toImage()
    assert bar.explorer_button.icon().pixmap(icon_size, icon_size).toImage() == expected


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


# -- reorderable icon strip (PROMPT.md: "please also move this arrow to the top of the icons,
# then rvt icon, then dashboard, then locations, then search (please also make them drag
# re-oderable by the user (should be saved in .env in .inreach))") -------------------------------


def test_activity_bar_default_icon_order(qtbot) -> None:
    bar = ActivityBar()
    qtbot.addWidget(bar)

    assert bar._icon_strip.order == ["compile", "rvt", "explorer", "locations", "search"]


def test_activity_bar_loads_a_persisted_order_from_env(qtbot, tmp_path: Path) -> None:
    from in_reach.app import env_file
    from in_reach.ide.activity_bar import ORDER_ENV_KEY

    env_path = tmp_path / ".env"
    env_file.update_env_value(env_path, ORDER_ENV_KEY, "search,explorer,rvt,locations,compile")

    bar = ActivityBar(env_path=env_path)
    qtbot.addWidget(bar)

    assert bar._icon_strip.order == ["search", "explorer", "rvt", "locations", "compile"]


def test_activity_bar_ignores_a_stale_persisted_order_gracefully(qtbot, tmp_path: Path) -> None:
    # A key that no longer names a real button (renamed/removed icon) is dropped rather than
    # crashing; any real button missing from the saved list (a newly-added icon, or one added
    # after the .env entry was written) is appended rather than just vanishing.
    from in_reach.app import env_file
    from in_reach.ide.activity_bar import ORDER_ENV_KEY

    env_path = tmp_path / ".env"
    env_file.update_env_value(env_path, ORDER_ENV_KEY, "search,not-a-real-icon,rvt")

    bar = ActivityBar(env_path=env_path)
    qtbot.addWidget(bar)

    order = bar._icon_strip.order
    assert order[:2] == ["search", "rvt"]
    assert set(order) == {"compile", "rvt", "explorer", "locations", "search"}


def test_activity_bar_with_no_env_path_does_not_persist_reordering(qtbot) -> None:
    bar = ActivityBar()
    qtbot.addWidget(bar)

    bar._icon_strip.order_changed.emit(["search", "rvt", "explorer", "locations", "compile"])  # should not raise


def test_reordering_the_icon_strip_persists_the_new_order_to_env(qtbot, tmp_path: Path) -> None:
    from in_reach.app import env_file
    from in_reach.ide.activity_bar import ORDER_ENV_KEY

    env_path = tmp_path / ".env"
    bar = ActivityBar(env_path=env_path)
    qtbot.addWidget(bar)

    new_order = ["search", "locations", "explorer", "rvt", "compile"]
    bar._icon_strip.order_changed.emit(new_order)

    assert env_file.get_env_values(env_path).get(ORDER_ENV_KEY) == ",".join(new_order)


def test_icon_strip_drop_reorders_the_dragged_button_to_the_drop_position(qtbot) -> None:
    from in_reach.ide.activity_bar import _IconStrip
    from PyQt6.QtCore import QMimeData, QPointF
    from PyQt6.QtCore import Qt as QtNS
    from PyQt6.QtGui import QDropEvent
    from PyQt6.QtWidgets import QToolButton

    strip = _IconStrip()
    qtbot.addWidget(strip)
    for key in ("a", "b", "c"):
        button = QToolButton()
        strip.add_button(key, button)
    strip.resize(50, 200)
    strip.show()

    seen_orders: list[list[str]] = []
    strip.order_changed.connect(seen_orders.append)

    mime = QMimeData()
    mime.setData("application/x-inreach-activitybar-icon", b"c")
    # Drop "c" above button "a" -- should move to the front.
    drop_pos = QPointF(strip._buttons["a"].geometry().center())
    drop_pos.setY(strip._buttons["a"].geometry().top())
    event = QDropEvent(
        drop_pos, QtNS.DropAction.MoveAction, mime, QtNS.MouseButton.LeftButton, QtNS.KeyboardModifier.NoModifier
    )
    strip.dropEvent(event)

    assert strip.order == ["c", "a", "b"]
    assert seen_orders == [["c", "a", "b"]]


def test_pressing_and_dragging_a_bar_button_past_the_threshold_starts_a_real_drag(
    qtbot, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression guard for PROMPT.md: "icons are not re-orderable" -- a QToolButton consumes its
    # own mouse press/move events, so _IconStrip's own mousePressEvent/mouseMoveEvent (the first
    # implementation) never actually fired for a press landing on one of its button children;
    # nothing ever started a drag for a real click-and-drag from the user. The fix watches each
    # button's events via an installed event filter instead -- this drives a real press-then-move
    # sequence through that filter (QDrag.exec() itself is mocked out, since it blocks on a real
    # OS drag-and-drop loop that has nothing to drop onto in a test).
    from in_reach.ide.activity_bar import _IconStrip
    from PyQt6.QtCore import QEvent, QPointF
    from PyQt6.QtGui import QDrag, QMouseEvent
    from PyQt6.QtWidgets import QToolButton

    strip = _IconStrip()
    qtbot.addWidget(strip)
    for key in ("a", "b", "c"):
        strip.add_button(key, QToolButton())
    strip.resize(50, 200)
    strip.show()
    button_a = strip._buttons["a"]

    started_with: list[bytes] = []

    def fake_exec(self, *args, **kwargs):
        started_with.append(bytes(self.mimeData().data("application/x-inreach-activitybar-icon")))
        return Qt.DropAction.MoveAction

    monkeypatch.setattr(QDrag, "exec", fake_exec)

    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(5, 5),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(button_a, press)
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(5, 40),  # well past QApplication.startDragDistance()
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(button_a, move)

    assert started_with == [b"a"]
    assert button_a.isDown() is False


def test_adjust_zoom_resizes_the_activity_bar(window: MainWindow, tmp_path: Path) -> None:
    from in_reach.app import project
    from in_reach.ide.activity_bar import WIDTH

    window.root_dir = tmp_path
    project.get_project_dir(tmp_path).mkdir(parents=True)

    window._zoom_in()

    assert window.activity_bar.width() > WIDTH


def test_adjust_zoom_keeps_an_open_settings_json_tab_at_110_percent(
    window: MainWindow, tmp_path: Path
) -> None:
    from in_reach.app import project

    window.root_dir = tmp_path
    project.get_project_dir(tmp_path).mkdir(parents=True)
    source = tmp_path / "settings.json"
    source.write_text("{}", encoding="utf-8")
    pane = window.main_panel.active_pane
    pane.open_file(source)
    editor = pane.widget(pane.currentIndex())

    window._zoom_in()

    # Zoom level itself is shared, clamped, cross-test global state (zoom_module's own module-level
    # baseline) -- this only asserts the +10% stays correctly pinned to whatever the live app font
    # ends up being after a zoom change, not any particular absolute size.
    app_size = QApplication.instance().font().pointSizeF()
    assert editor.font().pointSizeF() == pytest.approx(app_size * 1.1)


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


class _FakeRvtProcess:
    """A stand-in for :class:`subprocess.Popen` -- just enough of its interface (``poll()``/
    ``terminate()``) for :meth:`MainWindow._close_rvt_for_project` to drive."""

    def __init__(self) -> None:
        self.terminated = False

    def poll(self):
        return None if not self.terminated else 0

    def terminate(self) -> None:
        self.terminated = True


def test_closing_a_project_terminates_its_own_running_rvt_process(
    project_window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PROMPT.md: "if project is closed in ide, if Reach Variant tool is open for that project it
    # should be closed".
    from in_reach.app import rvt_launcher

    folder = tmp_path / "some-project"
    folder.mkdir()
    project_window._on_project_opened(folder)
    process = _FakeRvtProcess()
    monkeypatch.setattr(rvt_launcher, "launch_rvt", lambda *a, **k: process)

    project_window.launch_rvt()
    assert project_window._rvt_processes[folder] is process

    project_window.explorer_panel.close_active_project()

    assert process.terminated is True
    assert folder not in project_window._rvt_processes


def test_closing_a_project_with_no_rvt_launched_is_a_no_op(
    project_window: MainWindow, tmp_path: Path
) -> None:
    folder = tmp_path / "some-project"
    folder.mkdir()
    project_window._on_project_opened(folder)

    project_window.explorer_panel.close_active_project()  # should not raise


def test_closing_a_project_does_not_terminate_an_already_exited_rvt_process(
    project_window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import rvt_launcher

    folder = tmp_path / "some-project"
    folder.mkdir()
    project_window._on_project_opened(folder)
    process = _FakeRvtProcess()
    monkeypatch.setattr(rvt_launcher, "launch_rvt", lambda *a, **k: process)
    project_window.launch_rvt()
    process.terminated = True  # simulate it having exited on its own already

    project_window.explorer_panel.close_active_project()

    # terminate() is only called while poll() still reports "running" -- it was never called here,
    # so `terminated` stays exactly the sentinel value this test set, not flipped by a second call.
    assert process.terminated is True


def test_closing_a_different_project_does_not_terminate_this_ones_rvt_process(
    project_window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import rvt_launcher

    folder_a = tmp_path / "project-a"
    folder_a.mkdir()
    folder_b = tmp_path / "project-b"
    folder_b.mkdir()
    project_window._on_project_opened(folder_a)
    process = _FakeRvtProcess()
    monkeypatch.setattr(rvt_launcher, "launch_rvt", lambda *a, **k: process)
    project_window.launch_rvt()
    project_window._on_project_opened(folder_b)

    project_window.explorer_panel.close_project(folder_b)

    assert process.terminated is False
    assert project_window._rvt_processes[folder_a] is process


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


def test_clicking_apply_syncs_a_hand_edited_title_to_the_explorer_tab(
    project_window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PROMPT.md: "when a project name is changed [via rvt or] via apply settings.json change - the
    # project title should change in the tabs and in the breadcrumb".
    from in_reach.app import apply_settings
    from in_reach.app.rvt.compile import BuildResult

    folder = _make_project_with_settings(tmp_path)
    (folder / "settings" / "settings.json").write_text(
        '{"meta": {"title": "Hand-Edited Title"}}', encoding="utf-8"
    )
    project_window._on_project_opened(folder)

    monkeypatch.setattr(apply_settings, "apply_settings_changes", lambda project_dir, target_folder: BuildResult(success=True))

    project_window.apply_settings_changes()

    from in_reach.app import new_project

    assert new_project.read_project_title(folder) == "Hand-Edited Title"
    tab_index = project_window.explorer_panel.project_tabs.currentIndex()
    assert project_window.explorer_panel.project_tabs.tabText(tab_index) == "Hand-Edited Title"


def test_clicking_apply_arms_the_bin_watcher_once_a_compiled_bin_first_exists(
    project_window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No compiled .bin exists yet when the project is first opened (nothing's ever been applied),
    # so _rewatch_project_bin() (fired on project-open) has nothing to arm the watcher against --
    # a successful Apply needs to re-arm it itself, once build/dist/*.bin actually starts existing.
    from in_reach.app import apply_settings, new_project
    from in_reach.app.rvt.compile import BuildResult

    folder = _make_project_with_settings(tmp_path)
    project_window._on_project_opened(folder)
    assert project_window._bin_watcher.files() == []

    compiled_bin = new_project.compiled_variant_path(folder)

    def _fake_apply(project_dir, target_folder):
        compiled_bin.parent.mkdir(parents=True, exist_ok=True)
        compiled_bin.write_bytes(b"freshly compiled")
        return BuildResult(success=True)

    monkeypatch.setattr(apply_settings, "apply_settings_changes", _fake_apply)

    project_window.apply_settings_changes()

    assert project_window._bin_watcher.files() == [str(compiled_bin)]


# -- View Output.txt / Export RVT File (PROMPT.md: "Underneath project tabs please add the
# following buttons: Export RVT File (on the left) and on the right: View Output.txt") -----------


def test_view_output_txt_with_no_project_open_is_a_no_op(window: MainWindow) -> None:
    pane = window.main_panel.active_pane
    before = pane.count()

    window.view_output_txt()

    assert pane.count() == before


def test_view_output_txt_opens_a_locked_generated_view_of_the_script(
    project_window: MainWindow, tmp_path: Path
) -> None:
    folder = _make_project_with_settings(tmp_path)
    (folder / "script").mkdir(parents=True)
    (folder / "script" / "output.txt").write_text("do stuff\n", encoding="utf-8")
    project_window._on_project_opened(folder)
    pane = project_window.main_panel.active_pane

    project_window.view_output_txt()

    editor = pane.widget(pane.currentIndex())
    assert editor.isReadOnly() is True
    assert pane.tabIcon(pane.currentIndex()).isNull() is False  # the padlock icon
    text = editor.toPlainText()
    assert text.startswith("-- This file is auto-generated and non-editable")
    assert "do stuff" in text


def test_view_output_txt_refreshes_an_already_open_view_with_the_scripts_latest_content(
    project_window: MainWindow, tmp_path: Path
) -> None:
    folder = _make_project_with_settings(tmp_path)
    (folder / "script").mkdir(parents=True)
    script_path = folder / "script" / "output.txt"
    script_path.write_text("v1", encoding="utf-8")
    project_window._on_project_opened(folder)
    pane = project_window.main_panel.active_pane
    project_window.view_output_txt()
    index = pane.currentIndex()
    before = pane.count()

    script_path.write_text("v2", encoding="utf-8")
    project_window.view_output_txt()

    assert pane.count() == before  # switched to the existing tab, not duplicated
    assert pane.currentIndex() == index
    assert "v2" in pane.widget(index).toPlainText()
    assert "v1" not in pane.widget(index).toPlainText()


def test_export_rvt_file_with_no_project_open_is_a_no_op(window: MainWindow) -> None:
    window.export_rvt_file()  # should not raise


def test_export_rvt_file_prompts_to_compile_first_when_settings_have_unapplied_changes(
    project_window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import apply_settings

    folder = _make_project_with_settings(tmp_path)
    (folder / "settings" / "settings.json").write_text('{"a": 1}', encoding="utf-8")
    (folder / "build" / "settings.autogenerated.json").write_text('{"a": 0}', encoding="utf-8")
    project_window._on_project_opened(folder)
    prompted = []
    monkeypatch.setattr(MainWindow, "_confirm_compile_before_export", lambda self: prompted.append(True) or False)
    compile_calls = []
    monkeypatch.setattr(
        apply_settings, "apply_settings_changes", lambda pd, f: compile_calls.append((pd, f))
    )

    project_window.export_rvt_file()

    assert prompted == [True]
    assert compile_calls == []  # cancelled -- never even tried to compile


def test_export_rvt_file_compiles_after_confirming_the_compile_prompt(
    project_window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import apply_settings, new_project
    from in_reach.app.rvt.compile import BuildResult

    folder = _make_project_with_settings(tmp_path)
    (folder / "settings" / "settings.json").write_text('{"a": 1}', encoding="utf-8")
    (folder / "build" / "settings.autogenerated.json").write_text('{"a": 0}', encoding="utf-8")
    compiled_bin = new_project.compiled_variant_path(folder)

    def _fake_apply(project_dir, target_folder):
        compiled_bin.parent.mkdir(parents=True, exist_ok=True)
        compiled_bin.write_bytes(b"compiled")
        return BuildResult(success=True)

    monkeypatch.setattr(apply_settings, "apply_settings_changes", _fake_apply)
    monkeypatch.setattr(MainWindow, "_confirm_compile_before_export", lambda self: True)
    dest = tmp_path / "MySlayer.bin"
    monkeypatch.setattr(MainWindow, "ask_export_path", lambda self, default_path: str(dest))
    project_window._on_project_opened(folder)

    project_window.export_rvt_file()

    assert dest.read_bytes() == b"compiled"


def test_export_rvt_file_updates_the_apply_buttons_state_after_compiling(
    project_window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # "if a user clicks export rvt and has unsaved changes, then when changes are applied the
    # changes should be compiled (updating side icon panel)" -- export_rvt_file() used to compile
    # without ever re-checking the Apply button's own enabled state afterward, so the activity
    # bar's compile arrow kept reading as "changes pending" even once export had just applied them.
    from in_reach.app import apply_settings, new_project
    from in_reach.app.rvt.compile import BuildResult

    folder = _make_project_with_settings(tmp_path)
    settings_path = folder / "settings" / "settings.json"
    generated_path = folder / "build" / "settings.autogenerated.json"
    settings_path.write_text('{"a": 1}', encoding="utf-8")
    generated_path.write_text('{"a": 0}', encoding="utf-8")
    compiled_bin = new_project.compiled_variant_path(folder)

    def _fake_apply(project_dir, target_folder):
        compiled_bin.parent.mkdir(parents=True, exist_ok=True)
        compiled_bin.write_bytes(b"compiled")
        generated_path.write_text(settings_path.read_text(encoding="utf-8"), encoding="utf-8")
        return BuildResult(success=True)

    monkeypatch.setattr(apply_settings, "apply_settings_changes", _fake_apply)
    monkeypatch.setattr(MainWindow, "_confirm_compile_before_export", lambda self: True)
    dest = tmp_path / "MySlayer.bin"
    monkeypatch.setattr(MainWindow, "ask_export_path", lambda self, default_path: str(dest))
    project_window._on_project_opened(folder)
    assert project_window.activity_bar.apply_button.isEnabled() is True  # unapplied to start

    project_window.export_rvt_file()

    assert project_window.activity_bar.apply_button.isEnabled() is False


def test_export_rvt_file_does_not_prompt_when_settings_already_match_the_last_build(
    project_window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import apply_settings, new_project
    from in_reach.app.rvt.compile import BuildResult

    folder = _make_project_with_settings(tmp_path)
    (folder / "settings" / "settings.json").write_text('{"a": 1}', encoding="utf-8")
    (folder / "build" / "settings.autogenerated.json").write_text('{"a": 1}', encoding="utf-8")
    compiled_bin = new_project.compiled_variant_path(folder)

    def _fake_apply(project_dir, target_folder):
        compiled_bin.parent.mkdir(parents=True, exist_ok=True)
        compiled_bin.write_bytes(b"compiled")
        return BuildResult(success=True)

    monkeypatch.setattr(apply_settings, "apply_settings_changes", _fake_apply)

    def _fail_if_prompted(self):
        pytest.fail("should not have prompted -- nothing unapplied")

    monkeypatch.setattr(MainWindow, "_confirm_compile_before_export", _fail_if_prompted)
    dest = tmp_path / "MySlayer.bin"
    monkeypatch.setattr(MainWindow, "ask_export_path", lambda self, default_path: str(dest))
    project_window._on_project_opened(folder)

    project_window.export_rvt_file()

    assert dest.read_bytes() == b"compiled"


def test_export_rvt_file_shows_an_error_and_stops_when_compiling_fails(
    project_window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import apply_settings
    from in_reach.app.rvt.compile import BuildResult

    folder = _make_project_with_settings(tmp_path)
    project_window._on_project_opened(folder)
    monkeypatch.setattr(
        apply_settings, "apply_settings_changes", lambda project_dir, target_folder: BuildResult(success=False, failure="nope")
    )
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: shown.append(a[2]) or None))
    asked = []
    monkeypatch.setattr(MainWindow, "ask_export_path", lambda self, default_path: asked.append(default_path) or "")

    project_window.export_rvt_file()

    assert len(shown) == 1
    assert asked == []  # never even got to the Save As dialog


def test_export_rvt_file_cancelled_dialog_does_nothing(
    project_window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import apply_settings, new_project
    from in_reach.app.rvt.compile import BuildResult

    folder = _make_project_with_settings(tmp_path)
    compiled_bin = new_project.compiled_variant_path(folder)

    def _fake_apply(project_dir, target_folder):
        compiled_bin.parent.mkdir(parents=True, exist_ok=True)
        compiled_bin.write_bytes(b"compiled")
        return BuildResult(success=True)

    monkeypatch.setattr(apply_settings, "apply_settings_changes", _fake_apply)
    monkeypatch.setattr(MainWindow, "ask_export_path", lambda self, default_path: "")
    project_window._on_project_opened(folder)

    project_window.export_rvt_file()  # should not raise, nothing written anywhere else


def test_export_rvt_file_as_bin_copies_the_freshly_compiled_variant(
    project_window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import apply_settings, new_project
    from in_reach.app.rvt.compile import BuildResult

    folder = _make_project_with_settings(tmp_path)
    compiled_bin = new_project.compiled_variant_path(folder)

    def _fake_apply(project_dir, target_folder):
        compiled_bin.parent.mkdir(parents=True, exist_ok=True)
        compiled_bin.write_bytes(b"compiled bytes")
        return BuildResult(success=True)

    monkeypatch.setattr(apply_settings, "apply_settings_changes", _fake_apply)
    dest = tmp_path / "MySlayer.bin"
    monkeypatch.setattr(MainWindow, "ask_export_path", lambda self, default_path: str(dest))
    project_window._on_project_opened(folder)

    project_window.export_rvt_file()

    assert dest.read_bytes() == b"compiled bytes"


def test_export_rvt_file_as_mglo_calls_write_mglo_with_the_compiled_bin_and_script(
    project_window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import apply_settings, new_project
    from in_reach.app.rvt import mglo
    from in_reach.app.rvt.compile import BuildResult

    folder = _make_project_with_settings(tmp_path)
    (folder / "script").mkdir(parents=True)
    compiled_bin = new_project.compiled_variant_path(folder)

    def _fake_apply(project_dir, target_folder):
        compiled_bin.parent.mkdir(parents=True, exist_ok=True)
        compiled_bin.write_bytes(b"compiled")
        return BuildResult(success=True)

    monkeypatch.setattr(apply_settings, "apply_settings_changes", _fake_apply)
    dest = tmp_path / "MySlayer.mglo"
    monkeypatch.setattr(MainWindow, "ask_export_path", lambda self, default_path: str(dest))
    calls = []
    monkeypatch.setattr(mglo, "write_mglo", lambda bin_path, script_path, dest_path: calls.append((bin_path, script_path, dest_path)) or True)
    project_window._on_project_opened(folder)

    project_window.export_rvt_file()

    assert calls == [(compiled_bin, folder / "script" / "output.txt", dest)]


def test_export_rvt_file_as_mglo_reports_an_error_when_write_mglo_fails(
    project_window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import apply_settings, new_project
    from in_reach.app.rvt import mglo
    from in_reach.app.rvt.compile import BuildResult

    folder = _make_project_with_settings(tmp_path)
    compiled_bin = new_project.compiled_variant_path(folder)

    def _fake_apply(project_dir, target_folder):
        compiled_bin.parent.mkdir(parents=True, exist_ok=True)
        compiled_bin.write_bytes(b"compiled")
        return BuildResult(success=True)

    monkeypatch.setattr(apply_settings, "apply_settings_changes", _fake_apply)
    dest = tmp_path / "MySlayer.mglo"
    monkeypatch.setattr(MainWindow, "ask_export_path", lambda self, default_path: str(dest))
    monkeypatch.setattr(mglo, "write_mglo", lambda bin_path, script_path, dest_path: False)
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: shown.append(a[2]) or None))
    project_window._on_project_opened(folder)

    project_window.export_rvt_file()

    assert len(shown) == 1
    assert not dest.exists()


def _recent_button_labels(welcome) -> list[str]:
    return [welcome._recent_layout.itemAt(i).widget().text() for i in range(1, welcome._recent_layout.count())]


def test_a_rename_refreshes_the_open_welcome_tabs_recent_list(
    project_window: MainWindow, tmp_path: Path
) -> None:
    # PROMPT.md: "when a project is renamed, it needs to be renamed in recents in dropdown and in
    # the welcome window".
    from in_reach.app import project, recent
    from in_reach.ide.welcome import WelcomeTab

    folder = _make_project_with_settings(tmp_path)
    (folder / "settings" / "settings.json").write_text('{"meta": {"title": "Old Title"}}', encoding="utf-8")
    env_project_dir = project.get_project_dir(project_window.root_dir)
    recent.add_recent(env_project_dir, folder)

    welcome = project_window.main_panel.active_pane.widget(0)
    assert isinstance(welcome, WelcomeTab)
    welcome.refresh()  # populate the Recent list with the stale title first
    assert any("Old Title" in label for label in _recent_button_labels(welcome))

    (folder / "settings" / "settings.json").write_text('{"meta": {"title": "New Title"}}', encoding="utf-8")
    project_window._sync_project_title(folder)

    labels = _recent_button_labels(welcome)
    assert any("New Title" in label for label in labels)
    assert not any("Old Title" in label for label in labels)


def test_a_rename_shows_the_new_title_in_open_recent_next_time_its_opened(
    project_window: MainWindow, tmp_path: Path
) -> None:
    from in_reach.app import project, recent

    folder = _make_project_with_settings(tmp_path)
    (folder / "settings" / "settings.json").write_text('{"meta": {"title": "New Title"}}', encoding="utf-8")
    env_project_dir = project.get_project_dir(project_window.root_dir)
    recent.add_recent(env_project_dir, folder)

    project_window._sync_project_title(folder)

    button = project_window.top_bar.file_menu_button
    button._populate_open_recent()
    actions = button.open_recent_menu.actions()
    assert [a.text() for a in actions] == ["New Title"]


def test_status_bar_shows_the_active_projects_title_and_folder_id(
    project_window: MainWindow, tmp_path: Path
) -> None:
    # PROMPT.md: "please remove the dir location string (under the tabs section) and move that
    # information into the bottom bar (in the centre): it should read test (uuid)"
    folder = _make_project_with_settings(tmp_path)
    (folder / "settings" / "settings.json").write_text('{"meta": {"title": "Slayer Plus"}}', encoding="utf-8")

    project_window._on_project_opened(folder)

    assert project_window.status_bar._project_label.text() == f"Slayer Plus ({folder.name})"


def test_status_bar_clears_the_project_label_once_the_project_closes(
    project_window: MainWindow, tmp_path: Path
) -> None:
    folder = _make_project_with_settings(tmp_path)
    project_window._on_project_opened(folder)

    project_window.close_project()

    assert project_window.status_bar._project_label.text() == ""


def test_status_bar_project_label_updates_after_a_rename(project_window: MainWindow, tmp_path: Path) -> None:
    folder = _make_project_with_settings(tmp_path)
    (folder / "settings" / "settings.json").write_text('{"meta": {"title": "Old Title"}}', encoding="utf-8")
    project_window._on_project_opened(folder)

    (folder / "settings" / "settings.json").write_text('{"meta": {"title": "New Title"}}', encoding="utf-8")
    project_window._sync_project_title(folder)

    assert project_window.status_bar._project_label.text() == f"New Title ({folder.name})"


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


def test_launch_rvt_with_a_project_open_passes_its_compiled_bin_as_the_target(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import new_project, project, rvt_launcher

    window.root_dir = tmp_path
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir()
    folder = tmp_path / "abcd1234"
    folder.mkdir()
    bin_path = new_project.compiled_variant_path(folder)
    bin_path.parent.mkdir(parents=True)
    bin_path.write_bytes(b"")
    window._on_project_opened(folder)

    calls = []
    monkeypatch.setattr(rvt_launcher, "launch_rvt", lambda target=None, **k: calls.append(target))

    window.activity_bar.rvt_button.click()

    assert calls == [bin_path]


def test_launch_rvt_opens_the_compiled_bin_not_the_frozen_source_one(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PROMPT.md: "when clicking into rvt, it seems to be showing blank gametype and description
    # not the contents from the saved settings" -- launch_rvt() used to hand RVT the project's
    # frozen init_gametype/ source .bin (never touched again after project creation) instead of
    # build/dist/'s freshly-compiled one, so RVT always opened onto whatever the project started
    # from, never anything actually saved into settings/ since.
    from in_reach.app import apply_settings, new_project, project, rvt_launcher
    from in_reach.app.rvt.compile import BuildResult

    window.root_dir = tmp_path
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir()
    folder = tmp_path / "abcd1234"
    folder.mkdir()
    source_bin = new_project.source_variant_path(project_dir, folder)
    source_bin.parent.mkdir(parents=True)
    source_bin.write_bytes(b"stale original variant")
    compiled_bin = new_project.compiled_variant_path(folder)
    compiled_bin.parent.mkdir(parents=True)
    compiled_bin.write_bytes(b"freshly compiled variant with saved settings")
    window._on_project_opened(folder)
    # A real compile isn't exercised here (see test_launch_rvt_applies_present_settings_before_
    # launching for that) -- faked so it can't overwrite compiled_bin's own distinguishing content.
    monkeypatch.setattr(
        apply_settings, "apply_settings_changes", lambda pd, f: BuildResult(success=True)
    )
    calls = []
    monkeypatch.setattr(rvt_launcher, "launch_rvt", lambda target=None, **k: calls.append(target))

    window.activity_bar.rvt_button.click()

    assert calls == [compiled_bin]
    assert calls[0] != source_bin


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
    bin_path = new_project.compiled_variant_path(folder)
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


def test_launch_rvt_refuses_when_a_settings_json_tab_has_unsaved_edits(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import new_project, project, rvt_launcher

    window.root_dir = tmp_path
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir()
    folder = tmp_path / "abcd1234"
    settings_dir = folder / new_project.SETTINGS_DIRNAME
    settings_dir.mkdir(parents=True)
    settings_path = settings_dir / "settings.json"
    settings_path.write_text('{"meta": {"title": "Old"}}', encoding="utf-8")
    bin_path = new_project.compiled_variant_path(folder)
    bin_path.parent.mkdir(parents=True)
    bin_path.write_bytes(b"")
    window._on_project_opened(folder)
    window.main_panel.active_pane.open_file(settings_path)
    widget = window.main_panel.active_pane.widget(window.main_panel.active_pane.currentIndex())
    widget.setPlainText("hand-edited, unsaved")
    widget.document().setModified(True)

    launch_calls = []
    monkeypatch.setattr(rvt_launcher, "launch_rvt", lambda target=None, **k: launch_calls.append(target))
    warned = []
    monkeypatch.setattr(MainWindow, "_warn_unsaved_settings_before_rvt", lambda self, names: warned.append(names))

    window.launch_rvt()

    assert launch_calls == []
    assert warned == [["settings.json"]]


def test_launch_rvt_proceeds_once_the_dirty_settings_tab_is_saved(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import apply_settings, new_project, project, rvt_launcher
    from in_reach.app.rvt.compile import BuildResult

    window.root_dir = tmp_path
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir()
    folder = tmp_path / "abcd1234"
    settings_dir = folder / new_project.SETTINGS_DIRNAME
    settings_dir.mkdir(parents=True)
    settings_path = settings_dir / "settings.json"
    settings_path.write_text('{"meta": {"title": "Old"}}', encoding="utf-8")
    bin_path = new_project.compiled_variant_path(folder)
    bin_path.parent.mkdir(parents=True)
    bin_path.write_bytes(b"")
    window._on_project_opened(folder)
    window.main_panel.active_pane.open_file(settings_path)
    widget = window.main_panel.active_pane.widget(window.main_panel.active_pane.currentIndex())
    widget.setPlainText('{"meta": {"title": "Old"}}')
    widget.document().setModified(False)  # a clean, already-open tab

    monkeypatch.setattr(apply_settings, "apply_settings_changes", lambda pd, f: BuildResult(success=True))
    launch_calls = []
    monkeypatch.setattr(rvt_launcher, "launch_rvt", lambda target=None, **k: launch_calls.append(target))

    window.launch_rvt()

    assert launch_calls == [bin_path]


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
    bin_path = new_project.compiled_variant_path(folder)
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


def test_launch_rvt_with_a_project_open_but_no_compiled_bin_passes_no_target(
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


def test_opening_a_project_with_a_compiled_bin_watches_it(
    window: MainWindow, tmp_path: Path
) -> None:
    from in_reach.app import new_project, project

    window.root_dir = tmp_path
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir()
    folder = tmp_path / "abcd1234"
    folder.mkdir()
    bin_path = new_project.compiled_variant_path(folder)
    bin_path.parent.mkdir(parents=True)
    bin_path.write_bytes(b"")

    window._on_project_opened(folder)

    assert window._bin_watcher.files() == [str(bin_path)]


def test_opening_a_project_with_no_compiled_bin_watches_nothing(window: MainWindow, tmp_path: Path) -> None:
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
    first_bin = new_project.compiled_variant_path(first)
    first_bin.parent.mkdir(parents=True)
    first_bin.write_bytes(b"")
    second_bin = new_project.compiled_variant_path(second)
    second_bin.parent.mkdir(parents=True)
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
    bin_path = new_project.compiled_variant_path(folder)
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


def test_the_watched_bin_changing_carries_category_forward_but_not_title(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PROMPT.md: "when a project name is changed via rvt ... the project title should change in
    # the tabs and in the breadcrumb" -- a resync must let a rename typed into RVT's own header
    # flow through, so unlike category (never a .bin concept at all, so it's still read back from
    # the existing settings.json and carried forward), title/description are deliberately left
    # unset here rather than pinned to whatever settings.json said before this save.
    from in_reach.app import new_project, project
    from in_reach.app.categories import EngineCategory, EngineIcon

    window.root_dir = tmp_path
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir()
    folder = tmp_path / "abcd1234"
    folder.mkdir()
    settings_dir = folder / new_project.SETTINGS_DIRNAME
    settings_dir.mkdir(parents=True)
    (settings_dir / "settings.json").write_text(
        '{"meta": {"title": "Old Title", "description": "Old description",'
        ' "category": "juggernaut", "category_icon": "juggernaut"}}',
        encoding="utf-8",
    )
    bin_path = new_project.compiled_variant_path(folder)
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
    assert calls[0][2]["category"] == EngineCategory.juggernaut
    assert calls[0][2]["category_icon"] == EngineIcon.juggernaut
    assert "title" not in calls[0][2]
    assert "description" not in calls[0][2]


def test_the_watched_bin_changing_syncs_a_renamed_title_to_the_explorer_tab(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import new_project, project

    window.root_dir = tmp_path
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir()
    folder = tmp_path / "abcd1234"
    folder.mkdir()
    settings_dir = folder / new_project.SETTINGS_DIRNAME
    settings_dir.mkdir(parents=True)
    bin_path = new_project.compiled_variant_path(folder)
    bin_path.parent.mkdir(parents=True)
    bin_path.write_bytes(b"")
    window._on_project_opened(folder)

    def _fake_resync(bin_path, folder, **k):
        (settings_dir / "settings.json").write_text(
            '{"meta": {"title": "RVT Renamed"}}', encoding="utf-8"
        )

    monkeypatch.setattr("in_reach.app.rvt.decompile.resync_from_bin", _fake_resync)

    window._on_watched_bin_changed(str(bin_path))

    assert new_project.read_project_title(folder) == "RVT Renamed"
    tab_index = window.explorer_panel.project_tabs.currentIndex()
    assert window.explorer_panel.project_tabs.tabText(tab_index) == "RVT Renamed"


def test_a_resync_failure_does_not_crash_and_still_rewatches_the_file(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import new_project, project

    window.root_dir = tmp_path
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir()
    folder = tmp_path / "abcd1234"
    folder.mkdir()
    bin_path = new_project.compiled_variant_path(folder)
    bin_path.parent.mkdir(parents=True)
    bin_path.write_bytes(b"")
    window._on_project_opened(folder)

    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("in_reach.app.rvt.decompile.resync_from_bin", _raise)

    window._on_watched_bin_changed(str(bin_path))  # should not raise

    assert str(bin_path) in window._bin_watcher.files()


def test_watched_bin_changing_reloads_a_clean_open_settings_tab_in_place(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PROMPT.md: "any open script_settings.json, settings.json, or strings.json without saved
    # changes should immediately update in place".
    from in_reach.app import new_project, project

    window.root_dir = tmp_path
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir()
    folder = tmp_path / "abcd1234"
    folder.mkdir()
    settings_dir = folder / new_project.SETTINGS_DIRNAME
    settings_dir.mkdir(parents=True)
    settings_path = settings_dir / "settings.json"
    settings_path.write_text('{"meta": {"title": "Old"}}', encoding="utf-8")
    bin_path = new_project.compiled_variant_path(folder)
    bin_path.parent.mkdir(parents=True)
    bin_path.write_bytes(b"")
    window._on_project_opened(folder)
    window.main_panel.active_pane.open_file(settings_path)
    index = window.main_panel.active_pane.currentIndex()

    def _fake_resync(bin_path, folder, **k):
        settings_path.write_text('{"meta": {"title": "RVT Renamed"}}', encoding="utf-8")

    monkeypatch.setattr("in_reach.app.rvt.decompile.resync_from_bin", _fake_resync)
    prompted = []
    monkeypatch.setattr(
        MainWindow, "_confirm_overwrite_rvt_changes", lambda self, names: prompted.append(names) or True
    )

    window._on_watched_bin_changed(str(bin_path))

    assert prompted == []  # never asked -- the tab wasn't dirty
    assert window.main_panel.active_pane.widget(index).toPlainText() == '{"meta": {"title": "RVT Renamed"}}'


def test_watched_bin_changing_prompts_before_overwriting_a_dirty_settings_tab(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PROMPT.md: "any of the above with unsaved changes should pop up showing all unsaved changes
    # and asking whether to confirm overwrite or abort reach variant tool save".
    from in_reach.app import new_project, project

    window.root_dir = tmp_path
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir()
    folder = tmp_path / "abcd1234"
    folder.mkdir()
    settings_dir = folder / new_project.SETTINGS_DIRNAME
    settings_dir.mkdir(parents=True)
    settings_path = settings_dir / "settings.json"
    settings_path.write_text('{"meta": {"title": "Old"}}', encoding="utf-8")
    bin_path = new_project.compiled_variant_path(folder)
    bin_path.parent.mkdir(parents=True)
    bin_path.write_bytes(b"")
    window._on_project_opened(folder)
    window.main_panel.active_pane.open_file(settings_path)
    index = window.main_panel.active_pane.currentIndex()
    widget = window.main_panel.active_pane.widget(index)
    widget.setPlainText("hand-edited, unsaved")
    widget.document().setModified(True)

    resync_calls = []
    monkeypatch.setattr(
        "in_reach.app.rvt.decompile.resync_from_bin", lambda *a, **k: resync_calls.append(True)
    )
    prompted = []
    monkeypatch.setattr(
        MainWindow, "_confirm_overwrite_rvt_changes", lambda self, names: prompted.append(names) or False
    )

    window._on_watched_bin_changed(str(bin_path))

    assert prompted == [["settings.json"]]
    assert resync_calls == []  # aborted -- the resync never ran
    assert widget.toPlainText() == "hand-edited, unsaved"  # untouched


def test_watched_bin_changing_overwrites_a_dirty_settings_tab_when_confirmed(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import new_project, project

    window.root_dir = tmp_path
    project_dir = project.get_project_dir(tmp_path)
    project_dir.mkdir()
    folder = tmp_path / "abcd1234"
    folder.mkdir()
    settings_dir = folder / new_project.SETTINGS_DIRNAME
    settings_dir.mkdir(parents=True)
    settings_path = settings_dir / "settings.json"
    settings_path.write_text('{"meta": {"title": "Old"}}', encoding="utf-8")
    bin_path = new_project.compiled_variant_path(folder)
    bin_path.parent.mkdir(parents=True)
    bin_path.write_bytes(b"")
    window._on_project_opened(folder)
    window.main_panel.active_pane.open_file(settings_path)
    index = window.main_panel.active_pane.currentIndex()
    widget = window.main_panel.active_pane.widget(index)
    widget.setPlainText("hand-edited, unsaved")
    widget.document().setModified(True)

    def _fake_resync(bin_path, folder, **k):
        settings_path.write_text('{"meta": {"title": "RVT Renamed"}}', encoding="utf-8")

    monkeypatch.setattr("in_reach.app.rvt.decompile.resync_from_bin", _fake_resync)
    monkeypatch.setattr(MainWindow, "_confirm_overwrite_rvt_changes", lambda self, names: True)

    window._on_watched_bin_changed(str(bin_path))

    assert widget.toPlainText() == '{"meta": {"title": "RVT Renamed"}}'
    assert widget.document().isModified() is False


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
    bin_path = new_project.compiled_variant_path(folder)
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


def test_status_bar_set_project_label_updates_and_clears_the_centered_text(window: MainWindow) -> None:
    status_bar = window.status_bar
    assert status_bar._project_label.text() == ""

    status_bar.set_project_label("Slayer Plus (abcd1234)")

    assert status_bar._project_label.text() == "Slayer Plus (abcd1234)"

    status_bar.set_project_label("")

    assert status_bar._project_label.text() == ""


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


def test_settings_cog_opens_the_settings_dialog(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.ide.settings_dialog import SettingsDialog

    opened = []
    monkeypatch.setattr(SettingsDialog, "exec", lambda self: opened.append(self) or 0)

    window.activity_bar.settings_button.click()

    assert len(opened) == 1
    assert isinstance(opened[0], SettingsDialog)


def test_settings_dialog_theme_change_updates_the_main_window_chrome(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.ide.settings_dialog import SettingsDialog

    captured: list[SettingsDialog] = []

    def _capture_and_close(self):
        captured.append(self)
        return 0

    monkeypatch.setattr(SettingsDialog, "exec", _capture_and_close)

    window.open_settings_dialog()

    dialog = captured[0]
    dialog.theme_tab.theme_picker.apply_theme("Whiley")

    # on_theme_applied() (MainWindow's own theme-change hook, passed as SettingsDialog's
    # on_theme_changed) re-colors the status bar to match -- confirms the dialog's Theme tab is
    # actually wired to it, not just applying the palette in isolation.
    assert "#700000" in window.status_bar.styleSheet()


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
        "New Window",
        "Load Welcome Tab",
        "Open Folder...",
        "Open Recent",
        "Save",
        "Save All",
        "Close Project",
        "Close Editor",
    ]


def test_open_welcome_tab_switches_to_the_existing_one(project_window: MainWindow) -> None:
    pane = project_window.main_panel.active_pane
    before = pane.count()  # the panel opens on a Welcome tab already
    project_window.main_panel.new_tab_in(pane)  # switch away from it first
    assert not isinstance(pane.widget(pane.currentIndex()), WelcomeTab)

    project_window.open_welcome_tab()

    assert pane.count() == before + 1  # switched to the existing Welcome tab, not a new one
    assert isinstance(pane.widget(pane.currentIndex()), WelcomeTab)


def test_open_welcome_tab_reopens_one_after_it_was_closed(project_window: MainWindow) -> None:
    pane = project_window.main_panel.active_pane
    pane._close_tab(0)  # closes the initial Welcome tab
    before = pane.count()

    project_window.open_welcome_tab()

    assert pane.count() == before + 1
    assert isinstance(pane.widget(pane.currentIndex()), WelcomeTab)


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


def test_open_folder_adopts_it_as_the_current_project(
    project_window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from in_reach.app import project, recent as recent_module

    folder = tmp_path / "SomeProject"
    folder.mkdir()
    monkeypatch.setattr(MainWindow, "ask_open_folder", lambda self: str(folder))

    project_window.open_folder()

    assert Path(project_window.explorer_panel._settings_model.rootPath()) == folder / "settings"
    env_project_dir = project.get_project_dir(project_window.root_dir)
    assert recent_module.list_recent(env_project_dir) == [folder]


def test_open_recent_project_menu_shows_a_placeholder_when_empty(project_window: MainWindow) -> None:
    button = project_window.top_bar.file_menu_button
    button._populate_open_recent()

    actions = button.open_recent_menu.actions()
    assert len(actions) == 1
    assert actions[0].text() == "No Recent Projects"
    assert actions[0].isEnabled() is False


@_NEEDS_NATIVE_RVT
def test_open_recent_project_menu_lists_recent_projects_by_title(
    project_window: MainWindow, tmp_path: Path
) -> None:
    from in_reach.app import new_project as new_project_module
    from in_reach.app import project as project_module
    from in_reach.app.blank_variant import resolve_blank_variant

    env_project_dir = project_module.get_project_dir(project_window.root_dir)
    folder, warning = new_project_module.create_gametype_project(
        env_project_dir, "Slayer Plus", source_variant=resolve_blank_variant(firefight=False)
    )
    assert warning is None
    from in_reach.app import recent as recent_module

    recent_module.add_recent(env_project_dir, folder)

    button = project_window.top_bar.file_menu_button
    button._populate_open_recent()

    actions = button.open_recent_menu.actions()
    assert [a.text() for a in actions] == ["Slayer Plus"]

    actions[0].trigger()
    assert Path(project_window.explorer_panel._settings_model.rootPath()) == folder / "settings"


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
    assert project_window.explorer_panel.settings_section.isVisibleTo(project_window.explorer_panel) is True

    project_window.close_project()

    assert project_window.explorer_panel._no_project_label.isVisibleTo(project_window.explorer_panel) is True


def test_close_editor_closes_the_active_panes_current_tab(project_window: MainWindow) -> None:
    pane = project_window.main_panel.active_pane
    before = pane.count()

    project_window.close_editor()

    assert pane.count() == before - 1
