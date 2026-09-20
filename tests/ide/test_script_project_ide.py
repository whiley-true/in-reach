"""The IDE's face for script projects: the Problems tab, the Scripts view, and the commands that drive them."""
import json
import sys
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QMessageBox

sys.path.insert(0, str(Path(__file__).parents[1] / "app" / "script_project"))
from hill_project import hill_rush  # noqa: E402

from in_reach.app import new_project, script_preprocess  # noqa: E402
from in_reach.app.rvt.compile import BuildMessage, BuildResult  # noqa: E402
from in_reach.app.script_project import ProjectDiagnostic, is_linked, link  # noqa: E402
from in_reach.ide.main_window import MainWindow  # noqa: E402
from in_reach.ide.problems_panel import (  # noqa: E402
    Problem, ProblemsPanel, problems_from_build, problems_from_diagnostics,
)
from in_reach.ide.scripts_panel import ScriptsPanel, budget_rows  # noqa: E402


@pytest.fixture
def project_window(qtbot, tmp_path: Path):
    project_dir = tmp_path / ".in-reach"
    project_dir.mkdir()
    (project_dir / ".env").write_text("", encoding="utf-8")
    win = MainWindow(root_dir=tmp_path)
    qtbot.addWidget(win)
    win.show()
    return win


def _single_file_project(tmp_path: Path, name: str = "abcd1234") -> Path:
    folder = tmp_path / name
    (folder / "settings").mkdir(parents=True)
    (folder / "settings" / "settings.json").write_text(json.dumps({"meta": {"title": "T"}}), encoding="utf-8")
    (folder / "script").mkdir()
    (folder / "script" / "output.txt").write_text("global.number[0] = 1\n", encoding="utf-8")
    return folder


def _linked_project(tmp_path: Path, **changes: str | None) -> Path:
    folder = tmp_path / "linked01"
    (folder / "settings").mkdir(parents=True)
    (folder / "settings" / "settings.json").write_text(json.dumps({"meta": {"title": "Hill"}}), encoding="utf-8")
    return hill_rush(folder, **changes)


# -- the Problems panel by itself -------------------------------------------------------------------------


def test_problems_are_listed_errors_first_then_by_file_and_line(qtbot) -> None:
    panel = ProblemsPanel()
    qtbot.addWidget(panel)

    panel.set_problems([
        Problem("warning", "w", Path("b.mgl"), 1),
        Problem("error", "e2", Path("a.mgl"), 9),
        Problem("error", "e1", Path("a.mgl"), 2),
        Problem("notice", "n"),
    ])

    assert [panel.tree.topLevelItem(i).text(1) for i in range(4)] == ["e1", "e2", "w", "n"]
    assert panel.counts() == (2, 1) and panel.summary.text() == "2 errors, 1 warning, 1 notice"


def test_no_problems_says_so_and_a_single_error_is_singular(qtbot) -> None:
    panel = ProblemsPanel()
    qtbot.addWidget(panel)
    assert panel.summary.text() == "No problems"

    panel.set_problems([Problem("error", "x")])

    assert panel.summary.text() == "1 error"
    panel.clear()
    assert panel.summary.text() == "No problems" and panel.tree.topLevelItemCount() == 0


def test_setting_problems_reports_the_counts(qtbot) -> None:
    panel = ProblemsPanel()
    qtbot.addWidget(panel)

    with qtbot.waitSignal(panel.counts_changed) as signal:
        panel.set_problems([Problem("error", "a"), Problem("warning", "b"), Problem("warning", "c")])

    assert signal.args == [1, 2]


def test_activating_a_row_asks_for_its_file_and_line(qtbot) -> None:
    panel = ProblemsPanel()
    qtbot.addWidget(panel)
    panel.set_problems([Problem("error", "boom", Path("x/setup.mgl"), 7)])

    with qtbot.waitSignal(panel.open_requested) as signal:
        panel.tree.itemActivated.emit(panel.tree.topLevelItem(0), 1)

    assert signal.args == [Path("x/setup.mgl"), 7]


def test_a_row_with_no_file_opens_nothing(qtbot) -> None:
    panel = ProblemsPanel()
    qtbot.addWidget(panel)
    panel.set_problems([Problem("error", "the build as a whole")])
    seen = []
    panel.open_requested.connect(lambda *a: seen.append(a))

    panel.tree.itemActivated.emit(panel.tree.topLevelItem(0), 1)

    assert seen == []


