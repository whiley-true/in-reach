from pathlib import Path

import pytest
from PyQt6.QtCore import Qt

from in_reach.app import env_file, system_verify
from in_reach.ide.explorer import ExplorerPanel


@pytest.fixture
def panel(qtbot) -> ExplorerPanel:
    widget = ExplorerPanel()
    qtbot.addWidget(widget)
    widget.show()  # isVisible() reflects real state only once the whole ancestor chain is shown
    return widget


def test_starts_with_no_project_placeholder_shown_and_tree_hidden(panel: ExplorerPanel) -> None:
    assert panel._no_project_label.isVisible() is True
    assert panel.project_tree.isVisible() is False


def test_open_project_shows_the_tree_rooted_at_it(panel: ExplorerPanel, tmp_path: Path) -> None:
    folder = tmp_path / "project"
    folder.mkdir()
    (folder / "settings.json").write_text("{}", encoding="utf-8")

    panel.open_project(folder)

    assert panel._no_project_label.isVisible() is False
    assert panel.project_tree.isVisible() is True
    assert Path(panel._project_model.rootPath()) == folder


def test_close_all_projects_restores_the_placeholder(panel: ExplorerPanel, tmp_path: Path) -> None:
    folder = tmp_path / "project"
    folder.mkdir()
    panel.open_project(folder)

    panel.close_all_projects()

    assert panel._no_project_label.isVisible() is True
    assert panel.project_tree.isVisible() is False


def test_opening_a_nonexistent_project_folder_is_a_no_op(panel: ExplorerPanel, tmp_path: Path) -> None:
    panel.open_project(tmp_path / "does-not-exist")

    assert panel._no_project_label.isVisible() is True
    assert panel.project_tree.isVisible() is False
    assert panel.open_projects == []


# -- the two personal-folder sections -----------------------------------------------------------


@pytest.fixture
def env_project_dir(tmp_path: Path) -> Path:
    project_dir = tmp_path / ".in-reach"
    project_dir.mkdir()
    (project_dir / ".env").write_text("", encoding="utf-8")
    return project_dir


# Sections start collapsed (see the "collapsible sections" tests below), so a nested tree/
# placeholder's own isVisible() reflects the whole ancestor chain including that collapse -- these
# tests care about the resolved-vs-placeholder state on its own, so they check visibility relative
# to the section's own body instead (see QWidget.isVisibleTo's own docs).


def test_personal_sections_start_with_the_not_resolved_placeholder(
    panel: ExplorerPanel, env_project_dir: Path
) -> None:
    panel.set_env_project_dir(env_project_dir)

    body1 = panel.personal_variants_section.body
    body2 = panel.personal_maps_section.body
    assert panel.personal_variants_placeholder.isVisibleTo(body1) is True
    assert panel.personal_variants_tree.isVisibleTo(body1) is False
    assert panel.personal_maps_placeholder.isVisibleTo(body2) is True
    assert panel.personal_maps_tree.isVisibleTo(body2) is False


def test_personal_sections_resolve_once_the_env_keys_are_set(
    panel: ExplorerPanel, env_project_dir: Path, tmp_path: Path
) -> None:
    variants = tmp_path / "variants"
    variants.mkdir()
    maps = tmp_path / "maps"
    maps.mkdir()
    env_file.update_env_value(env_project_dir / ".env", system_verify.PERSONAL_VARIANTS_KEY, str(variants))
    env_file.update_env_value(env_project_dir / ".env", system_verify.PERSONAL_MAPS_KEY, str(maps))

    panel.set_env_project_dir(env_project_dir)

    body1 = panel.personal_variants_section.body
    body2 = panel.personal_maps_section.body
    assert panel.personal_variants_placeholder.isVisibleTo(body1) is False
    assert panel.personal_variants_tree.isVisibleTo(body1) is True
    assert Path(panel._personal_variants_model.rootPath()) == variants
    assert panel.personal_maps_placeholder.isVisibleTo(body2) is False
    assert panel.personal_maps_tree.isVisibleTo(body2) is True
    assert Path(panel._personal_maps_model.rootPath()) == maps


def test_refresh_personal_folders_picks_up_a_later_verify(
    panel: ExplorerPanel, env_project_dir: Path, tmp_path: Path
) -> None:
    panel.set_env_project_dir(env_project_dir)
    body = panel.personal_variants_section.body
    assert panel.personal_variants_tree.isVisibleTo(body) is False

    variants = tmp_path / "variants"
    variants.mkdir()
    env_file.update_env_value(env_project_dir / ".env", system_verify.PERSONAL_VARIANTS_KEY, str(variants))
    panel.refresh_personal_folders()

    assert panel.personal_variants_tree.isVisibleTo(body) is True


