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
    assert panel.history_list.isVisible() is False


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
    assert panel.history_list.count() == 1


def test_set_project_none_clears_and_disables_everything(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)

    panel.set_project(None)

    assert panel.branch_combo.isEnabled() is False
    assert panel.branch_combo.count() == 0


def test_refresh_lists_every_branch_and_marks_stamps_in_history(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.stamp(folder, "v1")
    vcs.create_branch(folder, "feature")

    panel.set_project(folder)

    assert {panel.branch_combo.itemText(i) for i in range(panel.branch_combo.count())} == {
        vcs.DEFAULT_BRANCH,
        "feature",
    }
    items = [panel.history_list.item(i).text() for i in range(panel.history_list.count())]
    assert any(item.startswith("* v1") for item in items)


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


def test_selecting_a_history_row_enables_restore(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)
    assert panel.restore_button.isEnabled() is False

    panel.history_list.setCurrentRow(0)

    assert panel.restore_button.isEnabled() is True


def test_restore_button_emits_restore_requested_with_the_snapshots_sha(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    sha = vcs.stamp(folder, "v1")
    panel.set_project(folder)
    panel.history_list.setCurrentRow(0)  # newest first -- the v1 stamp
    emitted = []
    panel.restore_requested.connect(emitted.append)

    panel.restore_button.click()

    assert emitted == [sha]


def test_refresh_disables_restore_until_a_row_is_selected_again(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)
    panel.history_list.setCurrentRow(0)
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