def test_the_where_column_names_the_file_and_line(qtbot) -> None:
    panel = ProblemsPanel()
    qtbot.addWidget(panel)
    panel.set_problems([Problem("error", "a", Path("dir/setup.mgl"), 4), Problem("error", "b", Path("dir/project.toml"))])

    assert {panel.tree.topLevelItem(i).text(2) for i in range(2)} == {"setup.mgl:4", "project.toml"}


def test_diagnostics_become_problems_at_paths_under_script(tmp_path: Path) -> None:
    folder = tmp_path / "p"
    diagnostics = [
        ProjectDiagnostic(severity="error", code="IR006", message="dup", file="blocks/setup.mgl", line=2, col=3, hint="rename it"),
        ProjectDiagnostic(severity="error", code="settings-invalid", message="bad", file="../settings/script_settings.json"),
        ProjectDiagnostic(severity="warning", code="x", message="whole project", file=""),
    ]

    first, second, third = problems_from_diagnostics(folder, diagnostics)

    assert first.path == folder / "script" / "blocks" / "setup.mgl" and (first.line, first.column) == (2, 4)
    assert first.message == "dup (rename it)" and first.code == "IR006"
    assert second.path == folder / "settings" / "script_settings.json"  # the ".." is resolved
    assert third.path is None and third.column == 0


def test_a_linked_builds_messages_are_located_by_their_own_file() -> None:
    folder = Path("proj")
    result = BuildResult(
        success=False,
        errors=[BuildMessage(line=4, col=2, text="bad action", file="blocks/win.mgl")],
        warnings=[BuildMessage(line=0, col=0, text="near the cap", file="../build/link_map.json", code="IR012")],
        failure="Megalo compile failed",
    )

    failure, error, warning = problems_from_build(folder, result, linked=True)

    assert failure == Problem("error", "Megalo compile failed")
    assert error.path == folder / "script" / "blocks" / "win.mgl" and error.line == 4
    assert warning.path == folder / "build" / "link_map.json" and warning.code == "IR012"


def test_a_single_file_builds_positioned_messages_are_about_output_txt() -> None:
    folder = Path("proj")
    result = BuildResult(
        success=False,
        errors=[BuildMessage(line=3, col=1, text="oops")],
        notices=[BuildMessage(line=0, col=0, text="Added forge label(s)")],
    )

    error, notice = problems_from_build(folder, result, linked=False)

    assert error.path == folder / "script" / "output.txt" and error.line == 3
    assert notice.path is None and notice.severity == "notice"


# -- the Scripts view by itself ---------------------------------------------------------------------------


def test_budget_rows_list_pools_tables_and_measured_counters() -> None:
    link_map = {"budget": {
        "global.number": {"cap": 12, "used": 3}, "traits": {"cap": 16, "used": 1},
        "counters": {"actions": {"cap": 1024, "used": 90}, "strings": {"used": 4}},
    }}

    assert budget_rows(link_map) == [
        ("global.number", 3, 12), ("traits", 1, 16), ("actions", 90, 1024), ("strings", 4, None),
    ]
    assert budget_rows({}) == []


def test_the_scripts_view_shows_a_script_projects_modules_blocks_budget_and_fusion(qtbot, tmp_path: Path) -> None:
    folder = _linked_project(tmp_path)
    result = link(folder, write=False)
    panel = ScriptsPanel()
    qtbot.addWidget(panel)
    panel.show()

    panel.show_link(folder, result, ["dev", "release"], "dev")

    assert panel.linked_box.isVisible() and not panel.unlinked_box.isVisible()
    assert panel.status_label.text() == "Links cleanly."
    assert [panel.modules_tree.topLevelItem(i).text(0) for i in range(2)] == ["hill_score 1.0.0", "hill_buff 0.0.0"]
    assert panel.modules_tree.topLevelItem(0).text(1) == "HILL_PASS"
    assert [panel.blocks_tree.topLevelItem(i).text(0) for i in range(3)] == ["SETUP", "HILL_PASS", "WIN_CHECK"]
    assert "fragments only" in panel.blocks_tree.topLevelItem(1).text(1)
    rows = {panel.budget_tree.topLevelItem(i).text(0): panel.budget_tree.topLevelItem(i).text(1) for i in range(panel.budget_tree.topLevelItemCount())}
    assert rows["global.number"] == "2" and rows["traits"] == "1"
    assert "HILL_PASS: hill_score.score + hill_buff.buff" in panel.fusion_tree.topLevelItem(0).text(0)


