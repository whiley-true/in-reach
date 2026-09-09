from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame

from in_reach.ide.explorer import ExplorerPanel


@pytest.fixture
def panel(qtbot) -> ExplorerPanel:
    widget = ExplorerPanel()
    qtbot.addWidget(widget)
    widget.show()  # isVisible() reflects real state only once the whole ancestor chain is shown
    return widget


# -- no bordered "bubble" chrome ---------------------------------------------------------------


def test_settings_and_script_trees_have_no_default_frame_border(panel: ExplorerPanel) -> None:
    # PROMPT.md: "please remove the bubble outline around ... setings, and output.txt" -- QTreeView
    # (like every QAbstractScrollArea) defaults to a sunken StyledPanel frame around itself.
    assert panel.settings_tree.frameShape() == QFrame.Shape.NoFrame
    assert panel.script_tree.frameShape() == QFrame.Shape.NoFrame


def test_stats_progress_bar_has_no_border(panel: ExplorerPanel) -> None:
    # PROMPT.md: "please remove the bubble outline around triggers conditions actions, forge
    # lables and strings" -- Fusion's default QProgressBar is a rounded, bordered pill sitting
    # directly above those lines.
    assert "border: none" in panel.stats_progress.styleSheet()


def test_starts_with_no_project_placeholder_shown_and_boxes_hidden(panel: ExplorerPanel) -> None:
    assert panel._no_project_label.isVisible() is True
    assert panel.script_section.isVisible() is False
    assert panel.settings_section.isVisible() is False
    assert panel.stats_section.isVisible() is False


def test_open_project_shows_the_script_and_settings_boxes_rooted_at_it(
    panel: ExplorerPanel, tmp_path: Path
) -> None:
    folder = tmp_path / "project"
    folder.mkdir()

    panel.open_project(folder)

    assert panel._no_project_label.isVisible() is False
    assert panel.script_section.isVisible() is True
    assert panel.settings_section.isVisible() is True
    assert Path(panel._script_model.rootPath()) == folder / "script"
    assert Path(panel._settings_model.rootPath()) == folder / "settings"


def test_close_all_projects_restores_the_placeholder(panel: ExplorerPanel, tmp_path: Path) -> None:
    folder = tmp_path / "project"
    folder.mkdir()
    panel.open_project(folder)

    panel.close_all_projects()

    assert panel._no_project_label.isVisible() is True
    assert panel.script_section.isVisible() is False
    assert panel.settings_section.isVisible() is False


def test_opening_a_nonexistent_project_folder_is_a_no_op(panel: ExplorerPanel, tmp_path: Path) -> None:
    panel.open_project(tmp_path / "does-not-exist")

    assert panel._no_project_label.isVisible() is True
    assert panel.script_section.isVisible() is False
    assert panel.open_projects == []


# -- Script/Settings boxes (PROMPT.md: "boxes like Personal Game Variants for Script and Settings")


def test_script_and_settings_sections_are_hidden_with_no_project_open(panel: ExplorerPanel) -> None:
    assert panel.script_section.isVisible() is False
    assert panel.settings_section.isVisible() is False


def test_opening_a_project_points_the_script_and_settings_trees_at_its_own_subfolders(
    panel: ExplorerPanel, tmp_path: Path
) -> None:
    folder = tmp_path / "project"
    (folder / "script").mkdir(parents=True)
    (folder / "settings").mkdir(parents=True)

    panel.open_project(folder)

    assert panel.script_section.isVisible() is True
    assert panel.settings_section.isVisible() is True
    assert Path(panel._script_model.rootPath()) == folder / "script"
    assert Path(panel._settings_model.rootPath()) == folder / "settings"


def test_closing_the_last_project_hides_the_script_and_settings_sections_again(
    panel: ExplorerPanel, tmp_path: Path
) -> None:
    folder = tmp_path / "project"
    folder.mkdir()
    panel.open_project(folder)

    panel.close_all_projects()

    assert panel.script_section.isVisible() is False
    assert panel.settings_section.isVisible() is False


