from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

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


def _trigger_action(menu, label: str) -> None:  # noqa: ANN001 -- QMenu
    action = next(a for a in menu.actions() if a.text() == label)
    action.trigger()


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


def test_stamp_button_emits_stamp_requested_with_the_typed_message_and_version(
    panel: GitPanel, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)  # stamped "gametype init" at v0.0.0
    panel.set_project(folder)
    monkeypatch.setattr(panel, "_ask_stamp_release", lambda major, minor, patch, message="": ("First release", "1.2.3"))
    emitted = []
    panel.stamp_requested.connect(lambda message, version: emitted.append((message, version)))

    panel.stamp_button.click()

    assert emitted == [("First release", "1.2.3")]


def test_stamp_button_does_not_emit_when_the_dialog_is_cancelled(
    panel: GitPanel, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)
    monkeypatch.setattr(panel, "_ask_stamp_release", lambda major, minor, patch, message="": None)
    emitted = []
    panel.stamp_requested.connect(lambda message, version: emitted.append((message, version)))

    panel.stamp_button.click()

    assert emitted == []


def test_stamp_button_seeds_the_dialog_from_the_last_stamped_version(
    panel: GitPanel, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _project(tmp_path)
    vcs.init(folder, stamp_message="gametype init")  # v0.0.0
    vcs.stamp(folder, "release one", version="1.2.3")
    panel.set_project(folder)
    seeded = []
    monkeypatch.setattr(
        panel,
        "_ask_stamp_release",
        lambda major, minor, patch, message="": seeded.append((major, minor, patch)) or None,
    )

    panel.stamp_button.click()

    assert seeded == [(1, 2, 3)]


def test_stamp_button_seeds_0_0_0_with_no_prior_stamp(
    panel: GitPanel, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)  # plain "Initial commit" -- no stamp, no version
    panel.set_project(folder)
    seeded = []
    monkeypatch.setattr(
        panel,
        "_ask_stamp_release",
        lambda major, minor, patch, message="": seeded.append((major, minor, patch)) or None,
    )

    panel.stamp_button.click()

    assert seeded == [(0, 0, 0)]


def test_stamp_button_warns_before_reusing_an_already_stamped_version(
    panel: GitPanel, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.stamp(folder, "release one", version="1.0.0")
    panel.set_project(folder)
    calls = []

    def fake_ask(major, minor, patch, message=""):
        calls.append((major, minor, patch, message))
        # First attempt reuses the already-stamped version and gets declined; second call is the
        # dialog reopening (see the "back at the release dialog" test below) -- the user cancels
        # out of it here, ending the whole stamp attempt.
        return ("release two", "1.0.0") if len(calls) == 1 else None

    monkeypatch.setattr(panel, "_ask_stamp_release", fake_ask)
    confirmed = []
    monkeypatch.setattr(panel, "_confirm_duplicate_version", lambda version: confirmed.append(version) or False)
    emitted = []
    panel.stamp_requested.connect(lambda message, version: emitted.append((message, version)))

    panel.stamp_button.click()

    assert confirmed == ["1.0.0"]
    assert emitted == []  # declined the overwrite warning -- no stamp requested
    assert len(calls) == 2  # declining reopened the dialog once more, per PROMPT.md below


def test_declining_the_duplicate_version_warning_reopens_the_dialog_seeded_with_what_they_typed(
    panel: GitPanel, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PROMPT.md: "also when stamping a release if a user aborts the stamp due to not re-stamping
    # the same version, the warning should close and they should be back at their release
    # dialog/window" -- not just kicked out of the whole stamp attempt, and not back at a *blank*
    # dialog either.
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.stamp(folder, "release one", version="1.0.0")
    panel.set_project(folder)
    calls = []

    def fake_ask(major, minor, patch, message=""):
        calls.append((major, minor, patch, message))
        # First attempt collides; the user (seeing the reopened dialog still has their message)
        # just bumps the patch number and resubmits.
        return ("release two", "1.0.0") if len(calls) == 1 else ("release two", "1.0.1")

    monkeypatch.setattr(panel, "_ask_stamp_release", fake_ask)
    monkeypatch.setattr(panel, "_confirm_duplicate_version", lambda version: False)
    emitted = []
    panel.stamp_requested.connect(lambda message, version: emitted.append((message, version)))

    panel.stamp_button.click()

    assert len(calls) == 2
    assert calls[0] == (1, 0, 0, "")  # seeded from the project's own last stamped version
    # Reopened seeded with the version just tried (not reset) and the message already typed.
    assert calls[1] == (1, 0, 0, "release two")
    assert emitted == [("release two", "1.0.1")]


def test_stamp_button_stamps_anyway_when_the_duplicate_version_warning_is_accepted(
    panel: GitPanel, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.stamp(folder, "release one", version="1.0.0")
    panel.set_project(folder)
    monkeypatch.setattr(panel, "_ask_stamp_release", lambda major, minor, patch, message="": ("release two", "1.0.0"))
    monkeypatch.setattr(panel, "_confirm_duplicate_version", lambda version: True)
    emitted = []
    panel.stamp_requested.connect(lambda message, version: emitted.append((message, version)))

    panel.stamp_button.click()

    assert emitted == [("release two", "1.0.0")]


def test_stamp_button_is_disabled_when_the_gametype_is_not_compiled(panel: GitPanel, tmp_path: Path) -> None:
    # PROMPT.md: "it also should not be possible to stamp a non compiled gametype".
    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)
    assert panel.stamp_button.isEnabled() is True

    panel.set_stamp_enabled(False)

    assert panel.stamp_button.isEnabled() is False

    panel.set_stamp_enabled(True)

    assert panel.stamp_button.isEnabled() is True


def test_new_branch_button_offers_a_new_branch_and_new_branch_from_dropdown(
    panel: GitPanel, tmp_path: Path
) -> None:
    # PROMPT.md: "please make new branch trigger a drop down also providing a New Branch from
    # option (if not use present)".
    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)

    menu = panel.new_branch_button.menu()

    assert [a.text() for a in menu.actions()] == ["New Branch", "New Branch From..."]


def test_new_branch_menu_action_emits_new_branch_requested_with_the_typed_name(
    panel: GitPanel, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)
    monkeypatch.setattr(panel, "_ask_text", lambda title, label: "feature")
    emitted = []
    panel.new_branch_requested.connect(emitted.append)

    _trigger_action(panel.new_branch_button.menu(), "New Branch")

    assert emitted == ["feature"]


def test_new_branch_from_picking_a_different_source_emits_new_branch_from_requested(
    panel: GitPanel, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.create_branch(folder, "feature")
    vcs.switch_branch(folder, vcs.DEFAULT_BRANCH)
    panel.set_project(folder)
    monkeypatch.setattr(
        "PyQt6.QtWidgets.QInputDialog.getItem", lambda *a, **k: ("feature", True)
    )
    monkeypatch.setattr(panel, "_ask_text", lambda title, label: "from-feature")
    emitted = []
    panel.new_branch_from_requested.connect(lambda name, source: emitted.append((name, source)))

    _trigger_action(panel.new_branch_button.menu(), "New Branch From...")

    assert emitted == [("from-feature", "feature")]


def test_new_branch_from_picking_the_current_branch_emits_plain_new_branch_requested(
    panel: GitPanel, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Picking whatever's already checked out as the "source" is just the plain "New Branch"
    # behavior -- no need to route it through the source-aware signal.
    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)
    monkeypatch.setattr(
        "PyQt6.QtWidgets.QInputDialog.getItem", lambda *a, **k: (vcs.DEFAULT_BRANCH, True)
    )
    monkeypatch.setattr(panel, "_ask_text", lambda title, label: "feature")
    plain_emitted = []
    from_emitted = []
    panel.new_branch_requested.connect(plain_emitted.append)
    panel.new_branch_from_requested.connect(lambda name, source: from_emitted.append((name, source)))

    _trigger_action(panel.new_branch_button.menu(), "New Branch From...")

    assert plain_emitted == ["feature"]
    assert from_emitted == []


def test_new_branch_from_cancelled_source_picker_emits_nothing(
    panel: GitPanel, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)
    monkeypatch.setattr("PyQt6.QtWidgets.QInputDialog.getItem", lambda *a, **k: ("", False))
    emitted = []
    panel.new_branch_from_requested.connect(lambda name, source: emitted.append((name, source)))

    _trigger_action(panel.new_branch_button.menu(), "New Branch From...")

    assert emitted == []


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


def test_merge_branch_button_is_enabled_with_history(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)

    panel.set_project(folder)

    assert panel.merge_branch_button.isEnabled() is True


def test_merge_branch_menu_offers_every_branch_other_than_the_current_one(
    panel: GitPanel, tmp_path: Path
) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.create_branch(folder, "feature")
    vcs.switch_branch(folder, vcs.DEFAULT_BRANCH)
    panel.set_project(folder)
    emitted = []
    panel.merge_branch_requested.connect(emitted.append)

    menu = panel._build_merge_branch_menu()
    _trigger_action(menu, "feature")

    assert emitted == ["feature"]


def test_merge_branch_menu_is_none_with_only_a_single_branch(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)

    assert panel._build_merge_branch_menu() is None


def test_compare_combos_default_to_listing_branches(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.stamp(folder, "v1")
    vcs.create_branch(folder, "feature")

    panel.set_project(folder)

    assert panel.compare_a_type_combo.currentText() == "Branch"
    labels = {panel.compare_a_combo.itemText(i) for i in range(panel.compare_a_combo.count())}
    assert labels == {vcs.DEFAULT_BRANCH, "feature"}


def test_compare_combo_switches_to_listing_stamps_when_its_type_combo_changes(
    panel: GitPanel, tmp_path: Path
) -> None:
    # PROMPT.md: "where we have compare we need to add 2 drop downs above the left and right
    # comparison to allow the user to select between branch and stamp, which then populates the
    # list below it (to stop the dropdown being too long for containing all branches and stamps)".
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.stamp(folder, "v1")
    vcs.create_branch(folder, "feature")
    panel.set_project(folder)

    panel.compare_a_type_combo.setCurrentText("Stamp")

    labels = {panel.compare_a_combo.itemText(i) for i in range(panel.compare_a_combo.count())}
    assert labels == {"Stamp: v1"}
    # The other side's own type/combo is untouched by changing this one.
    assert panel.compare_b_type_combo.currentText() == "Branch"
    b_labels = {panel.compare_b_combo.itemText(i) for i in range(panel.compare_b_combo.count())}
    assert b_labels == {vcs.DEFAULT_BRANCH, "feature"}


def test_compare_a_combo_carries_the_stamps_sha_as_its_own_item_data(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    sha = vcs.stamp(folder, "v1")
    panel.set_project(folder)

    panel.compare_a_type_combo.setCurrentText("Stamp")

    assert panel.compare_a_combo.itemData(0) == sha


def test_compare_type_combos_reset_to_branch_on_refresh(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.stamp(folder, "v1")
    panel.set_project(folder)
    panel.compare_a_type_combo.setCurrentText("Stamp")

    panel.refresh()

    assert panel.compare_a_type_combo.currentText() == "Branch"


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
    assert panel.changes_section._toggle.text() == "Changes (0)"
    assert panel.changes_list.count() == 0
    assert panel.commit_button.isEnabled() is False


def test_an_edited_file_shows_up_as_an_uncommitted_change(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "Notes.txt").write_text("edited\n", encoding="utf-8")

    panel.set_project(folder)

    assert panel.uncommitted_count == 1
    assert panel.changes_section._toggle.text() == "Changes (1)"
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


def test_commit_button_stays_disabled_with_no_message_even_if_something_is_staged(
    panel: GitPanel, tmp_path: Path
) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "Notes.txt").write_text("edited\n", encoding="utf-8")
    vcs.stage_all(folder)
    panel.set_project(folder)

    assert panel.commit_button.isEnabled() is False

    panel.commit_message_edit.setText("fix notes")

    assert panel.commit_button.isEnabled() is True


def test_commit_button_stays_disabled_with_a_message_when_nothing_is_staged(
    panel: GitPanel, tmp_path: Path
) -> None:
    # PROMPT.md, a later pass: "changes should be staged, and then committed" -- an uncommitted but
    # unstaged change alone doesn't enable Commit, even with a message typed.
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "Notes.txt").write_text("edited\n", encoding="utf-8")
    panel.set_project(folder)

    panel.commit_message_edit.setText("fix notes")

    assert panel.commit_button.isEnabled() is False


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
    vcs.stage_all(folder)
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
    vcs.stage_all(folder)
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


# -- staging (PROMPT.md, a later pass: "please then make it so that changes should be staged, and
# then committed"; "in the changes it should be possible to right click the file and then see: Open
# changes, open files, open file (HEAD), discard changes, stage changes (or unstage changes), reveal
# in file explorer"; "we also need buttons/functionality to: ... stage all/unstage all") ----------


def test_an_unstaged_change_shows_up_in_the_changes_list_only(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "Notes.txt").write_text("edited\n", encoding="utf-8")

    panel.set_project(folder)

    assert panel.staged_list.count() == 0
    assert panel.changes_list.count() == 1
    assert panel.changes_list.item(0).text() == "M  Notes.txt"
    assert panel.staged_label.text() == "Staged Changes (0)"
    assert panel.changes_label.text() == "Changes (1)"


def test_a_staged_change_shows_up_in_the_staged_list_only(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "Notes.txt").write_text("edited\n", encoding="utf-8")
    vcs.stage(folder, ["Notes.txt"])

    panel.set_project(folder)

    assert panel.changes_list.count() == 0
    assert panel.staged_list.count() == 1
    assert panel.staged_list.item(0).text() == "M  Notes.txt"
    assert panel.staged_label.text() == "Staged Changes (1)"
    assert panel.changes_label.text() == "Changes (0)"


def test_a_file_edited_again_after_staging_appears_in_both_lists(panel: GitPanel, tmp_path: Path) -> None:
    # PROMPT.md: "if there are further changes to a file with[which was] staged those changes -
    # that file should still appear in changes and staged changes should not update. when a change
    # is staged is essentially snapshotted".
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "Notes.txt").write_text("staged content\n", encoding="utf-8")
    vcs.stage(folder, ["Notes.txt"])
    (folder / "Notes.txt").write_text("further edit\n", encoding="utf-8")

    panel.set_project(folder)

    assert panel.staged_list.count() == 1
    assert panel.staged_list.item(0).text() == "M  Notes.txt"
    assert panel.changes_list.count() == 1
    assert panel.changes_list.item(0).text() == "M  Notes.txt"
    assert panel.staged_label.text() == "Staged Changes (1)"
    assert panel.changes_label.text() == "Changes (1)"


def test_stage_all_button_emits_stage_requested_with_every_unstaged_path(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "Notes.txt").write_text("edited\n", encoding="utf-8")
    (folder / "new_file.txt").write_text("new\n", encoding="utf-8")
    panel.set_project(folder)
    emitted = []
    panel.stage_requested.connect(emitted.append)

    panel.stage_all_button.click()

    assert sorted(emitted[0]) == ["Notes.txt", "new_file.txt"]


def test_stage_all_button_does_nothing_when_theres_nothing_unstaged(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)
    emitted = []
    panel.stage_requested.connect(emitted.append)

    panel.stage_all_button.click()

    assert emitted == []


def test_unstage_all_button_emits_unstage_requested_with_every_staged_path(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "Notes.txt").write_text("edited\n", encoding="utf-8")
    vcs.stage_all(folder)
    panel.set_project(folder)
    emitted = []
    panel.unstage_requested.connect(emitted.append)

    panel.unstage_all_button.click()

    assert emitted == [["Notes.txt"]]


def test_context_menu_open_changes_emits_diff_file_requested(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "Notes.txt").write_text("edited\n", encoding="utf-8")
    panel.set_project(folder)
    emitted = []
    panel.diff_file_requested.connect(emitted.append)

    menu = panel._build_change_context_menu(panel.changes_list, panel.changes_list.item(0))
    _trigger_action(menu, "Open Changes")

    assert emitted == ["Notes.txt"]


def test_context_menu_open_file_emits_open_file_requested(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "Notes.txt").write_text("edited\n", encoding="utf-8")
    panel.set_project(folder)
    emitted = []
    panel.open_file_requested.connect(emitted.append)

    menu = panel._build_change_context_menu(panel.changes_list, panel.changes_list.item(0))
    _trigger_action(menu, "Open File")

    assert emitted == ["Notes.txt"]


def test_context_menu_open_file_head_emits_open_file_head_requested(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "Notes.txt").write_text("edited\n", encoding="utf-8")
    panel.set_project(folder)
    emitted = []
    panel.open_file_head_requested.connect(emitted.append)

    menu = panel._build_change_context_menu(panel.changes_list, panel.changes_list.item(0))
    _trigger_action(menu, "Open File (HEAD)")

    assert emitted == ["Notes.txt"]


def test_context_menu_discard_emits_discard_requested(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "Notes.txt").write_text("edited\n", encoding="utf-8")
    panel.set_project(folder)
    emitted = []
    panel.discard_requested.connect(emitted.append)

    menu = panel._build_change_context_menu(panel.changes_list, panel.changes_list.item(0))
    _trigger_action(menu, "Discard Changes")

    assert emitted == ["Notes.txt"]


def test_context_menu_reveal_emits_reveal_requested(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "Notes.txt").write_text("edited\n", encoding="utf-8")
    panel.set_project(folder)
    emitted = []
    panel.reveal_requested.connect(emitted.append)

    menu = panel._build_change_context_menu(panel.changes_list, panel.changes_list.item(0))
    _trigger_action(menu, "Reveal in File Explorer")

    assert emitted == ["Notes.txt"]


def test_context_menu_on_an_unstaged_item_offers_stage_not_unstage(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "Notes.txt").write_text("edited\n", encoding="utf-8")
    panel.set_project(folder)
    emitted = []
    panel.stage_requested.connect(emitted.append)

    menu = panel._build_change_context_menu(panel.changes_list, panel.changes_list.item(0))
    labels = [a.text() for a in menu.actions() if a.text()]
    assert "Stage Changes" in labels
    assert "Unstage Changes" not in labels
    _trigger_action(menu, "Stage Changes")

    assert emitted == [["Notes.txt"]]


def test_context_menu_on_a_staged_item_offers_unstage_not_stage(panel: GitPanel, tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "Notes.txt").write_text("edited\n", encoding="utf-8")
    vcs.stage_all(folder)
    panel.set_project(folder)
    emitted = []
    panel.unstage_requested.connect(emitted.append)

    menu = panel._build_change_context_menu(panel.staged_list, panel.staged_list.item(0))
    labels = [a.text() for a in menu.actions() if a.text()]
    assert "Unstage Changes" in labels
    assert "Stage Changes" not in labels
    _trigger_action(menu, "Unstage Changes")

    assert emitted == [["Notes.txt"]]


# -- History "Files Changed" (PROMPT.md, a later pass: "please make it so that when clicking in
# history on commits - it extends to show a list of files changed (which can then be clicked on to
# view (please note this should be a single (not split) view, see sample.png for styling)) - and
# right click should have the option to open file") -------------------------------------------


def test_selecting_a_commit_emits_commit_selected_and_shows_the_files_list(
    panel: GitPanel, tmp_path: Path
) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)
    emitted = []
    panel.commit_selected.connect(emitted.append)
    assert panel.commit_files_list.isVisible() is False

    panel.graph.select_row(0)

    assert len(emitted) == 1
    assert panel.commit_files_list.isVisible() is True
    assert panel.commit_files_label.isVisible() is True


def test_deselecting_hides_the_files_list(panel: GitPanel, tmp_path: Path) -> None:
    from in_reach.app.vcs import FileDiff

    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)
    panel.graph.select_row(0)
    panel.set_commit_files(panel.graph.selected_sha(), [FileDiff(path="Notes.txt", change_type="added", diff_text="")])

    panel._on_graph_selection_changed("")

    assert panel.commit_files_list.isVisible() is False


def test_set_commit_files_populates_the_list(panel: GitPanel, tmp_path: Path) -> None:
    from in_reach.app.vcs import FileDiff

    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)
    panel.graph.select_row(0)
    sha = panel.graph.selected_sha()

    panel.set_commit_files(sha, [FileDiff(path="Notes.txt", change_type="added", diff_text="")])

    assert panel.commit_files_list.count() == 1
    assert panel.commit_files_list.item(0).text() == "+  Notes.txt"
    assert panel.commit_files_label.text() == "Files Changed (1)"


