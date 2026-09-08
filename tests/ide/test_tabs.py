from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication, QLabel, QMenu, QMessageBox, QTabBar

import in_reach
from in_reach.ide import icons
from in_reach.ide import tabs as tabs_module
from in_reach.ide.main_window import MainWindow
from in_reach.ide.tabs import (
    _MAX_H_SPLITS,
    _TAB_CLOSE_ICON_COLOR,
    _TAB_CLOSE_ICON_SIZE,
    MainPanelArea,
    TabPane,
    _SaveChoice,
    _TabState,
)
from in_reach.ide.welcome import WelcomeTab


@pytest.fixture
def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    return win


def _close_icon_image(button):
    return button.icon().pixmap(_TAB_CLOSE_ICON_SIZE, _TAB_CLOSE_ICON_SIZE).toImage()


def _tab_by_text(pane, text: str):
    for i in range(pane.count()):
        if pane.tabText(i) == text:
            return pane.widget(i)
    raise AssertionError(f"no tab labeled {text!r}")


def _expected_icon_image(name: str):
    return icons.icon(name, color=_TAB_CLOSE_ICON_COLOR, size=_TAB_CLOSE_ICON_SIZE).pixmap(
        _TAB_CLOSE_ICON_SIZE, _TAB_CLOSE_ICON_SIZE
    ).toImage()


# -- dirty-state close icon -----------------------------------------------------------------


def test_dirty_tab_shows_a_dot_and_clean_tab_shows_the_close_x(window: MainWindow) -> None:
    main_panel = window.main_panel
    pane = main_panel.panes[0]
    main_panel.new_tab_in(pane)
    index = pane.currentIndex()
    editor = pane.widget(index)
    button = pane.tabBar().tabButton(index, QTabBar.ButtonPosition.RightSide)

    assert _close_icon_image(button) == _expected_icon_image("win_close")

    editor.document().setModified(True)
    assert _close_icon_image(button) == _expected_icon_image("tab_dirty")

    editor.document().setModified(False)
    assert _close_icon_image(button) == _expected_icon_image("win_close")


# -- close routing / save prompt --------------------------------------------------------------


def test_closing_a_clean_tab_does_not_prompt_to_save(window: MainWindow, monkeypatch) -> None:
    pane = window.main_panel.panes[0]
    prompted = []
    monkeypatch.setattr(
        TabPane, "_ask_save_choice", lambda self, label: prompted.append(label) or _SaveChoice.CANCEL
    )
    before = pane.count()

    pane.tabCloseRequested.emit(0)

    assert prompted == []
    assert pane.count() == before - 1


def test_cancelling_the_save_prompt_keeps_the_dirty_tab_open(window: MainWindow, monkeypatch) -> None:
    main_panel = window.main_panel
    pane = main_panel.panes[0]
    main_panel.new_tab_in(pane)
    index = pane.currentIndex()
    pane.widget(index).document().setModified(True)
    monkeypatch.setattr(TabPane, "_ask_save_choice", lambda self, label: _SaveChoice.CANCEL)
    before = pane.count()

    result = pane._maybe_close(index)

    assert result is False
    assert pane.count() == before


def test_dont_save_discards_changes_and_closes(window: MainWindow, monkeypatch) -> None:
    main_panel = window.main_panel
    pane = main_panel.panes[0]
    main_panel.new_tab_in(pane)
    index = pane.currentIndex()
    pane.widget(index).setPlainText("hello")
    pane.widget(index).document().setModified(True)
    monkeypatch.setattr(TabPane, "_ask_save_choice", lambda self, label: _SaveChoice.DISCARD)
    before = pane.count()

    result = pane._maybe_close(index)

    assert result is True
    assert pane.count() == before - 1