def test_set_env_project_dir_none_clears_both_sections(
    panel: ExplorerPanel, env_project_dir: Path, tmp_path: Path
) -> None:
    variants = tmp_path / "variants"
    variants.mkdir()
    env_file.update_env_value(env_project_dir / ".env", system_verify.PERSONAL_VARIANTS_KEY, str(variants))
    panel.set_env_project_dir(env_project_dir)
    body = panel.personal_variants_section.body
    assert panel.personal_variants_tree.isVisibleTo(body) is True

    panel.set_env_project_dir(None)

    assert panel.personal_variants_placeholder.isVisibleTo(body) is True
    assert panel.personal_variants_tree.isVisibleTo(body) is False


# -- collapsible sections -------------------------------------------------------------------------


def test_personal_sections_start_collapsed(panel: ExplorerPanel) -> None:
    assert panel.personal_variants_section.expanded is False
    assert panel.personal_maps_section.expanded is False
    assert panel.personal_variants_section.body.isVisible() is False


def test_clicking_a_section_header_expands_it(panel: ExplorerPanel, qtbot) -> None:
    qtbot.mouseClick(panel.personal_variants_section._toggle, Qt.MouseButton.LeftButton)

    assert panel.personal_variants_section.expanded is True
    assert panel.personal_variants_section.body.isVisible() is True


# -- clicking a file opens it ----------------------------------------------------------------------


def test_clicking_a_file_in_the_project_tree_emits_file_activated(
    panel: ExplorerPanel, qtbot, tmp_path: Path
) -> None:
    folder = tmp_path / "project"
    folder.mkdir()
    file_path = folder / "notes.txt"
    file_path.write_text("hi", encoding="utf-8")
    panel.open_project(folder)
    model = panel._project_model
    root_index = panel.project_tree.rootIndex()
    qtbot.waitUntil(lambda: model.rowCount(root_index) > 0, timeout=2000)
    file_index = model.index(str(file_path))

    activated: list[Path] = []
    panel.file_activated.connect(activated.append)
    panel._on_tree_clicked(model, file_index)

    assert activated == [file_path]


def test_clicking_a_file_in_the_project_tree_via_the_real_signal_emits_file_activated(
    panel: ExplorerPanel, qtbot, tmp_path: Path
) -> None:
    # Unlike the test above (which drives the private handler directly), this fires the tree's own
    # `clicked` signal -- confirming the project tree really is wired up, the mirror image of the
    # "personal folders are NOT wired up" tests below.
    folder = tmp_path / "project"
    folder.mkdir()
    file_path = folder / "notes.txt"
    file_path.write_text("hi", encoding="utf-8")
    panel.open_project(folder)
    model = panel._project_model
    root_index = panel.project_tree.rootIndex()
    qtbot.waitUntil(lambda: model.rowCount(root_index) > 0, timeout=2000)
    file_index = model.index(str(file_path))

    activated: list[Path] = []
    panel.file_activated.connect(activated.append)
    panel.project_tree.clicked.emit(file_index)

    assert activated == [file_path]


def test_clicking_a_folder_in_the_project_tree_does_not_emit_file_activated(
    panel: ExplorerPanel, qtbot, tmp_path: Path
) -> None:
    folder = tmp_path / "project"
    (folder / "subfolder").mkdir(parents=True)
    panel.open_project(folder)
    model = panel._project_model
    root_index = panel.project_tree.rootIndex()
    qtbot.waitUntil(lambda: model.rowCount(root_index) > 0, timeout=2000)
    dir_index = model.index(str(folder / "subfolder"))

    activated: list[Path] = []
    panel.file_activated.connect(activated.append)
    panel._on_tree_clicked(model, dir_index)

    assert activated == []


def test_an_invalid_index_does_not_emit_file_activated(panel: ExplorerPanel) -> None:
    from PyQt6.QtCore import QModelIndex

    activated: list[Path] = []
    panel.file_activated.connect(activated.append)

    panel._on_tree_clicked(panel._project_model, QModelIndex())

    assert activated == []