def test_history_splitter_is_hidden_with_no_commit_selected(panel: GitPanel, tmp_path: Path) -> None:
    # PROMPT.md: "please also add a menu line divider under the restore button in vcs allowing the
    # menu to be dragged vertically up to reveal more of the files changed" -- no divider to drag,
    # and no space wasted on an empty pane, before any commit is selected.
    folder = _project(tmp_path)
    vcs.init(folder)

    panel.set_project(folder)

    assert panel._files_pane.isVisible() is False


def test_history_splitter_shows_the_files_pane_once_a_commit_is_selected(
    panel: GitPanel, tmp_path: Path
) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)
    panel.show()

    panel.graph.select_row(0)

    assert panel._files_pane.isVisible() is True
    assert panel._history_splitter.count() == 2


def test_dragging_the_history_splitter_up_grows_the_files_changed_list(
    panel: GitPanel, tmp_path: Path
) -> None:
    from in_reach.app.vcs import FileDiff

    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)
    panel.resize(400, 500)
    panel.show()
    panel.graph.select_row(0)
    sha = panel.graph.selected_sha()
    panel.set_commit_files(sha, [FileDiff(path="Notes.txt", change_type="added", diff_text="")])
    QApplication.processEvents()
    before = panel.commit_files_list.height()
    graph_size, files_size = panel._history_splitter.sizes()

    # Drag the handle up -- shrink the graph pane, grow the files pane.
    panel._history_splitter.moveSplitter(max(graph_size - 100, 0), 1)
    QApplication.processEvents()

    assert panel.commit_files_list.height() > before


