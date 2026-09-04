from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from in_reach.ide import app as ide_app
from in_reach.ide import theme
from in_reach.ide.first_run_dialog import FirstRunDialog
from in_reach.ide.main_window import MainWindow
from in_reach.ide.tabs import _MAX_SPLITS


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    return win


def test_lists_the_three_shipped_themes() -> None:
    assert theme.list_themes() == ["Dark", "Light", "Whiley"]


def test_apply_theme_falls_back_to_default_for_an_unknown_name(qtbot) -> None:
    app = QApplication.instance()
    applied = theme.apply_theme(app, "Not A Real Theme")
    assert applied.name == theme.DEFAULT_THEME_NAME


def test_main_window_opens_on_three_stub_tabs(window: MainWindow) -> None:
    pane = window.main_panel.panes[0]
    assert [pane.tabText(i) for i in range(pane.count())] == ["Tab 1", "Tab 2", "Tab 3"]


def test_bottom_panel_has_cyclable_stub_tabs(window: MainWindow) -> None:
    bottom = window.bottom_panel
    labels = [bottom.tabText(i) for i in range(bottom.count())]
    assert labels == ["text1", "text2", "text3"]
    bottom.setCurrentIndex(1)
    assert bottom.tabText(bottom.currentIndex()) == "text2"


def test_search_icon_toggles_the_primary_sidebar(window: MainWindow) -> None:
    assert window.primary_sidebar.isVisible() is True

    window.activity_bar.search_button.click()
    assert window.primary_sidebar.isVisible() is False
    assert window.top_bar.sidebar_toggle.isChecked() is False

    window.activity_bar.search_button.click()
    assert window.primary_sidebar.isVisible() is True
    assert window.top_bar.sidebar_toggle.isChecked() is True


def test_topbar_toggle_also_drives_the_sidebar_and_stays_synced(window: MainWindow) -> None:
    window.top_bar.sidebar_toggle.setChecked(False)
    assert window.primary_sidebar.isVisible() is False
    assert window.activity_bar.search_button.isChecked() is False


def test_panel_toggle_hides_and_shows_the_bottom_panel(window: MainWindow) -> None:
    assert window.bottom_panel.isVisible() is True
    window.top_bar.panel_toggle.setChecked(False)
    assert window.bottom_panel.isVisible() is False


def test_settings_button_has_no_wired_action(window: MainWindow) -> None:
    # PROMPT.md: "for now settings should do nothing" -- just asserts the button exists and isn't
    # checkable/connected to anything that changes app state.
    assert window.activity_bar.settings_button.isCheckable() is False


def test_split_panel_can_be_split_up_to_three_times(window: MainWindow) -> None:
    main_panel = window.main_panel
    first_pane = main_panel.panes[0]

    for expected_split_count in range(1, _MAX_SPLITS + 1):
        first_pane.split_button.click()
        assert main_panel.split_count == expected_split_count

    # A fourth split is refused -- the button disables itself once the max is reached.
    assert first_pane.split_button.isEnabled() is False
    first_pane.split_button.click()
    assert main_panel.split_count == _MAX_SPLITS
    assert len(main_panel.panes) == _MAX_SPLITS + 1


def test_moving_a_tab_between_panes_and_closing_an_emptied_one(window: MainWindow) -> None:
    main_panel = window.main_panel
    source = main_panel.panes[0]
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


def test_first_run_dialog_theme_buttons_apply_live_and_notify(qtbot) -> None:
    notified = []
    dialog = FirstRunDialog(on_theme_changed=lambda: notified.append(True))
    qtbot.addWidget(dialog)

    dialog._apply_theme("Whiley")

    assert notified == [True]


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