def test_the_profile_picker_lists_profiles_marks_the_active_one_and_reports_a_pick(qtbot, tmp_path: Path) -> None:
    folder = _linked_project(tmp_path)
    panel = ScriptsPanel()
    qtbot.addWidget(panel)
    panel.show_link(folder, link(folder, write=False), ["dev", "release"], "release")

    assert [panel.profile_combo.itemText(i) for i in range(panel.profile_combo.count())] == ["dev", "release", "No profile"]
    assert panel.profile_combo.currentText() == "release"

    with qtbot.waitSignal(panel.profile_selected) as signal:
        panel.profile_combo.activated.emit(0)
    assert signal.args == ["dev"]
    with qtbot.waitSignal(panel.profile_selected) as signal:
        panel.profile_combo.activated.emit(2)
    assert signal.args == [None]


def test_a_module_row_opens_its_first_file(qtbot, tmp_path: Path) -> None:
    folder = _linked_project(tmp_path)
    panel = ScriptsPanel()
    qtbot.addWidget(panel)
    panel.show_link(folder, link(folder, write=False), [], None)

    with qtbot.waitSignal(panel.open_file_requested) as signal:
        panel.modules_tree.itemActivated.emit(panel.modules_tree.topLevelItem(0), 0)

    assert signal.args == [folder / "script" / "modules" / "hill_score" / "hill_score.mgl"]


def test_a_link_that_fails_says_so_and_a_near_full_pool_is_flagged(qtbot, tmp_path: Path) -> None:
    folder = _linked_project(tmp_path, blocks__setup_dot_mgl="-- @number a\n-- @number a\n")
    bad = link(folder, write=False)
    bad.link_map = {"budget": {"global.number": {"cap": 12, "used": 11}, "player.number": {"cap": 8, "used": 9}}}
    panel = ScriptsPanel()
    qtbot.addWidget(panel)

    panel.show_link(folder, bad, [], None)

    assert panel.status_label.text().startswith("1 error")
    warn, over = panel.budget_tree.topLevelItem(0), panel.budget_tree.topLevelItem(1)
    assert warn.foreground(0).color().name() != over.foreground(0).color().name()
    assert over.toolTip(0) == "112% of 8"


def test_an_empty_link_map_and_nothing_to_fuse_say_so(qtbot, tmp_path: Path) -> None:
    folder = _linked_project(tmp_path)
    result = link(folder, write=False)
    result.link_map = {}
    panel = ScriptsPanel()
    qtbot.addWidget(panel)

    panel.show_link(folder, result, [], None)

    assert panel.budget_tree.topLevelItem(0).text(0) == "nothing linked yet"
    assert panel.fusion_tree.topLevelItem(0).text(0) == "nothing to fuse"


def test_a_single_file_project_offers_to_create_a_script_project(qtbot, tmp_path: Path) -> None:
    panel = ScriptsPanel()
    qtbot.addWidget(panel)
    panel.show()

    panel.show_unlinked(_single_file_project(tmp_path))

    assert panel.unlinked_box.isVisible() and not panel.linked_box.isVisible()
    with qtbot.waitSignal(panel.create_project_requested):
        panel.create_button.click()


def test_no_project_shows_neither_box(qtbot) -> None:
    panel = ScriptsPanel()
    qtbot.addWidget(panel)
    panel.show()

    assert not panel.unlinked_box.isVisible() and not panel.linked_box.isVisible()


# -- in the window ----------------------------------------------------------------------------------------


def test_opening_a_script_project_fills_the_scripts_view_and_leaves_problems_empty(project_window, tmp_path: Path) -> None:
    project_window._on_project_opened(_linked_project(tmp_path))

    assert not project_window.scripts_panel.linked_box.isHidden()
    assert project_window.bottom_panel.problems_panel.problems() == []
    assert project_window.bottom_panel.tabText(1) == "Problems"


def test_opening_a_single_file_project_shows_the_offer_to_create_one(project_window, tmp_path: Path) -> None:
    project_window._on_project_opened(_single_file_project(tmp_path))

    assert not project_window.scripts_panel.unlinked_box.isHidden()