def test_set_commit_files_ignores_a_stale_fetch_for_a_no_longer_selected_commit(
    panel: GitPanel, tmp_path: Path
) -> None:
    from in_reach.app.vcs import FileDiff

    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.stamp(folder, "v1")
    panel.set_project(folder)
    panel.graph.select_row(0)  # selects whatever is now the newest (the stamp)

    panel.set_commit_files("some-other-stale-sha", [FileDiff(path="Notes.txt", change_type="added", diff_text="")])

    assert panel.commit_files_list.count() == 0


def test_clicking_a_commit_file_emits_commit_diff_requested(panel: GitPanel, tmp_path: Path) -> None:
    from in_reach.app.vcs import FileDiff

    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)
    panel.graph.select_row(0)
    sha = panel.graph.selected_sha()
    panel.set_commit_files(sha, [FileDiff(path="Notes.txt", change_type="added", diff_text="")])
    emitted = []
    panel.commit_diff_requested.connect(lambda s, p: emitted.append((s, p)))

    panel.commit_files_list.itemClicked.emit(panel.commit_files_list.item(0))

    assert emitted == [(sha, "Notes.txt")]


def test_commit_file_context_menu_view_diff_emits_commit_diff_requested(panel: GitPanel, tmp_path: Path) -> None:
    from in_reach.app.vcs import FileDiff

    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)
    panel.graph.select_row(0)
    sha = panel.graph.selected_sha()
    panel.set_commit_files(sha, [FileDiff(path="Notes.txt", change_type="added", diff_text="")])
    emitted = []
    panel.commit_diff_requested.connect(lambda s, p: emitted.append((s, p)))

    menu = panel._build_commit_file_context_menu(panel.commit_files_list.item(0))
    _trigger_action(menu, "View Diff")

    assert emitted == [(sha, "Notes.txt")]


