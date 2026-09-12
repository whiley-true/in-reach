from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from in_reach.app import env_file
from in_reach.ide import theme as theme_module
from in_reach.ide.main_window import MainWindow
from in_reach.ide.quick_access import Command, QuickAccessBar, QuickAccessOverlay


@pytest.fixture
def project_window(qtbot, tmp_path: Path) -> MainWindow:
    project_dir = tmp_path / ".in-reach"
    project_dir.mkdir()
    (project_dir / ".env").write_text("", encoding="utf-8")
    win = MainWindow(root_dir=tmp_path)
    qtbot.addWidget(win)
    win.show()
    return win


@pytest.fixture
def overlay(qtbot) -> QuickAccessOverlay:
    widget = QuickAccessOverlay()
    qtbot.addWidget(widget)
    return widget


def _project(tmp_path: Path) -> Path:
    (tmp_path / "settings").mkdir()
    (tmp_path / "settings" / "settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "settings" / "strings.json").write_text("{}", encoding="utf-8")
    return tmp_path


# -- search mode --------------------------------------------------------------------------------


def test_open_search_lists_every_project_file(overlay: QuickAccessOverlay, tmp_path: Path) -> None:
    project = _project(tmp_path)
    from in_reach.app import quick_open

    files = quick_open.list_project_files(project)

    overlay.open_search(project, files, lambda p: None)

    assert overlay.list_widget.count() == 2
    assert overlay.isVisible() is True


def test_search_filters_as_the_query_changes(overlay: QuickAccessOverlay, tmp_path: Path) -> None:
    project = _project(tmp_path)
    from in_reach.app import quick_open

    overlay.open_search(project, quick_open.list_project_files(project), lambda p: None)

    overlay.line_edit.setText("strings")

    assert overlay.list_widget.count() == 1
    assert "strings.json" in overlay.list_widget.item(0).text()


def test_enter_on_a_search_result_opens_the_file(overlay: QuickAccessOverlay, tmp_path: Path) -> None:
    project = _project(tmp_path)
    from in_reach.app import quick_open

    opened = []
    overlay.open_search(project, quick_open.list_project_files(project), opened.append)
    overlay.line_edit.setText("strings")

    overlay.activate_current()

    assert opened == [project / "settings" / "strings.json"]
    assert overlay.isVisible() is False


# -- ">" flips search into the command palette -------------------------------------------------


def test_typing_gt_in_search_switches_to_command_mode(overlay: QuickAccessOverlay, tmp_path: Path) -> None:
    project = _project(tmp_path)
    overlay.open_search(project, [], lambda p: None)

    overlay.line_edit.setText(">")

    assert overlay._mode == "command"


def test_ctrl_shift_p_style_open_starts_in_command_mode_with_prefix_prefilled(
    overlay: QuickAccessOverlay,
) -> None:
    commands = [Command(label="Do Thing", action=lambda: None)]

    overlay.open_command_palette(commands)

    assert overlay.line_edit.text() == ">"
    assert overlay._mode == "command"
    assert overlay.list_widget.count() == 1


# -- command palette: filtering, two-level drill-down, execution --------------------------------


def test_command_palette_filters_by_label(overlay: QuickAccessOverlay) -> None:
    commands = [Command(label="Set Theme"), Command(label="Set UI Scale")]
    overlay.open_command_palette(commands)

    overlay.line_edit.setText(">theme")

    assert overlay.list_widget.count() == 1
    assert "Set Theme" in overlay.list_widget.item(0).text()


def test_enter_on_a_parent_command_shows_its_children_instead_of_closing(
    overlay: QuickAccessOverlay,
) -> None:
    leaf_ran = []
    commands = [
        Command(
            label="Set Theme",
            children=[Command(label="Light", action=lambda: leaf_ran.append("Light"))],
        )
    ]
    overlay.open_command_palette(commands)

    overlay.activate_current()  # Enter on "Set Theme"

    assert overlay.isVisible() is True  # still open -- drilled into children, not executed
    assert leaf_ran == []
    assert overlay.list_widget.count() == 1
    assert "Light" in overlay.list_widget.item(0).text()

    overlay.activate_current()  # Enter on "Light"

    assert leaf_ran == ["Light"]
    assert overlay.isVisible() is False


def test_leaf_command_runs_its_action_and_closes(overlay: QuickAccessOverlay) -> None:
    ran = []
    commands = [Command(label="Increase", action=lambda: ran.append(True))]
    overlay.open_command_palette(commands)

    overlay.activate_current()

    assert ran == [True]
    assert overlay.isVisible() is False


# -- goto_line mode: live jump as digits are typed -----------------------------------------------


def test_goto_line_applies_live_as_valid_digits_are_typed(overlay: QuickAccessOverlay) -> None:
    seen = []
    overlay.open_goto_line(50, seen.append)

    overlay.line_edit.setText("12")

    assert seen == [12]
    assert overlay.list_widget.isVisible() is False


def test_goto_line_ignores_out_of_range_values(overlay: QuickAccessOverlay) -> None:
    seen = []
    overlay.open_goto_line(10, seen.append)

    overlay.line_edit.setText("99")

    assert seen == []


def test_goto_line_ignores_non_numeric_text(overlay: QuickAccessOverlay) -> None:
    seen = []
    overlay.open_goto_line(10, seen.append)

    overlay.line_edit.setText("abc")

    assert seen == []


# -- action_list mode: the Spaces segment's fixed 5-item menu -------------------------------------


def test_action_list_shows_the_given_commands_under_a_heading(overlay: QuickAccessOverlay) -> None:
    commands = [Command(label="Trim trailing whitespace", action=lambda: None)]

    overlay.open_action_list(commands, heading="Select Action")

    assert overlay.heading_label.text() == "Select Action"
    assert overlay.heading_label.isVisible() is True
    assert overlay.line_edit.text() == ""
    assert overlay.list_widget.count() == 1


# -- keyboard navigation --------------------------------------------------------------------------


def test_arrow_keys_move_the_selection(overlay: QuickAccessOverlay) -> None:
    commands = [Command(label="A"), Command(label="B"), Command(label="C")]
    overlay.open_action_list(commands)
    assert overlay.list_widget.currentRow() == 0

    overlay.move_selection(1)
    assert overlay.list_widget.currentRow() == 1

    overlay.move_selection(-1)
    assert overlay.list_widget.currentRow() == 0


def test_escape_hides_the_overlay(overlay: QuickAccessOverlay, qtbot) -> None:
    overlay.open_action_list([Command(label="A")])
    overlay.show()

    qtbot.keyClick(overlay.line_edit, Qt.Key.Key_Escape)

    assert overlay.isVisible() is False


# -- the pill widget itself ------------------------------------------------------------------------


def test_pill_click_opens_search_mode(qtbot, tmp_path: Path) -> None:
    project = _project(tmp_path)
    bar = QuickAccessBar(
        get_project_folder=lambda: project,
        open_file=lambda p: None,
        build_root_commands=lambda: [],
    )
    qtbot.addWidget(bar)

    bar.button.click()

    assert bar.overlay._mode == "search"
    assert bar.overlay.isVisible() is True


def test_pill_defaults_to_three_times_its_natural_width(qtbot) -> None:
    bar = QuickAccessBar(
        get_project_folder=lambda: None,
        open_file=lambda p: None,
        build_root_commands=lambda: [],
    )
    qtbot.addWidget(bar)

    assert bar.button.width() == bar.button.sizeHint().width() * 3


def test_open_command_palette_builds_from_the_injected_root_commands(qtbot) -> None:
    bar = QuickAccessBar(
        get_project_folder=lambda: None,
        open_file=lambda p: None,
        build_root_commands=lambda: [Command(label="Set Theme")],
    )
    qtbot.addWidget(bar)

    bar.open_command_palette()

    assert bar.overlay.list_widget.count() == 1


# -- MainWindow integration: shortcuts, the pill in the top bar, Set Theme/Set UI Scale -----------


def test_pill_label_is_the_root_dir_name(project_window: MainWindow) -> None:
    """PROMPT.md: "rename the search bar text to be the name of the parent folder where in-reach
    has been installed" -- the pill shows ``root_dir.name`` (the folder the window's own
    ``.in-reach`` project data lives under), not a generic "Search" label."""
    assert project_window.top_bar.quick_access.button.text() == project_window.root_dir.name


def test_ctrl_p_shortcut_opens_search_mode(project_window: MainWindow) -> None:
    project_window._quick_open_shortcut.activated.emit()

    assert project_window.quick_access.overlay._mode == "search"
    assert project_window.quick_access.overlay.isVisible() is True


def test_ctrl_shift_p_shortcut_opens_command_mode(project_window: MainWindow) -> None:
    project_window._command_palette_shortcut.activated.emit()

    assert project_window.quick_access.overlay._mode == "command"
    assert project_window.quick_access.overlay.isVisible() is True


def test_no_shortcut_binds_the_same_key_sequence_twice(project_window: MainWindow) -> None:
    for name in ("_quick_open_shortcut", "_command_palette_shortcut"):
        keys = [seq.toString() for seq in getattr(project_window, name).keys()]
        assert len(keys) == len(set(keys))


def test_the_pill_is_centered_between_the_left_content_and_the_right_controls(project_window: MainWindow) -> None:
    top_bar = project_window.top_bar
    layout = top_bar.layout()
    widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
    assert top_bar.quick_access in widgets


def test_build_command_palette_commands_offers_set_theme_and_set_ui_scale(project_window: MainWindow) -> None:
    commands = project_window.build_command_palette_commands()

    labels = [c.label for c in commands]
    assert labels == ["Set Theme", "Set UI Scale"]
    theme_command = commands[0]
    assert [c.label for c in theme_command.children] == ["Light", "Dark", "Whiley"]
    scale_command = commands[1]
    assert [c.label for c in scale_command.children] == ["Increase", "Decrease"]


def test_running_a_set_theme_command_applies_and_persists_the_theme(project_window: MainWindow) -> None:
    from PyQt6.QtGui import QPalette

    commands = project_window.build_command_palette_commands()
    whiley = next(c for c in commands[0].children if c.label == "Whiley")

    whiley.action()

    applied_base = QApplication.instance().palette().color(QPalette.ColorRole.Base).name()
    assert applied_base == theme_module.load_theme("Whiley").palette_colors["base"]
    env_path = project_window.root_dir / ".in-reach" / ".env"
    assert env_file.get_env_values(env_path)[theme_module.THEME_KEY] == "Whiley"


def test_running_a_set_ui_scale_command_zooms(project_window: MainWindow) -> None:
    from in_reach.ide import zoom as zoom_module

    commands = project_window.build_command_palette_commands()
    increase = next(c for c in commands[1].children if c.label == "Increase")
    env_path = project_window.root_dir / ".in-reach" / ".env"
    before = zoom_module.get_zoom(env_path)

    increase.action()

    assert zoom_module.get_zoom(env_path) > before


def test_open_quick_access_file_opens_it_into_the_active_pane(project_window: MainWindow, tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("hi", encoding="utf-8")

    project_window.open_quick_access_file(path)

    from in_reach.ide.editor import TextEditorWidget

    widget = project_window.main_panel.active_pane.currentWidget()
    assert isinstance(widget, TextEditorWidget)
    assert widget.path == path