def test_clicking_a_file_in_the_script_section_emits_file_activated(
    panel: ExplorerPanel, qtbot, tmp_path: Path
) -> None:
    folder = tmp_path / "project"
    (folder / "script").mkdir(parents=True)
    output_txt = folder / "script" / "output.txt"
    output_txt.write_text("-- script --", encoding="utf-8")
    panel.open_project(folder)
    model = panel._script_model
    qtbot.waitUntil(lambda: model.rowCount(panel.script_tree.rootIndex()) > 0, timeout=2000)

    activated: list[Path] = []
    panel.file_activated.connect(activated.append)
    panel.script_tree.clicked.emit(model.index(str(output_txt)))

    assert activated == [output_txt]


# -- the Stats box (PROMPT.md: "please also add a stats view into the dashboard") ----------------


def test_stats_box_shows_the_placeholder_with_no_project_open(panel: ExplorerPanel) -> None:
    assert panel.stats_section.isVisible() is False
    assert "No build stats" in panel.stats_label.text()


def test_no_stats_file_shows_the_placeholder_and_hides_the_progress_bar(
    panel: ExplorerPanel, tmp_path: Path
) -> None:
    folder = tmp_path / "project"
    (folder / "build").mkdir(parents=True)  # no stats.autogenerated.json written

    panel.open_project(folder)

    assert panel.stats_progress.isVisible() is False
    assert panel.stats_counts_label.isVisible() is False
    assert "No build stats" in panel.stats_label.text()


def test_a_real_stats_file_populates_the_progress_bar_and_counts(
    panel: ExplorerPanel, tmp_path: Path
) -> None:
    import json

    folder = tmp_path / "project"
    build_dir = folder / "build"
    build_dir.mkdir(parents=True)
    (build_dir / "stats.autogenerated.json").write_text(
        json.dumps(
            {
                "space": {
                    "bits": {
                        "maximum": 100, "header": 1, "header_strings": 1, "cg_options": 1,
                        "team_config": 1, "script_traits": 1, "script_options": 1,
                        "script_strings": 1, "option_toggles": 1, "rating_params": 1,
                        "map_perms": 1, "script_content": 1, "script_stats": 1,
                        "script_widgets": 1, "forge_labels": 1, "title_update_1": 1,
                    },
                    "bytes_used": 100,
                    "bytes_max": 200,
                    "percent": 50.0,
                },
                "counts": {
                    "triggers": 3, "conditions": 4, "actions": 5, "forge_labels": 1,
                    "strings": 2, "script_options": 0, "script_stats": 0,
                    "script_traits": 0, "script_widgets": 0,
                },
            }
        ),
        encoding="utf-8",
    )

    panel.open_project(folder)

    assert panel.stats_progress.isVisible() is True
    assert panel.stats_progress.value() == 50
    # PROMPT.md: "please combine the percentage used bar to be: 10,874 / 20520 B used (53%) (and
    # with the progress bar background)" -- shown as the progress bar's own text, not a label line.
    assert "100" in panel.stats_progress.text() and "200" in panel.stats_progress.text()
    assert panel.stats_counts_label.isVisible() is True
    assert "Triggers: 3" in panel.stats_counts_label.text()
    # PROMPT.md: "fix the panel icon width so that trigger conditions and actions should always
    # display on the same line" -- word-wrap off is what actually guarantees that (see
    # ExplorerPanel.__init__'s own comment); a wrapping label would still split it in two given a
    # narrow enough panel.
    assert panel.stats_counts_label.wordWrap() is False


def _write_strings_json(path: Path, entries: int) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "meta": {"name": [], "description": [], "category": []},
                "teams": [],
                "script_strings": [{"index": i, "text": f"str{i}"} for i in range(entries)],
            }
        ),
        encoding="utf-8",
    )


def test_stats_box_shows_the_strings_count_even_with_no_build_stats(
    panel: ExplorerPanel, tmp_path: Path
) -> None:
    # PROMPT.md: "please also make stats include[] strings.json" -- settings/strings.json is
    # written for every project, multiplayer or not, unlike build/stats.autogenerated.json (only a
    # compiled multiplayer gametype gets one) -- so a project with no build stats yet should still
    # show a strings count.
    folder = tmp_path / "project"
    _write_strings_json(folder / "settings" / "strings.json", 5)

    panel.open_project(folder)

    assert panel.stats_progress.isVisible() is False
    assert "Strings: 5" in panel.stats_label.text()
    assert "No build stats" not in panel.stats_label.text()