def test_save_choice_writes_via_save_as_retitles_and_closes(
    window: MainWindow, monkeypatch, tmp_path: Path
) -> None:
    main_panel = window.main_panel
    pane = main_panel.panes[0]
    main_panel.new_tab_in(pane)
    index = pane.currentIndex()
    widget = pane.widget(index)
    widget.setPlainText("hello world")
    widget.document().setModified(True)
    target = tmp_path / "my_gametype.txt"
    monkeypatch.setattr(TabPane, "_ask_save_choice", lambda self, label: _SaveChoice.SAVE)
    monkeypatch.setattr(TabPane, "_ask_save_path", lambda self, default_dir, name: target)

    result = pane._maybe_close(index)

    assert result is True
    assert target.read_text(encoding="utf-8") == "hello world"


def test_save_as_cancelled_keeps_the_tab_open(window: MainWindow, monkeypatch) -> None:
    main_panel = window.main_panel
    pane = main_panel.panes[0]
    main_panel.new_tab_in(pane)
    index = pane.currentIndex()
    pane.widget(index).document().setModified(True)
    monkeypatch.setattr(TabPane, "_ask_save_choice", lambda self, label: _SaveChoice.SAVE)
    monkeypatch.setattr(TabPane, "_ask_save_path", lambda self, default_dir, name: None)
    before = pane.count()

    result = pane._maybe_close(index)

    assert result is False
    assert pane.count() == before


def test_saving_an_already_saved_tab_does_not_reprompt_for_a_path(
    window: MainWindow, monkeypatch, tmp_path: Path
) -> None:
    main_panel = window.main_panel
    pane = main_panel.panes[0]
    main_panel.new_tab_in(pane)
    index = pane.currentIndex()
    widget = pane.widget(index)
    widget.setPlainText("v1")
    target = tmp_path / "gametype.txt"
    pane._tab_state_for(widget).path = target
    prompted = []
    monkeypatch.setattr(
        TabPane, "_ask_save_path", lambda self, *a: prompted.append(True) or None
    )

    assert pane._save_tab(index) is True
    assert target.read_text(encoding="utf-8") == "v1"
    assert prompted == []