def test_clicking_a_file_in_a_personal_folder_section_does_not_open_it(
    panel: ExplorerPanel, qtbot, tmp_path: Path
) -> None:
    # PROMPT.md: "disable clicking on personal game variants of personal map variants window for
    # now" -- those are raw .bin/.mvar files, and opening one as text just raised an error. Clicks
    # in either personal-folder tree are simply never wired to file_activated at all (see
    # ExplorerPanel.__init__) -- this drives the real `clicked` signal, not the private handler
    # directly, so it actually exercises that wiring (or lack of it) rather than just the handler.
    project_dir = tmp_path / ".in-reach"
    project_dir.mkdir()
    (project_dir / ".env").write_text("", encoding="utf-8")
    variants = tmp_path / "variants"
    variants.mkdir()
    file_path = variants / "Slayer.bin"
    file_path.write_bytes(b"")
    env_file.update_env_value(project_dir / ".env", system_verify.PERSONAL_VARIANTS_KEY, str(variants))
    panel.set_env_project_dir(project_dir)
    model = panel._personal_variants_model
    root_index = panel.personal_variants_tree.rootIndex()
    qtbot.waitUntil(lambda: model.rowCount(root_index) > 0, timeout=2000)
    file_index = model.index(str(file_path))

    activated: list[Path] = []
    panel.file_activated.connect(activated.append)
    panel.personal_variants_tree.clicked.emit(file_index)

    assert activated == []


def test_clicking_a_file_in_the_personal_maps_section_also_does_not_open_it(
    panel: ExplorerPanel, qtbot, tmp_path: Path
) -> None:
    project_dir = tmp_path / ".in-reach"
    project_dir.mkdir()
    (project_dir / ".env").write_text("", encoding="utf-8")
    maps = tmp_path / "maps"
    maps.mkdir()
    file_path = maps / "Forge.mvar"
    file_path.write_bytes(b"")
    env_file.update_env_value(project_dir / ".env", system_verify.PERSONAL_MAPS_KEY, str(maps))
    panel.set_env_project_dir(project_dir)
    model = panel._personal_maps_model
    root_index = panel.personal_maps_tree.rootIndex()
    qtbot.waitUntil(lambda: model.rowCount(root_index) > 0, timeout=2000)
    file_index = model.index(str(file_path))

    activated: list[Path] = []
    panel.file_activated.connect(activated.append)
    panel.personal_maps_tree.clicked.emit(file_index)

    assert activated == []


# -- text scale -------------------------------------------------------------------------------


def test_panel_font_is_10_percent_larger_than_the_app_font(panel: ExplorerPanel) -> None:
    from PyQt6.QtWidgets import QApplication

    app_size = QApplication.instance().font().pointSizeF()

    assert panel.font().pointSizeF() == pytest.approx(app_size * ExplorerPanel.TEXT_SCALE)


def test_refresh_font_scale_tracks_a_later_app_font_change(panel: ExplorerPanel) -> None:
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    original = QFont(app.font())
    try:
        bigger = QFont(original)
        bigger.setPointSizeF(original.pointSizeF() * 2)
        app.setFont(bigger)

        panel.refresh_font_scale()

        assert panel.font().pointSizeF() == pytest.approx(bigger.pointSizeF() * ExplorerPanel.TEXT_SCALE)
    finally:
        app.setFont(original)


def test_personal_section_headers_are_10_percent_smaller_than_the_panel_font(panel: ExplorerPanel) -> None:
    panel_size = panel.font().pointSizeF()

    for section in (panel.personal_variants_section, panel.personal_maps_section):
        assert section._toggle.font().pointSizeF() == pytest.approx(
            panel_size * ExplorerPanel.HEADER_TEXT_SCALE
        )


# -- multi-project tabs ------------------------------------------------------------------------


def test_project_tabs_are_hidden_with_no_project(panel: ExplorerPanel) -> None:
    assert panel.project_tabs.isVisible() is False
    assert panel.project_tabs.count() == 0


def test_open_project_adds_a_tab_labeled_with_the_projects_own_title(
    panel: ExplorerPanel, tmp_path: Path
) -> None:
    folder = tmp_path / "abcd1234"
    folder.mkdir()
    (folder / "README.md").write_text("# Slayer Plus\n\nA better slayer.\n", encoding="utf-8")

    panel.open_project(folder)

    assert panel.project_tabs.isVisible() is True
    assert panel.project_tabs.count() == 1
    assert panel.project_tabs.tabText(0) == "Slayer Plus"
    assert panel.open_projects == [folder]
    assert panel.current_folder == folder


def test_open_project_tab_falls_back_to_the_folder_name_without_a_readme(
    panel: ExplorerPanel, tmp_path: Path
) -> None:
    folder = tmp_path / "abcd1234"
    folder.mkdir()

    panel.open_project(folder)

    assert panel.project_tabs.tabText(0) == "abcd1234"