def test_stats_box_shows_both_build_stats_and_strings_count_together(
    panel: ExplorerPanel, tmp_path: Path
) -> None:
    import json

    folder = tmp_path / "project"
    build_dir = folder / "build"
    build_dir.mkdir(parents=True)
    (build_dir / "stats.autogenerated.json").write_text(
        json.dumps(
            {
                "space": {
                    "bits": {
                        "maximum": 100, "header": 1, "header_strings": 1, "cg_options": 1,
                        "team_config": 1, "script_traits": 1, "script_options": 1,
                        "script_strings": 1, "option_toggles": 1, "rating_params": 1,
                        "map_perms": 1, "script_content": 1, "script_stats": 1,
                        "script_widgets": 1, "forge_labels": 1, "title_update_1": 1,
                    },
                    "bytes_used": 100,
                    "bytes_max": 200,
                    "percent": 50.0,
                },
                "counts": {
                    "triggers": 3, "conditions": 4, "actions": 5, "forge_labels": 1,
                    "strings": 2, "script_options": 0, "script_stats": 0,
                    "script_traits": 0, "script_widgets": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    _write_strings_json(folder / "settings" / "strings.json", 7)

    panel.open_project(folder)

    assert panel.stats_progress.isVisible() is True
    assert "Triggers: 3" in panel.stats_counts_label.text()
    # PROMPT.md: "Forge labels and Strings should be on the same line"
    lines = panel.stats_label.text().splitlines()
    forge_line = next(line for line in lines if "Forge Labels" in line)
    assert "Strings: 7" in forge_line


def test_refresh_stats_re_reads_the_stats_file_for_the_current_project(
    panel: ExplorerPanel, tmp_path: Path
) -> None:
    folder = tmp_path / "project"
    build_dir = folder / "build"
    build_dir.mkdir(parents=True)
    panel.open_project(folder)
    assert panel.stats_progress.isVisible() is False

    import json

    (build_dir / "stats.autogenerated.json").write_text(
        json.dumps(
            {
                "space": {
                    "bits": {
                        "maximum": 8, "header": 1, "header_strings": 1, "cg_options": 1,
                        "team_config": 1, "script_traits": 1, "script_options": 1,
                        "script_strings": 0, "option_toggles": 0, "rating_params": 0,
                        "map_perms": 0, "script_content": 0, "script_stats": 0,
                        "script_widgets": 0, "forge_labels": 0, "title_update_1": 0,
                    },
                    "bytes_used": 1,
                    "bytes_max": 2,
                    "percent": 50.0,
                },
                "counts": {
                    "triggers": 0, "conditions": 0, "actions": 0, "forge_labels": 0,
                    "strings": 0, "script_options": 0, "script_stats": 0,
                    "script_traits": 0, "script_widgets": 0,
                },
            }
        ),
        encoding="utf-8",
    )

    panel.refresh_stats()

    assert panel.stats_progress.isVisible() is True


# -- collapsible sections -------------------------------------------------------------------------


def test_dashboard_sections_start_expanded(panel: ExplorerPanel) -> None:
    # PROMPT.md: "we then want boxes like Personal Game Variants for Script and Settings" (open by
    # default, unlike that now-removed section) -- Stats/Settings/Script are all central to the
    # active project, not secondary, so they start expanded rather than collapsed.
    for section in (panel.stats_section, panel.settings_section, panel.script_section):
        assert section.expanded is True


def test_clicking_a_section_header_collapses_and_expands_it(
    panel: ExplorerPanel, qtbot, tmp_path: Path
) -> None:
    # A project must be open, or settings_section itself (not just its body) is hidden -- so
    # body.isVisible() (which reflects the whole ancestor chain, not just the toggle's own state)
    # would read False regardless of what's toggled here.
    folder = tmp_path / "project"
    folder.mkdir()
    panel.open_project(folder)

    qtbot.mouseClick(panel.settings_section._toggle, Qt.MouseButton.LeftButton)

    assert panel.settings_section.expanded is False
    assert panel.settings_section.body.isVisible() is False

    qtbot.mouseClick(panel.settings_section._toggle, Qt.MouseButton.LeftButton)

    assert panel.settings_section.expanded is True
    assert panel.settings_section.body.isVisible() is True


# -- clicking a file opens it ----------------------------------------------------------------------


def test_clicking_a_file_in_the_settings_section_via_the_real_signal_emits_file_activated(
    panel: ExplorerPanel, qtbot, tmp_path: Path
) -> None:
    # Unlike test_clicking_a_file_in_the_script_section_emits_file_activated above (which drives
    # the private handler directly), this fires the tree's own `clicked` signal -- confirming the
    # Settings box really is wired up.
    folder = tmp_path / "project"
    folder.mkdir()
    panel.open_project(folder)
    file_path = folder / "settings" / "settings.json"
    file_path.write_text("{}", encoding="utf-8")
    model = panel._settings_model
    # rootIndex() is re-fetched fresh inside the lambda (not captured once beforehand) --
    # QFileSystemModel can rebuild its internal node tree the first time it visits a brand new
    # subtree, silently invalidating a QModelIndex captured before that settles; querying a stale
    # one afterward is undefined behavior (observed: wrong rows, or an outright native crash).
    qtbot.waitUntil(lambda: model.rowCount(panel.settings_tree.rootIndex()) > 0, timeout=2000)

    activated: list[Path] = []
    panel.file_activated.connect(activated.append)
    panel.settings_tree.clicked.emit(model.index(str(file_path)))

    assert activated == [file_path]


def test_clicking_a_folder_does_not_emit_file_activated(panel: ExplorerPanel, qtbot, tmp_path: Path) -> None:
    folder = tmp_path / "project"
    (folder / "script" / "subfolder").mkdir(parents=True)
    panel.open_project(folder)
    model = panel._script_model
    qtbot.waitUntil(lambda: model.rowCount(panel.script_tree.rootIndex()) > 0, timeout=2000)
    dir_index = model.index(str(folder / "script" / "subfolder"))

    activated: list[Path] = []
    panel.file_activated.connect(activated.append)
    panel._on_tree_clicked(model, dir_index)

    assert activated == []


def test_an_invalid_index_does_not_emit_file_activated(panel: ExplorerPanel) -> None:
    from PyQt6.QtCore import QModelIndex

    activated: list[Path] = []
    panel.file_activated.connect(activated.append)

    panel._on_tree_clicked(panel._script_model, QModelIndex())

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


def test_section_headers_are_10_percent_smaller_than_the_panel_font(panel: ExplorerPanel) -> None:
    panel_size = panel.font().pointSizeF()

    for section in (panel.stats_section, panel.settings_section, panel.script_section):
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
    (folder / "settings").mkdir(parents=True)
    (folder / "settings" / "settings.json").write_text(
        '{"meta": {"title": "Slayer Plus"}}', encoding="utf-8"
    )

    panel.open_project(folder)

    assert panel.project_tabs.isVisible() is True
    assert panel.project_tabs.count() == 1
    assert panel.project_tabs.tabText(0) == "Slayer Plus"
    assert panel.open_projects == [folder]
    assert panel.current_folder == folder


def test_open_project_tab_falls_back_to_the_folder_name_without_a_settings_json(
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
    assert Path(panel._settings_model.rootPath()) == second / "settings"


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
    assert panel.script_section.isVisible() is False
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


# -- no-project spacer -----------------------------------------------------------------------


def test_no_project_spacer_is_visible_only_with_no_project_open(panel: ExplorerPanel, tmp_path: Path) -> None:
    assert panel._no_project_spacer.isVisible() is True

    folder = tmp_path / "abcd1234"
    folder.mkdir()
    panel.open_project(folder)
    assert panel._no_project_spacer.isVisible() is False

    panel.close_project(folder)
    assert panel._no_project_spacer.isVisible() is True