def test_commit_file_context_menu_open_file_emits_commit_open_file_requested(
    panel: GitPanel, tmp_path: Path
) -> None:
    from in_reach.app.vcs import FileDiff

    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)
    panel.graph.select_row(0)
    sha = panel.graph.selected_sha()
    panel.set_commit_files(sha, [FileDiff(path="Notes.txt", change_type="added", diff_text="")])
    emitted = []
    panel.commit_open_file_requested.connect(lambda s, p: emitted.append((s, p)))

    menu = panel._build_commit_file_context_menu(panel.commit_files_list.item(0))
    _trigger_action(menu, "Open File")

    assert emitted == [(sha, "Notes.txt")]


def test_history_graph_widens_to_fill_a_wider_sidebar(panel: GitPanel, tmp_path: Path) -> None:
    # PROMPT.md: "history text is not always expanding with side panel" -- the graph used to stay
    # pinned at its own fixed sizeHint() width regardless of how wide the sidebar actually was.
    folder = _project(tmp_path)
    vcs.init(folder)
    panel.set_project(folder)
    from PyQt6.QtWidgets import QApplication

    assert panel._graph_scroll.widgetResizable() is True
    narrow_width = panel.graph.width()

    panel.resize(900, panel.height())
    QApplication.processEvents()

    assert panel.graph.width() > narrow_width
    assert panel.graph.width() >= panel._graph_scroll.viewport().width()