def test_save_failure_reports_the_error_and_keeps_the_tab_open(
    window: MainWindow, monkeypatch, tmp_path: Path
) -> None:
    main_panel = window.main_panel
    pane = main_panel.panes[0]
    main_panel.new_tab_in(pane)
    index = pane.currentIndex()
    pane.widget(index).document().setModified(True)
    monkeypatch.setattr(TabPane, "_ask_save_choice", lambda self, label: _SaveChoice.SAVE)
    monkeypatch.setattr(TabPane, "_ask_save_path", lambda self, default_dir, name: tmp_path / "f.txt")

    def _raise(self, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", _raise)
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    before = pane.count()

    result = pane._maybe_close(index)

    assert result is False
    assert pane.count() == before


# -- bulk close (pin exemption) -----------------------------------------------------------------


def test_close_others_skips_pinned_tabs(window: MainWindow) -> None:
    main_panel = window.main_panel
    pane = main_panel.panes[0]
    main_panel.new_tab_in(pane)
    main_panel.new_tab_in(pane)
    pane._toggle_pin(0)  # pin the Welcome tab

    pane._close_others(2)

    labels = [pane.tabText(i) for i in range(pane.count())]
    assert labels == ["Welcome", "Untitled-2.txt"]


def test_close_to_the_right_skips_pinned_tabs(window: MainWindow) -> None:
    main_panel = window.main_panel
    pane = main_panel.panes[0]
    main_panel.new_tab_in(pane)  # Untitled-1
    main_panel.new_tab_in(pane)  # Untitled-2
    main_panel.new_tab_in(pane)  # Untitled-3
    # Pinning both groups them at the front: Untitled-2@0, Untitled-3@1, Welcome@2, Untitled-1@3.
    pane._toggle_pin(pane.indexOf(_tab_by_text(pane, "Untitled-2.txt")))
    pane._toggle_pin(pane.indexOf(_tab_by_text(pane, "Untitled-3.txt")))

    # Everything to the right of the first pinned tab closes, except the other pinned one.
    pane._close_to_the_right(0)

    labels = [pane.tabText(i) for i in range(pane.count())]
    assert labels == ["Untitled-2.txt", "Untitled-3.txt"]


def test_close_saved_only_closes_non_dirty_tabs(window: MainWindow) -> None:
    main_panel = window.main_panel
    pane = main_panel.panes[0]
    main_panel.new_tab_in(pane)
    dirty_widget = pane.widget(pane.currentIndex())
    dirty_widget.document().setModified(True)

    pane._close_saved()

    assert pane.count() == 1
    assert pane.widget(0) is dirty_widget


def test_close_all_skips_pinned_tabs(window: MainWindow) -> None:
    main_panel = window.main_panel
    pane = main_panel.panes[0]
    pane._toggle_pin(0)
    main_panel.new_tab_in(pane)

    pane._close_all()

    assert pane.count() == 1
    assert pane.tabText(0) == "Welcome"


# -- pin --------------------------------------------------------------------------------------


def test_pinning_groups_pinned_tabs_at_the_front(window: MainWindow) -> None:
    main_panel = window.main_panel
    pane = main_panel.panes[0]
    main_panel.new_tab_in(pane)
    main_panel.new_tab_in(pane)
    untitled_2 = pane.widget(2)

    pane._toggle_pin(pane.indexOf(untitled_2))

    assert pane.tabText(0) == "Untitled-2.txt"
    welcome = pane.widget(1)
    pane._toggle_pin(pane.indexOf(welcome))

    assert pane._tab_state_for(untitled_2).pinned is True
    assert pane._tab_state_for(welcome).pinned is True
    assert {pane.tabText(0), pane.tabText(1)} == {"Untitled-2.txt", "Welcome"}


def test_unpinning_leaves_the_tab_in_place(window: MainWindow) -> None:
    pane = window.main_panel.panes[0]

    pane._toggle_pin(0)
    assert pane._tab_state_for(pane.widget(0)).pinned is True

    pane._toggle_pin(0)
    assert pane._tab_state_for(pane.widget(0)).pinned is False


# -- copy / reveal path actions -----------------------------------------------------------------


def test_copy_path_and_copy_relative_path_use_the_clipboard(window: MainWindow, tmp_path: Path) -> None:
    main_panel = window.main_panel
    main_panel.root_dir = tmp_path
    pane = main_panel.panes[0]
    widget = pane.widget(0)
    target = tmp_path / "sub" / "file.txt"
    pane._tab_state_for(widget).path = target

    pane._copy_path(widget)
    assert QApplication.clipboard().text() == str(target)

    pane._copy_relative_path(widget)
    assert QApplication.clipboard().text() == str(Path("sub") / "file.txt")


def test_copy_path_is_a_noop_without_a_backing_file(window: MainWindow) -> None:
    pane = window.main_panel.panes[0]
    widget = pane.widget(0)

    pane._copy_path(widget)  # must not raise


def test_reveal_in_os_explorer_invokes_windows_explorer_select(
    window: MainWindow, monkeypatch, tmp_path: Path
) -> None:
    pane = window.main_panel.panes[0]
    target = tmp_path / "file.txt"
    calls = []
    monkeypatch.setattr(tabs_module.subprocess, "run", lambda *a, **k: calls.append(a))

    pane._reveal_in_os_explorer(target)

    assert calls == [(["explorer", "/select,", str(target)],)]


def test_reveal_in_os_explorer_is_a_noop_without_a_path(
    window: MainWindow, monkeypatch
) -> None:
    pane = window.main_panel.panes[0]
    calls = []
    monkeypatch.setattr(tabs_module.subprocess, "run", lambda *a, **k: calls.append(a))

    pane._reveal_in_os_explorer(None)

    assert calls == []


def test_reveal_in_explorer_view_opens_and_switches_the_sidebar(window: MainWindow) -> None:
    pane = window.main_panel.panes[0]
    window.activity_bar.search_button.click()
    assert window._sidebar_stack.currentWidget() is window._sidebar_pages["search"]

    pane._reveal_in_explorer_view()

    assert window._sidebar_stack.currentWidget() is window._sidebar_pages["explorer"]
    assert window.primary_sidebar.isVisible() is True
    assert window.activity_bar.explorer_button.isChecked() is True


def test_reveal_in_explorer_view_is_a_noop_without_a_wired_callback(qtbot) -> None:
    area = MainPanelArea()
    qtbot.addWidget(area)
    pane = area.panes[0]

    pane._reveal_in_explorer_view()  # must not raise


# -- context menu -------------------------------------------------------------------------------


def test_context_menu_lists_the_expected_actions_in_order(window: MainWindow, monkeypatch) -> None:
    pane = window.main_panel.panes[0]
    captured = {}
    monkeypatch.setattr(QMenu, "exec", lambda self, *a, **k: captured.setdefault("menu", self))
    pos = pane.tabBar().tabRect(0).center()

    pane._show_tab_context_menu(pos)

    labels = [action.text() for action in captured["menu"].actions() if not action.isSeparator()]
    assert labels == [
        "Close",
        "Close Others",
        "Close to the Right",
        "Close Saved",
        "Close All",
        "Copy Path",
        "Copy Relative Path",
        "Reveal in File Explorer",
        "Reveal in Explorer View",
        "Pin",
        "Split Right",
        "Split Down",
    ]
    by_text = {action.text(): action for action in captured["menu"].actions()}
    assert by_text["Copy Path"].isEnabled() is False
    assert by_text["Reveal in File Explorer"].isEnabled() is False


def test_context_menu_enables_path_actions_once_a_tab_has_a_file(
    window: MainWindow, monkeypatch, tmp_path: Path
) -> None:
    pane = window.main_panel.panes[0]
    pane._tab_state_for(pane.widget(0)).path = tmp_path / "file.txt"
    captured = {}
    monkeypatch.setattr(QMenu, "exec", lambda self, *a, **k: captured.setdefault("menu", self))
    pos = pane.tabBar().tabRect(0).center()

    pane._show_tab_context_menu(pos)

    by_text = {action.text(): action for action in captured["menu"].actions()}
    assert by_text["Copy Path"].isEnabled() is True
    assert by_text["Copy Relative Path"].isEnabled() is True
    assert by_text["Reveal in File Explorer"].isEnabled() is True
    assert by_text["Reveal in Explorer View"].isEnabled() is True


def test_context_menu_shows_unpin_once_pinned(window: MainWindow, monkeypatch) -> None:
    pane = window.main_panel.panes[0]
    pane._toggle_pin(0)
    captured = {}
    monkeypatch.setattr(QMenu, "exec", lambda self, *a, **k: captured.setdefault("menu", self))
    pos = pane.tabBar().tabRect(0).center()

    pane._show_tab_context_menu(pos)

    labels = [action.text() for action in captured["menu"].actions() if not action.isSeparator()]
    assert "Unpin" in labels
    assert "Pin" not in labels


def test_context_menu_split_actions_grey_out_once_maxed(window: MainWindow, monkeypatch) -> None:
    pane = window.main_panel.panes[0]
    for _ in range(_MAX_H_SPLITS):
        pane.split_button.click()
    captured = {}
    monkeypatch.setattr(QMenu, "exec", lambda self, *a, **k: captured.setdefault("menu", self))
    pos = pane.tabBar().tabRect(0).center()

    pane._show_tab_context_menu(pos)

    by_text = {action.text(): action for action in captured["menu"].actions()}
    assert by_text["Split Right"].isEnabled() is False


# -- drag/drop preserves per-tab state ------------------------------------------------------------


def test_drop_between_panes_preserves_path_and_pinned_state(
    window: MainWindow, tmp_path: Path
) -> None:
    main_panel = window.main_panel
    source = main_panel.panes[0]
    source.split_button.click()
    dest = main_panel.panes[1]

    widget = source.widget(0)
    state = source._tab_state_for(widget)
    state.path = tmp_path / "kept.txt"
    state.pinned = True

    # Replicates TabPane.dropEvent()'s own move logic -- see test_ide_smoke.py's own drag/drop
    # test for why drag-and-drop itself is exercised manually rather than via a simulated drag.
    label = source.tabText(0)
    carried_state = source._tab_state.pop(widget, None)
    source.removeTab(0)
    new_index = dest.addTab(widget, label)
    dest._track_tab(new_index, widget, state=carried_state)
    main_panel.on_pane_emptied(source)

    moved_state = dest._tab_state_for(widget)
    assert moved_state.path == tmp_path / "kept.txt"
    assert moved_state.pinned is True


# -- Welcome tab ----------------------------------------------------------------------------------


def test_welcome_tab_shows_title_subtitle_version_path_and_four_quadrants(qtbot, tmp_path) -> None:
    welcome = WelcomeTab(root_dir=tmp_path)
    qtbot.addWidget(welcome)

    labels = [label.text() for label in welcome.findChildren(QLabel)]
    assert "In-Reach" in labels
    assert "Halo Reach Script Manager" in labels
    assert f"v{in_reach.__version__}" in labels
    assert str(tmp_path) in labels
    for heading in ("Start", "Recent", "Verify System Settings", "Help & Walkthroughs"):
        assert heading in labels


def test_welcome_tabs_carry_the_panels_root_dir_into_their_duplicates(window, tmp_path) -> None:
    # A split duplicates the source tab into the new pane -- a duplicated Welcome tab must still
    # know which folder it's showing/creating projects against, not silently fall back to cwd.
    main_panel = window.main_panel
    main_panel.root_dir = tmp_path
    pane = main_panel.panes[0]
    pane.setCurrentIndex(0)

    pane.split_button.click()

    duplicate = main_panel.panes[-1].widget(0)
    assert isinstance(duplicate, WelcomeTab)
    assert duplicate.root_dir == tmp_path


# -- File menu entry points on TabPane/MainPanelArea -----------------------------------------------


def test_save_current_saves_the_active_tab_prompting_for_a_path(
    window: MainWindow, monkeypatch, tmp_path: Path
) -> None:
    pane = window.main_panel.panes[0]
    window.main_panel.new_tab_in(pane)
    pane.widget(pane.currentIndex()).setPlainText("hello")
    target = tmp_path / "new.txt"
    monkeypatch.setattr(TabPane, "_ask_save_path", lambda self, default_dir, name: target)

    result = pane.save_current()

    assert result is True
    assert target.read_text(encoding="utf-8") == "hello"


def test_save_current_on_an_empty_pane_is_a_no_op(window: MainWindow) -> None:
    pane = window.main_panel.panes[0]
    pane.tabCloseRequested.emit(0)  # empties the pane (the Welcome tab has no unsaved changes)
    assert pane.count() == 0

    assert pane.save_current() is False


def test_save_current_as_always_prompts_even_for_an_already_saved_tab(
    window: MainWindow, monkeypatch, tmp_path: Path
) -> None:
    pane = window.main_panel.panes[0]
    window.main_panel.new_tab_in(pane)
    index = pane.currentIndex()
    pane.widget(index).setPlainText("v1")
    first_path = tmp_path / "first.txt"
    monkeypatch.setattr(TabPane, "_ask_save_path", lambda self, default_dir, name: first_path)
    pane.save_current()
    assert pane._tab_state_for(pane.widget(index)).path == first_path

    second_path = tmp_path / "second.txt"
    monkeypatch.setattr(TabPane, "_ask_save_path", lambda self, default_dir, name: second_path)
    result = pane.save_current_as()

    assert result is True
    assert pane._tab_state_for(pane.widget(index)).path == second_path
    assert second_path.read_text(encoding="utf-8") == "v1"


def test_save_current_as_cancelled_restores_the_original_path(
    window: MainWindow, monkeypatch, tmp_path: Path
) -> None:
    pane = window.main_panel.panes[0]
    window.main_panel.new_tab_in(pane)
    index = pane.currentIndex()
    widget = pane.widget(index)
    original = tmp_path / "original.txt"
    monkeypatch.setattr(TabPane, "_ask_save_path", lambda self, default_dir, name: original)
    pane.save_current()

    monkeypatch.setattr(TabPane, "_ask_save_path", lambda self, default_dir, name: None)
    result = pane.save_current_as()

    assert result is False
    assert pane._tab_state_for(widget).path == original


def test_save_all_saves_every_modified_tab_that_already_has_a_path(
    window: MainWindow, monkeypatch, tmp_path: Path
) -> None:
    pane = window.main_panel.panes[0]
    window.main_panel.new_tab_in(pane)
    saved_index = pane.currentIndex()
    saved_path = tmp_path / "saved.txt"
    pane._track_tab(saved_index, pane.widget(saved_index), state=_TabState(path=saved_path))
    pane.widget(saved_index).setPlainText("v2")
    pane.widget(saved_index).document().setModified(True)

    window.main_panel.new_tab_in(pane)  # never saved -- no path yet, save_all() must skip it
    never_saved_index = pane.currentIndex()

    pane.save_all()

    assert saved_path.read_text(encoding="utf-8") == "v2"
    assert pane._tab_state_for(pane.widget(never_saved_index)).path is None


def test_open_file_adds_a_tab_with_the_files_content(window: MainWindow, tmp_path: Path) -> None:
    pane = window.main_panel.panes[0]
    source = tmp_path / "script.txt"
    source.write_text("print('hi')", encoding="utf-8")

    pane.open_file(source)

    index = pane.currentIndex()
    assert pane.tabText(index) == "script.txt"
    assert pane.widget(index).toPlainText() == "print('hi')"
    assert pane._tab_state_for(pane.widget(index)).path == source


def test_open_file_switches_to_the_existing_tab_instead_of_duplicating_it(
    window: MainWindow, tmp_path: Path
) -> None:
    pane = window.main_panel.panes[0]
    source = tmp_path / "script.txt"
    source.write_text("print('hi')", encoding="utf-8")
    pane.open_file(source)
    first_index = pane.currentIndex()

    window.main_panel.new_tab_in(pane)  # moves focus elsewhere first
    assert pane.currentIndex() != first_index
    before = pane.count()

    pane.open_file(source)

    assert pane.count() == before
    assert pane.currentIndex() == first_index


def test_open_file_reports_an_unreadable_file_rather_than_raising(
    window: MainWindow, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    pane = window.main_panel.panes[0]
    before = pane.count()
    missing = tmp_path / "nope.txt"

    pane.open_file(missing)

    assert pane.count() == before


def test_close_current_closes_the_active_tab(window: MainWindow) -> None:
    pane = window.main_panel.panes[0]
    before = pane.count()

    result = pane.close_current()

    assert result is True
    assert pane.count() == before - 1


def test_close_current_on_an_empty_pane_is_a_no_op(window: MainWindow) -> None:
    pane = window.main_panel.panes[0]
    pane.tabCloseRequested.emit(0)
    assert pane.count() == 0

    assert pane.close_current() is False


def test_active_pane_is_the_first_pane(window: MainWindow) -> None:
    main_panel = window.main_panel
    first_pane = main_panel.panes[0]
    first_pane.split_button.click()

    assert main_panel.active_pane is first_pane


def test_main_panel_save_all_covers_every_pane_not_just_the_first(
    window: MainWindow, tmp_path: Path
) -> None:
    main_panel = window.main_panel
    first_pane = main_panel.panes[0]
    first_pane.split_button.click()
    second_pane = main_panel.panes[-1]

    path1 = tmp_path / "one.txt"
    main_panel.new_tab_in(first_pane)
    idx1 = first_pane.currentIndex()
    first_pane._track_tab(idx1, first_pane.widget(idx1), state=_TabState(path=path1))
    first_pane.widget(idx1).setPlainText("one")
    first_pane.widget(idx1).document().setModified(True)

    path2 = tmp_path / "two.txt"
    main_panel.new_tab_in(second_pane)
    idx2 = second_pane.currentIndex()
    second_pane._track_tab(idx2, second_pane.widget(idx2), state=_TabState(path=path2))
    second_pane.widget(idx2).setPlainText("two")
    second_pane.widget(idx2).document().setModified(True)

    main_panel.save_all()

    assert path1.read_text(encoding="utf-8") == "one"
    assert path2.read_text(encoding="utf-8") == "two"