def test_saving_a_broken_module_lists_the_problem_and_counts_it_in_the_tab(project_window, tmp_path: Path) -> None:
    folder = _linked_project(tmp_path)
    project_window._on_project_opened(folder)
    (folder / "script" / "blocks" / "setup.mgl").write_text("-- @number a\n-- @number a\n", encoding="utf-8")

    project_window._on_file_saved(folder / "script" / "blocks" / "setup.mgl")

    [problem] = [p for p in project_window.bottom_panel.problems_panel.problems() if p.code == "IR006"]
    assert problem.path == folder / "script" / "blocks" / "setup.mgl" and problem.line == 2
    assert project_window.bottom_panel.tabText(1) == "Problems (1)"
    assert project_window.scripts_panel.status_label.text().startswith("1 error")


def test_fixing_it_clears_the_problems(project_window, tmp_path: Path) -> None:
    folder = _linked_project(tmp_path, blocks__setup_dot_mgl="-- @number a\n-- @number a\n")
    project_window._on_project_opened(folder)
    assert project_window.bottom_panel.problems_panel.counts() == (1, 0)

    (folder / "script" / "blocks" / "setup.mgl").write_text("-- @number a\n", encoding="utf-8")
    project_window._on_file_saved(folder / "script" / "blocks" / "setup.mgl")

    assert project_window.bottom_panel.problems_panel.problems() == []
    assert project_window.bottom_panel.tabText(1) == "Problems"


def test_activating_a_problem_opens_the_file_at_its_line(project_window, tmp_path: Path) -> None:
    folder = _linked_project(tmp_path, blocks__setup_dot_mgl="on init: do\nend\n-- @number a\n-- @number a\n")
    project_window._on_project_opened(folder)
    panel = project_window.bottom_panel.problems_panel

    panel.tree.itemActivated.emit(panel.tree.topLevelItem(0), 1)

    editor = project_window.main_panel.active_pane.widget(project_window.main_panel.active_pane.currentIndex())
    assert editor.path == folder / "script" / "blocks" / "setup.mgl"
    assert editor.textCursor().blockNumber() == 3  # 0-based -- line 4


def test_switching_profile_relinks(project_window, tmp_path: Path) -> None:
    folder = _linked_project(tmp_path)
    (folder / "script" / "env" / "release.env").write_text("FLAGS=RELEASE\n", encoding="utf-8")
    project_window._on_project_opened(folder)

    project_window._set_build_profile("release")

    assert script_preprocess.active_profile_name(folder) == "release"
    assert project_window.scripts_panel.profile_combo.currentText() == "release"


def test_check_script_project_shows_the_problems_tab_when_there_are_some(project_window, tmp_path: Path) -> None:
    folder = _linked_project(tmp_path, blocks__setup_dot_mgl="-- @number a\n-- @number a\n")
    project_window._on_project_opened(folder)
    project_window.bottom_panel.setCurrentIndex(0)

    project_window.check_script_project()

    assert project_window.bottom_panel.currentWidget() is project_window.bottom_panel.problems_panel


def test_check_script_project_on_a_single_file_project_explains(project_window, tmp_path: Path, monkeypatch) -> None:
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    project_window._on_project_opened(_single_file_project(tmp_path))

    project_window.check_script_project()

    assert len(shown) == 1 and "single file" in shown[0]


def test_link_script_project_writes_the_build_files_without_compiling(project_window, tmp_path: Path) -> None:
    folder = _linked_project(tmp_path)
    project_window._on_project_opened(folder)

    project_window.link_script_project()

    assert (folder / "build" / "Compiled.txt").is_file() and (folder / "build" / "link_map.json").is_file()
    assert not new_project.compiled_variant_path(folder).exists()
    assert project_window.activity_bar.apply_button.isEnabled()  # linked, but never built


def test_a_link_that_fails_brings_the_problems_tab_forward(project_window, tmp_path: Path) -> None:
    folder = _linked_project(tmp_path, blocks__setup_dot_mgl="-- @number a\n-- @number a\n")
    project_window._on_project_opened(folder)
    project_window.bottom_panel.setCurrentIndex(0)

    project_window.link_script_project()

    assert project_window.bottom_panel.currentWidget() is project_window.bottom_panel.problems_panel
    assert not (folder / "build" / "Compiled.txt").exists()


def test_create_script_project_turns_a_single_script_into_one(project_window, tmp_path: Path, monkeypatch) -> None:
    folder = _single_file_project(tmp_path)
    project_window._on_project_opened(folder)
    monkeypatch.setattr(project_window, "_confirm_create_script_project", lambda: True)

    project_window.create_script_project()

    assert is_linked(folder) and (folder / "script" / "blocks" / "main.mgl").read_text(encoding="utf-8") == "global.number[0] = 1\n"
    assert not project_window.scripts_panel.linked_box.isHidden()
    assert project_window.main_panel.active_pane.widget(project_window.main_panel.active_pane.currentIndex()).path == (
        folder / "script" / "blocks" / "main.mgl"
    )


