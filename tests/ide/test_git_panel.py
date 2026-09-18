from pathlib import Path

import pytest

from in_reach.app import vcs
from in_reach.ide.git_panel import GitPanel


@pytest.fixture
def panel(qtbot) -> GitPanel:
    widget = GitPanel()
    qtbot.addWidget(widget)
    widget.show()
    return widget


def _project(tmp_path: Path) -> Path:
    folder = tmp_path / "abcd1234"
    folder.mkdir()
    (folder / "Notes.txt").write_text("hi\n", encoding="utf-8")
    return folder


def test_starts_disabled_with_no_project(panel: GitPanel) -> None:
    assert panel.branch_combo.isEnabled() is False
    assert panel.new_branch_button.isEnabled() is False
    assert panel.stamp_button.isEnabled() is False
    assert panel.commit_button.isEnabled() is False
    assert panel._graph_scroll.isVisible() is False


def test_a_project_with_no_history_yet_still_shows_the_empty_state(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)  # no vcs.init() call

    panel.set_project(folder)

    assert panel.branch_combo.isEnabled() is False
    assert panel._empty_label.isVisible() is True


def test_set_project_enables_controls_and_lists_the_branch(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)

    panel.set_project(folder)

    assert panel.branch_combo.isEnabled() is True
    assert panel.new_branch_button.isEnabled() is True
    assert panel.stamp_button.isEnabled() is True
    assert panel.branch_combo.currentText() == vcs.DEFAULT_BRANCH
    assert panel.graph.row_count() == 1


def test_set_project_none_clears_and_disables_everything(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)

    panel.set_project(None)

    assert panel.branch_combo.isEnabled() is False
    assert panel.branch_combo.count() == 0


