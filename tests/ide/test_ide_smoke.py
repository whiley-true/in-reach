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
from in_reach.ide.main_window import _ICON_SIZE, MainWindow
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

    assert app.style().objectName().lower() == "fusion"
    dark = theme.load_theme("Dark")
    for key, color_hex in dark.palette_colors.items():
        role = theme._PALETTE_ROLES.get(key)
        if role is not None:
            assert app.palette().color(role) == QColor(color_hex)
    assert applied.name == "Dark"


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
    window: MainWindow, tmp_path: Path
) -> None:
    folder = tmp_path / "some-project"
    folder.mkdir()

    welcome = window.main_panel.panes[0].widget(0)
    welcome.project_opened.emit(folder)

    assert Path(window.explorer_panel._project_model.rootPath()) == folder


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
    launched = []
    selected = []
    bar.launch_rvt_requested.connect(lambda: launched.append(True))
    bar.view_selected.connect(selected.append)

    bar.rvt_button.click()

    assert launched == [True]
    assert selected == []
    assert bar.rvt_button.isCheckable() is False


def test_launch_rvt_launches_the_bundled_exe_with_no_prompt(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import rvt_launcher

    calls = []
    monkeypatch.setattr(rvt_launcher, "launch_rvt", lambda *a, **k: calls.append((a, k)))

    window.activity_bar.rvt_button.click()

    assert len(calls) == 1


def test_launch_rvt_reports_a_launch_failure_rather_than_crashing(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    from in_reach.app import rvt_launcher

    def _raise(*args, **kwargs):
        raise OSError("access denied")

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