def test_declining_create_script_project_changes_nothing(project_window, tmp_path: Path, monkeypatch) -> None:
    folder = _single_file_project(tmp_path)
    project_window._on_project_opened(folder)
    monkeypatch.setattr(project_window, "_confirm_create_script_project", lambda: False)

    project_window.create_script_project()

    assert not is_linked(folder)


def test_new_script_module_adds_it_and_opens_its_file(project_window, tmp_path: Path, monkeypatch) -> None:
    folder = _linked_project(tmp_path)
    project_window._on_project_opened(folder)
    monkeypatch.setattr(project_window, "_ask_module_name", lambda: "extras")

    project_window.new_script_module()

    assert (folder / "script" / "modules" / "extras" / "module.toml").is_file()
    tree = project_window.scripts_panel.modules_tree
    assert "extras 0.1.0" in [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]


def test_a_bad_module_name_is_reported_not_created(project_window, tmp_path: Path, monkeypatch) -> None:
    folder = _linked_project(tmp_path)
    project_window._on_project_opened(folder)
    monkeypatch.setattr(project_window, "_ask_module_name", lambda: "9 bad")
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(a[2]))

    project_window.new_script_module()

    assert len(shown) == 1 and "valid module name" in shown[0]
    assert not (folder / "script" / "modules" / "9 bad").exists()


def test_a_failed_build_puts_its_messages_on_the_problems_tab_at_their_source(project_window, tmp_path: Path) -> None:
    folder = _linked_project(tmp_path)
    project_window._on_project_opened(folder)
    result = BuildResult(
        success=False, errors=[BuildMessage(line=3, col=4, text="no such action", file="blocks/win_check.mgl")], failure="Megalo compile failed"
    )
    project_window.bottom_panel.setCurrentIndex(0)

    project_window._report_build_problems(folder, result)

    problems = project_window.bottom_panel.problems_panel.problems()
    assert [(p.path, p.line) for p in problems if p.line] == [(folder / "script" / "blocks" / "win_check.mgl", 3)]
    assert project_window.bottom_panel.currentWidget() is project_window.bottom_panel.problems_panel


def test_a_successful_build_adds_only_warnings_the_check_did_not_already_list(project_window, tmp_path: Path) -> None:
    folder = _linked_project(tmp_path)
    project_window._on_project_opened(folder)
    result = BuildResult(
        success=True,
        warnings=[BuildMessage(line=0, col=0, text="near the cap [IR012]", file="../build/link_map.json", code="IR012")],
        notices=[BuildMessage(line=0, col=0, text="Added forge label(s)")],
    )

    project_window._report_build_problems(folder, result)

    assert [p.code for p in project_window.bottom_panel.problems_panel.problems()] == ["IR012"]  # the notice is not a problem


def test_a_single_file_projects_failed_build_points_at_output_txt(project_window, tmp_path: Path) -> None:
    folder = _single_file_project(tmp_path)
    project_window._on_project_opened(folder)

    project_window._report_build_problems(
        folder, BuildResult(success=False, errors=[BuildMessage(line=2, col=1, text="oops")])
    )

    [problem] = project_window.bottom_panel.problems_panel.problems()
    assert problem.path == folder / "script" / "output.txt" and problem.line == 2


def test_the_new_commands_are_in_the_palette_and_the_view_menu(project_window) -> None:
    labels = {c.label for c in project_window.build_command_palette_commands()}

    assert {"View Problems", "Check Script Project", "Link Script Project", "Create Script Project", "New Script Module"} <= labels
    view_menu = project_window.top_bar.view_menu_button.menu()
    assert "View Problems" in [a.text() for a in view_menu.actions()]


def test_view_problems_opens_the_panel_on_the_problems_tab(project_window) -> None:
    project_window.bottom_panel.setCurrentIndex(0)

    project_window.view_problems()

    assert project_window.bottom_panel.currentWidget() is project_window.bottom_panel.problems_panel


def test_a_linked_projects_apply_is_enabled_until_it_is_built(project_window, tmp_path: Path) -> None:
    folder = _linked_project(tmp_path)
    project_window._on_project_opened(folder)

    assert project_window.activity_bar.apply_button.isEnabled()