def test_refresh_lists_every_branch_and_marks_stamps_in_the_graph(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.stamp(folder, "v1")
    vcs.create_branch(folder, "feature")

    panel.set_project(folder)

    assert {panel.branch_combo.itemText(i) for i in range(panel.branch_combo.count())} == {
        vcs.DEFAULT_BRANCH,
        "feature",
    }
    stamp_messages = [row.snapshot.stamp_message for row in panel.graph._rows if row.snapshot.is_stamp]
    assert stamp_messages == ["v1"]


def test_stamp_button_emits_stamp_requested_with_the_typed_message(
    panel: GitPanel, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)
    monkeypatch.setattr(panel, "_ask_text", lambda title, label: "First release")
    emitted = []
    panel.stamp_requested.connect(emitted.append)

    panel.stamp_button.click()

    assert emitted == ["First release"]


def test_stamp_button_does_not_emit_when_the_dialog_is_cancelled(
    panel: GitPanel, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)
    monkeypatch.setattr(panel, "_ask_text", lambda title, label: "")
    emitted = []
    panel.stamp_requested.connect(emitted.append)

    panel.stamp_button.click()

    assert emitted == []


def test_new_branch_button_emits_new_branch_requested_with_the_typed_name(
    panel: GitPanel, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)
    monkeypatch.setattr(panel, "_ask_text", lambda title, label: "feature")
    emitted = []
    panel.new_branch_requested.connect(emitted.append)

    panel.new_branch_button.click()

    assert emitted == ["feature"]


def test_switching_the_branch_combo_emits_switch_branch_requested(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.create_branch(folder, "feature")
    vcs.switch_branch(folder, vcs.DEFAULT_BRANCH)
    panel.set_project(folder)
    emitted = []
    panel.switch_branch_requested.connect(emitted.append)

    panel.branch_combo.setCurrentText("feature")

    assert emitted == ["feature"]


def test_delete_branch_button_emits_delete_branch_requested_for_the_selected_branch(
    panel: GitPanel, tmp_path: Path
) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.create_branch(folder, "feature")
    vcs.switch_branch(folder, vcs.DEFAULT_BRANCH)
    panel.set_project(folder)
    panel.branch_combo.setCurrentText("feature")
    emitted = []
    panel.delete_branch_requested.connect(emitted.append)

    panel.delete_branch_button.click()

    assert emitted == ["feature"]


def test_compare_combos_list_branches_and_stamps(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.stamp(folder, "v1")
    vcs.create_branch(folder, "feature")

    panel.set_project(folder)

    labels = {panel.compare_a_combo.itemText(i) for i in range(panel.compare_a_combo.count())}
    assert labels == {vcs.DEFAULT_BRANCH, "feature", "Stamp: v1"}


def test_compare_button_emits_compare_requested_with_the_selected_refs(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.create_branch(folder, "feature")
    panel.set_project(folder)
    emitted = []
    panel.compare_requested.connect(lambda a, b: emitted.append((a, b)))

    # Branches list alphabetically -- "feature" sorts before "main".
    panel.compare_a_combo.setCurrentIndex(0)
    panel.compare_b_combo.setCurrentIndex(1)
    panel.compare_button.click()

    assert emitted == [("feature", vcs.DEFAULT_BRANCH)]


def test_selecting_a_graph_row_enables_restore(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)
    assert panel.restore_button.isEnabled() is False

    panel.graph.select_row(0)

    assert panel.restore_button.isEnabled() is True


def test_restore_button_emits_restore_requested_with_the_snapshots_sha(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    sha = vcs.stamp(folder, "v1")
    panel.set_project(folder)
    panel.graph.select_row(0)  # newest first -- the v1 stamp
    emitted = []
    panel.restore_requested.connect(emitted.append)

    panel.restore_button.click()

    assert emitted == [sha]


def test_refresh_disables_restore_until_a_row_is_selected_again(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)
    panel.graph.select_row(0)
    assert panel.restore_button.isEnabled() is True

    panel.refresh()

    assert panel.restore_button.isEnabled() is False


def test_refreshing_the_combo_never_emits_switch_branch_requested(panel: GitPanel, tmp_path: Path) -> None:
    # A repopulate-then-reselect-the-current-branch pass (refresh()) shouldn't read as the user
    # asking to switch to the branch that's already checked out.
    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)
    emitted = []
    panel.switch_branch_requested.connect(emitted.append)

    panel.refresh()

    assert emitted == []


# -- "Changes" / commit (PROMPT.md: "add committed changes and uncommitted changes[;] ... committing
# changes should require a commit message") -------------------------------------------------------


def test_a_clean_project_shows_zero_uncommitted_changes(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)

    panel.set_project(folder)

    assert panel.uncommitted_count == 0
    assert panel.changes_label.text() == "Changes (0)"
    assert panel.changes_list.count() == 0
    assert panel.commit_button.isEnabled() is False


def test_an_edited_file_shows_up_as_an_uncommitted_change(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "Notes.txt").write_text("edited\n", encoding="utf-8")

    panel.set_project(folder)

    assert panel.uncommitted_count == 1
    assert panel.changes_label.text() == "Changes (1)"
    assert panel.changes_list.item(0).text() == "M  Notes.txt"


def test_clicking_a_changed_file_emits_diff_file_requested_with_its_path(panel: GitPanel, tmp_path: Path) -> None:
    # PROMPT.md: "when clicking on changes to a file (in the changes tab) a tab should appear
    # showing the original on the left and highlighted changes on the right (like vscode git)".
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "Notes.txt").write_text("edited\n", encoding="utf-8")
    panel.set_project(folder)
    emitted = []
    panel.diff_file_requested.connect(emitted.append)

    panel.changes_list.itemClicked.emit(panel.changes_list.item(0))

    assert emitted == ["Notes.txt"]


def test_commit_button_stays_disabled_with_no_message_even_if_something_changed(
    panel: GitPanel, tmp_path: Path
) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "Notes.txt").write_text("edited\n", encoding="utf-8")
    panel.set_project(folder)

    assert panel.commit_button.isEnabled() is False

    panel.commit_message_edit.setText("fix notes")

    assert panel.commit_button.isEnabled() is True


def test_commit_button_stays_disabled_with_a_message_but_nothing_uncommitted(
    panel: GitPanel, tmp_path: Path
) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)

    panel.commit_message_edit.setText("nothing to commit")

    assert panel.commit_button.isEnabled() is False


def test_commit_button_emits_commit_requested_with_the_typed_message(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "Notes.txt").write_text("edited\n", encoding="utf-8")
    panel.set_project(folder)
    panel.commit_message_edit.setText("fix notes")
    emitted = []
    panel.commit_requested.connect(emitted.append)

    panel.commit_button.click()

    assert emitted == ["fix notes"]


def test_pressing_enter_in_the_commit_message_box_also_commits(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "Notes.txt").write_text("edited\n", encoding="utf-8")
    panel.set_project(folder)
    panel.commit_message_edit.setText("fix notes")
    emitted = []
    panel.commit_requested.connect(emitted.append)

    panel.commit_message_edit.returnPressed.emit()

    assert emitted == ["fix notes"]


def test_clear_commit_message_empties_the_box(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)
    panel.commit_message_edit.setText("something")

    panel.clear_commit_message()

    assert panel.commit_message_edit.text() == ""