def test_opening_an_already_open_project_switches_instead_of_duplicating(
    panel: ExplorerPanel, tmp_path: Path
) -> None:
    first = tmp_path / "first"
    first.mkdir()
    second = tmp_path / "second"
    second.mkdir()
    panel.open_project(first)
    panel.open_project(second)

    panel.open_project(first)

    assert panel.project_tabs.count() == 2
    assert panel.open_projects == [first, second]
    assert panel.current_folder == first


def test_opening_a_second_project_adds_a_tab_without_closing_the_first(
    panel: ExplorerPanel, tmp_path: Path
) -> None:
    first = tmp_path / "first"
    first.mkdir()
    second = tmp_path / "second"
    second.mkdir()

    panel.open_project(first)
    panel.open_project(second)

    assert panel.project_tabs.count() == 2
    assert panel.open_projects == [first, second]
    assert panel.current_folder == second
    assert Path(panel._project_model.rootPath()) == second


def test_close_project_switches_to_a_remaining_tab(panel: ExplorerPanel, tmp_path: Path) -> None:
    first = tmp_path / "first"
    first.mkdir()
    second = tmp_path / "second"
    second.mkdir()
    panel.open_project(first)
    panel.open_project(second)

    panel.close_project(second)

    assert panel.open_projects == [first]
    assert panel.current_folder == first
    assert panel.project_tabs.isVisible() is True


def test_close_project_of_the_last_tab_restores_the_placeholder(panel: ExplorerPanel, tmp_path: Path) -> None:
    folder = tmp_path / "abcd1234"
    folder.mkdir()
    panel.open_project(folder)

    panel.close_project(folder)

    assert panel.open_projects == []
    assert panel.current_folder is None
    assert panel._no_project_label.isVisible() is True
    assert panel.project_tree.isVisible() is False
    assert panel.project_tabs.isVisible() is False


def test_close_active_project_closes_whichever_tab_is_current(panel: ExplorerPanel, tmp_path: Path) -> None:
    first = tmp_path / "first"
    first.mkdir()
    second = tmp_path / "second"
    second.mkdir()
    panel.open_project(first)
    panel.open_project(second)

    panel.close_active_project()

    assert panel.open_projects == [first]
    assert panel.current_folder == first


def test_close_active_project_with_no_project_open_is_a_no_op(panel: ExplorerPanel) -> None:
    panel.close_active_project()  # should not raise

    assert panel.open_projects == []


def test_closing_a_background_tab_does_not_change_the_active_project(
    panel: ExplorerPanel, tmp_path: Path
) -> None:
    first = tmp_path / "first"
    first.mkdir()
    second = tmp_path / "second"
    second.mkdir()
    panel.open_project(first)
    panel.open_project(second)

    panel.close_project(first)

    assert panel.open_projects == [second]
    assert panel.current_folder == second


def test_tab_close_button_closes_that_projects_tab(panel: ExplorerPanel, tmp_path: Path) -> None:
    folder = tmp_path / "abcd1234"
    folder.mkdir()
    panel.open_project(folder)

    # Drives the tab bar's own close-request signal, not close_project() directly -- confirms the
    # close (X) button is actually wired up.
    panel.project_tabs.tabCloseRequested.emit(0)

    assert panel.open_projects == []


def test_active_project_changed_fires_on_open_switch_and_close(panel: ExplorerPanel, tmp_path: Path) -> None:
    first = tmp_path / "first"
    first.mkdir()
    second = tmp_path / "second"
    second.mkdir()
    seen: list[Path | None] = []
    panel.active_project_changed.connect(seen.append)

    panel.open_project(first)
    panel.open_project(second)
    panel.open_project(first)  # switch back -- "first" is active again
    panel.close_project(first)  # closing the *active* tab -- "second" becomes active
    panel.close_project(second)  # last one -- back to no project

    assert seen == [first, second, first, second, None]


def test_open_projects_changed_fires_on_open_and_close_but_not_on_switch(
    panel: ExplorerPanel, tmp_path: Path
) -> None:
    first = tmp_path / "first"
    first.mkdir()
    second = tmp_path / "second"
    second.mkdir()
    seen: list[list[Path]] = []
    panel.open_projects_changed.connect(seen.append)

    panel.open_project(first)
    panel.open_project(second)
    panel.open_project(first)  # already open -- just switches, no set change
    panel.close_project(second)

    assert seen == [[first], [first, second], [first]]
