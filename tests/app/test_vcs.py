from pathlib import Path

import pytest

from in_reach.app import vcs


def _project(tmp_path: Path) -> Path:
    folder = tmp_path / "abcd1234"
    (folder / "settings").mkdir(parents=True)
    (folder / "settings" / "settings.json").write_text('{"a": 1}', encoding="utf-8")
    (folder / "notes.md").write_text("hi\n", encoding="utf-8")
    return folder


def test_is_initialized_is_false_before_init(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    assert vcs.is_initialized(folder) is False


def test_init_creates_history_and_a_first_snapshot(tmp_path: Path) -> None:
    folder = _project(tmp_path)

    vcs.init(folder)

    assert vcs.is_initialized(folder) is True
    assert vcs.current_branch(folder) == vcs.DEFAULT_BRANCH
    assert len(vcs.history(folder)) == 1


def test_init_is_a_no_op_if_already_initialized(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "settings" / "settings.json").write_text('{"a": 2}', encoding="utf-8")

    vcs.init(folder)  # should not re-snapshot / wipe history

    assert len(vcs.history(folder)) == 1


def test_init_with_a_stamp_message_stamps_the_first_snapshot(tmp_path: Path) -> None:
    folder = _project(tmp_path)

    vcs.init(folder, stamp_message="gametype init")

    (snapshot,) = vcs.history(folder)
    assert snapshot.is_stamp is True
    assert snapshot.stamp_message == "gametype init"


def test_init_with_a_stamp_message_defaults_to_version_0_0_0(tmp_path: Path) -> None:
    # PROMPT.md: "the init gametype should be get a version number of 0.0.0".
    folder = _project(tmp_path)

    vcs.init(folder, stamp_message="gametype init")

    (snapshot,) = vcs.history(folder)
    assert snapshot.version == "0.0.0"
    assert snapshot.version == vcs.INITIAL_VERSION


def test_init_with_a_stamp_message_and_explicit_none_version_has_no_version(tmp_path: Path) -> None:
    folder = _project(tmp_path)

    vcs.init(folder, stamp_message="gametype init", version=None)

    (snapshot,) = vcs.history(folder)
    assert snapshot.is_stamp is True
    assert snapshot.version is None


def test_stamp_with_a_version_records_it_on_the_snapshot(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)

    vcs.stamp(folder, "First release", version="1.2.3")

    snapshot = vcs.history(folder)[0]
    assert snapshot.version == "1.2.3"
    assert snapshot.stamp_message == "First release"


def test_stamp_without_a_version_leaves_it_none(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)

    vcs.stamp(folder, "First release")

    snapshot = vcs.history(folder)[0]
    assert snapshot.version is None
    assert snapshot.stamp_message == "First release"


def test_last_stamp_version_returns_the_most_recent_versioned_stamp(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder, stamp_message="gametype init")  # v0.0.0
    vcs.stamp(folder, "second", version="0.1.0")
    vcs.stamp(folder, "third", version="1.0.0")

    assert vcs.last_stamp_version(folder) == "1.0.0"


def test_last_stamp_version_is_none_with_no_versioned_stamp(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)  # plain "Initial commit" -- no stamp at all

    assert vcs.last_stamp_version(folder) is None


def test_version_already_stamped_true_for_a_used_version(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.stamp(folder, "First release", version="1.0.0")

    assert vcs.version_already_stamped(folder, "1.0.0") is True
    assert vcs.version_already_stamped(folder, "2.0.0") is False


def test_version_already_stamped_checks_every_branch(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.create_branch(folder, "feature")
    vcs.stamp(folder, "feature release", version="1.0.0")
    vcs.switch_branch(folder, vcs.DEFAULT_BRANCH)

    assert vcs.version_already_stamped(folder, "1.0.0") is True


def test_commit_raises_when_nothing_changed(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)

    with pytest.raises(ValueError):
        vcs.commit(folder, "nothing to commit")

    assert len(vcs.history(folder)) == 1


def test_commit_snapshots_a_real_edit(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "notes.md").write_text("hi\nmore\n", encoding="utf-8")
    vcs.stage_all(folder)

    result = vcs.commit(folder, "edited notes")

    assert result is not None
    assert len(vcs.history(folder)) == 2
    latest = vcs.history(folder)[0]
    assert latest.is_stamp is False
    assert latest.message == "edited notes"


def test_commit_requires_a_message(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "notes.md").write_text("hi\nmore\n", encoding="utf-8")

    with pytest.raises(ValueError):
        vcs.commit(folder, "   ")


def test_commit_before_init_raises(tmp_path: Path) -> None:
    folder = _project(tmp_path)

    with pytest.raises(ValueError):
        vcs.commit(folder, "a message")


# -- uncommitted_changes (PROMPT.md: "we want to add committed changes and uncommitted changes[;]
# when there are uncommitted changes in the repo there should be a notification icon with the
# number of uncommitted changes") -------------------------------------------------------------


def test_uncommitted_changes_is_empty_for_a_clean_project(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)

    assert vcs.uncommitted_changes(folder) == []


def test_uncommitted_changes_reports_a_modified_file(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "notes.md").write_text("hi\nmore\n", encoding="utf-8")

    changes = vcs.uncommitted_changes(folder)

    assert len(changes) == 1
    assert changes[0].path == "notes.md"
    assert changes[0].change_type == "modified"


def test_uncommitted_changes_reports_an_added_and_a_removed_file(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "notes.md").unlink()
    (folder / "new_file.txt").write_text("new\n", encoding="utf-8")

    changes = {c.path: c.change_type for c in vcs.uncommitted_changes(folder)}

    assert changes == {"notes.md": "removed", "new_file.txt": "added"}


def test_uncommitted_changes_ignores_generated_build_output(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    build_dir = folder / "build"
    build_dir.mkdir()
    (build_dir / "settings.autogenerated.json").write_text("{}", encoding="utf-8")

    assert vcs.uncommitted_changes(folder) == []


def test_uncommitted_changes_is_empty_again_right_after_committing(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "notes.md").write_text("hi\nmore\n", encoding="utf-8")
    assert vcs.uncommitted_changes(folder) != []
    vcs.stage_all(folder)

    vcs.commit(folder, "edited notes")

    assert vcs.uncommitted_changes(folder) == []


def test_uncommitted_changes_before_init_is_empty(tmp_path: Path) -> None:
    folder = _project(tmp_path)

    assert vcs.uncommitted_changes(folder) == []


# -- staging (PROMPT.md, a later pass: "please then make it so that changes should be staged, and
# then committed") -------------------------------------------------------------------------------


def test_a_freshly_edited_file_is_not_staged_by_default(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "notes.md").write_text("edited\n", encoding="utf-8")

    changes = vcs.uncommitted_changes(folder)

    assert changes[0].path == "notes.md"
    assert changes[0].staged is False


def test_stage_marks_a_file_as_staged(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "notes.md").write_text("edited\n", encoding="utf-8")

    vcs.stage(folder, ["notes.md"])

    assert vcs.staged_paths(folder) == {"notes.md"}
    assert vcs.uncommitted_changes(folder)[0].staged is True


def test_unstage_removes_a_file_from_staging(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "notes.md").write_text("edited\n", encoding="utf-8")
    vcs.stage(folder, ["notes.md"])

    vcs.unstage(folder, ["notes.md"])

    assert vcs.staged_paths(folder) == set()
    assert vcs.uncommitted_changes(folder)[0].staged is False


def test_stage_all_stages_every_uncommitted_path(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "notes.md").write_text("edited\n", encoding="utf-8")
    (folder / "new_file.txt").write_text("new\n", encoding="utf-8")

    vcs.stage_all(folder)

    assert vcs.staged_paths(folder) == {"notes.md", "new_file.txt"}


def test_commit_only_snapshots_staged_files(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "notes.md").write_text("staged edit\n", encoding="utf-8")
    (folder / "settings" / "settings.json").write_text('{"a": 2}', encoding="utf-8")
    vcs.stage(folder, ["notes.md"])

    vcs.commit(folder, "stage only notes.md")

    # notes.md made it into the commit -- settings.json's own unstaged edit did not.
    assert (folder / "notes.md").read_text(encoding="utf-8") == "staged edit\n"
    remaining = {c.path for c in vcs.uncommitted_changes(folder)}
    assert remaining == {"settings/settings.json"}
    committed_notes = vcs.uncommitted_file_diff(folder, "settings/settings.json")[0]
    assert committed_notes == '{"a": 1}'  # settings.json's own HEAD content is unchanged


def test_commit_clears_only_the_staged_paths_it_actually_committed(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "notes.md").write_text("staged edit\n", encoding="utf-8")
    (folder / "settings" / "settings.json").write_text('{"a": 2}', encoding="utf-8")
    vcs.stage(folder, ["notes.md", "settings/settings.json"])

    vcs.commit(folder, "stage both")

    assert vcs.staged_paths(folder) == set()
    assert vcs.uncommitted_changes(folder) == []


def test_commit_raises_when_nothing_is_staged_even_if_something_changed(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "notes.md").write_text("edited\n", encoding="utf-8")

    with pytest.raises(ValueError):
        vcs.commit(folder, "nothing staged")


def test_commit_of_a_staged_deletion_removes_the_file_from_the_commit(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "notes.md").unlink()
    vcs.stage(folder, ["notes.md"])

    vcs.commit(folder, "remove notes")

    old, new = vcs.uncommitted_file_diff(folder, "notes.md")
    assert new is None
    # Nothing left uncommitted -- the deletion is now what HEAD itself has too.
    assert vcs.uncommitted_changes(folder) == []


def test_commit_uses_the_snapshot_taken_at_stage_time_not_current_disk_content(tmp_path: Path) -> None:
    # PROMPT.md: "when a change is staged is essentially snapshotted" -- staging a file and then
    # hand-editing it again (even back to matching HEAD) never changes what actually gets committed;
    # commit() always uses the content stage() captured, same as real git's own index.
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "notes.md").write_text("edited\n", encoding="utf-8")
    vcs.stage(folder, ["notes.md"])
    (folder / "notes.md").write_text("hi\n", encoding="utf-8")  # hand-reverted back to HEAD's own content

    vcs.commit(folder, "commit the snapshot")

    # The commit carries the *snapshot* ("edited"), not disk's current ("hi") -- so disk now reads
    # as uncommitted (differs from the new HEAD, which has "edited").
    changes = vcs.uncommitted_changes(folder)
    assert len(changes) == 1
    assert changes[0].path == "notes.md"
    assert changes[0].staged is False
    old, new = vcs.uncommitted_file_diff(folder, "notes.md")
    assert old == "edited\n"  # HEAD now has the committed snapshot
    assert new == "hi\n"  # disk still has the hand-reverted content


def test_further_edits_after_staging_show_up_in_changes_without_touching_the_staged_entry(
    tmp_path: Path,
) -> None:
    # PROMPT.md: "if there are further changes to a file with[which was] staged those changes -
    # that file should still appear in changes and staged changes should not update."
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "notes.md").write_text("staged content\n", encoding="utf-8")
    vcs.stage(folder, ["notes.md"])

    (folder / "notes.md").write_text("further edit\n", encoding="utf-8")

    changes = {(c.path, c.staged) for c in vcs.uncommitted_changes(folder)}
    assert changes == {("notes.md", True), ("notes.md", False)}


def test_restaging_an_already_staged_path_overwrites_its_snapshot(tmp_path: Path) -> None:
    # PROMPT.md: "if a file has staged changes, then gets new staged changes, the new staged
    # changes should overwrite as with normal git."
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "notes.md").write_text("first staged content\n", encoding="utf-8")
    vcs.stage(folder, ["notes.md"])
    (folder / "notes.md").write_text("second staged content\n", encoding="utf-8")

    vcs.stage(folder, ["notes.md"])  # re-stage -- overwrites the first snapshot

    changes = vcs.uncommitted_changes(folder)
    assert len(changes) == 1
    assert changes[0].staged is True

    vcs.commit(folder, "commit the re-staged content")

    assert (folder / "notes.md").read_text(encoding="utf-8") == "second staged content\n"
    assert vcs.uncommitted_changes(folder) == []


def test_discard_uncommitted_change_reverts_a_modified_file(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "notes.md").write_text("edited\n", encoding="utf-8")

    vcs.discard_uncommitted_change(folder, "notes.md")

    assert (folder / "notes.md").read_text(encoding="utf-8") == "hi\n"
    assert vcs.uncommitted_changes(folder) == []


def test_discard_uncommitted_change_deletes_a_newly_added_file(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "new_file.txt").write_text("new\n", encoding="utf-8")

    vcs.discard_uncommitted_change(folder, "new_file.txt")

    assert not (folder / "new_file.txt").exists()


def test_discard_uncommitted_change_also_unstages_the_path(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "notes.md").write_text("edited\n", encoding="utf-8")
    vcs.stage(folder, ["notes.md"])

    vcs.discard_uncommitted_change(folder, "notes.md")

    assert vcs.staged_paths(folder) == set()


def test_discard_uncommitted_change_before_init_raises(tmp_path: Path) -> None:
    folder = _project(tmp_path)

    with pytest.raises(ValueError):
        vcs.discard_uncommitted_change(folder, "notes.md")


def test_switch_branch_clears_the_staging_area(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.create_branch(folder, "feature")
    vcs.switch_branch(folder, vcs.DEFAULT_BRANCH)
    (folder / "notes.md").write_text("edited\n", encoding="utf-8")
    vcs.stage(folder, ["notes.md"])

    vcs.switch_branch(folder, "feature")

    assert vcs.staged_paths(folder) == set()


def test_restore_snapshot_clears_the_staging_area(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    first = vcs.stamp(folder, "v1")
    (folder / "notes.md").write_text("edited\n", encoding="utf-8")
    vcs.stage(folder, ["notes.md"])

    vcs.restore_snapshot(folder, first)

    assert vcs.staged_paths(folder) == set()


# -- uncommitted_file_diff (PROMPT.md: "when clicking on changes to a file (in the changes tab) a
# tab should appear showing the original on the left and highlighted changes on the right (like
# vscode git)") ----------------------------------------------------------------------------------


def test_uncommitted_file_diff_for_a_modified_file(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "notes.md").write_text("hi\nedited\n", encoding="utf-8")

    old, new = vcs.uncommitted_file_diff(folder, "notes.md")

    assert old == "hi\n"
    assert new == "hi\nedited\n"


def test_uncommitted_file_diff_for_a_newly_added_file(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "new_file.txt").write_text("brand new\n", encoding="utf-8")

    old, new = vcs.uncommitted_file_diff(folder, "new_file.txt")

    assert old is None
    assert new == "brand new\n"


def test_uncommitted_file_diff_for_a_removed_file(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "notes.md").unlink()

    old, new = vcs.uncommitted_file_diff(folder, "notes.md")

    assert old == "hi\n"
    assert new is None


def test_uncommitted_file_diff_normalizes_crlf_from_the_committed_blob(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    (folder / "notes.md").write_bytes(b"line1\r\nline2\r\n")
    vcs.init(folder)
    (folder / "notes.md").write_text("line1\nline2\nline3\n", encoding="utf-8")

    old, new = vcs.uncommitted_file_diff(folder, "notes.md")

    assert old == "line1\nline2\n"  # not "line1\r\nline2\r\n"
    assert new == "line1\nline2\nline3\n"


def test_uncommitted_file_diff_before_init_is_none_none(tmp_path: Path) -> None:
    folder = _project(tmp_path)

    assert vcs.uncommitted_file_diff(folder, "notes.md") == (None, None)


# -- ref_file_diff (PROMPT.md, a later pass: "please then add text colourings and line numbers in
# the compare window to make the text and changes clearer and more visually appealing") -----------


def test_ref_file_diff_between_two_branches(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.create_branch(folder, "feature")
    (folder / "notes.md").write_text("changed\n", encoding="utf-8")
    vcs.stage_all(folder)
    vcs.commit(folder, "feature change")
    vcs.switch_branch(folder, vcs.DEFAULT_BRANCH)

    old, new = vcs.ref_file_diff(folder, vcs.DEFAULT_BRANCH, "feature", "notes.md")

    assert old == "hi\n"
    assert new == "changed\n"


def test_ref_file_diff_between_two_stamps(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    first = vcs.stamp(folder, "v1")
    (folder / "notes.md").write_text("changed\n", encoding="utf-8")
    second = vcs.stamp(folder, "v2")

    old, new = vcs.ref_file_diff(folder, first, second, "notes.md")

    assert old == "hi\n"
    assert new == "changed\n"


def test_ref_file_diff_for_a_file_only_present_on_one_side(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.create_branch(folder, "feature")
    (folder / "new_file.txt").write_text("new\n", encoding="utf-8")
    vcs.stage_all(folder)
    vcs.commit(folder, "add new file")
    vcs.switch_branch(folder, vcs.DEFAULT_BRANCH)

    old, new = vcs.ref_file_diff(folder, vcs.DEFAULT_BRANCH, "feature", "new_file.txt")

    assert old is None
    assert new == "new\n"


def test_ref_file_diff_rejects_an_unknown_ref(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)

    with pytest.raises(ValueError):
        vcs.ref_file_diff(folder, vcs.DEFAULT_BRANCH, "does-not-exist", "notes.md")


def test_ref_file_diff_normalizes_crlf(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    (folder / "notes.md").write_bytes(b"line1\r\nline2\r\n")
    vcs.init(folder)
    first = vcs.stamp(folder, "v1")
    (folder / "notes.md").write_text("line1\nline2\nline3\n", encoding="utf-8")
    second = vcs.stamp(folder, "v2")

    old, new = vcs.ref_file_diff(folder, first, second, "notes.md")

    assert old == "line1\nline2\n"
    assert new == "line1\nline2\nline3\n"


def test_stamp_records_a_labelled_snapshot(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)

    sha = vcs.stamp(folder, "First release")

    assert isinstance(sha, str) and sha
    snapshot = vcs.history(folder)[0]
    assert snapshot.is_stamp is True
    assert snapshot.stamp_message == "First release"


def test_stamp_requires_a_message(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)

    with pytest.raises(ValueError):
        vcs.stamp(folder, "   ")


def test_stamp_before_init_raises(tmp_path: Path) -> None:
    folder = _project(tmp_path)

    with pytest.raises(ValueError):
        vcs.stamp(folder, "First release")


def test_last_stamp_finds_the_most_recent_stamp_only(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.stamp(folder, "v1")
    (folder / "notes.md").write_text("edit\n", encoding="utf-8")
    vcs.stage_all(folder)
    vcs.commit(folder, "test change")

    last = vcs.last_stamp(folder)

    assert last is not None
    assert last.stamp_message == "v1"


def test_last_stamp_is_none_when_never_stamped(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)

    assert vcs.last_stamp(folder) is None


def test_last_saved_at_reflects_the_most_recent_snapshot(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)

    assert vcs.last_saved_at(folder) is not None


# -- graph_history (PROMPT.md: "we also want to show a git graph of commits, branches and stamps
# instead in vscode style") ---------------------------------------------------------------------


def test_graph_history_is_empty_before_init(tmp_path: Path) -> None:
    folder = _project(tmp_path)

    assert vcs.graph_history(folder) == []


def test_graph_history_marks_the_tip_of_each_branch(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    root_sha = vcs.history(folder)[0].sha
    vcs.create_branch(folder, "feature")
    vcs.switch_branch(folder, vcs.DEFAULT_BRANCH)

    snapshots = vcs.graph_history(folder)

    (root,) = [s for s in snapshots if s.sha == root_sha]
    assert set(root.branches) == {vcs.DEFAULT_BRANCH, "feature"}


def test_graph_history_includes_commits_only_reachable_from_a_non_current_branch(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.create_branch(folder, "feature")
    (folder / "notes.md").write_text("feature-only change\n", encoding="utf-8")
    vcs.stage_all(folder)
    feature_sha = vcs.commit(folder, "feature change")
    vcs.switch_branch(folder, vcs.DEFAULT_BRANCH)

    snapshots = vcs.graph_history(folder)

    assert feature_sha in {s.sha for s in snapshots}


def test_graph_history_records_each_commits_parent(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    root_sha = vcs.history(folder)[0].sha
    (folder / "notes.md").write_text("edit\n", encoding="utf-8")
    vcs.stage_all(folder)
    second_sha = vcs.commit(folder, "edit notes")

    by_sha = {s.sha: s for s in vcs.graph_history(folder)}

    assert by_sha[second_sha].parents == [root_sha]
    assert by_sha[root_sha].parents == []


# -- commit_files_changed/commit_file_diff (PROMPT.md, a later pass: "please make it so that when
# clicking in history on commits - it extends to show a list of files changed (which can then be
# clicked on to view ...)") ------------------------------------------------------------------------


def test_commit_files_changed_for_the_root_commit_diffs_against_an_empty_tree(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    root_sha = vcs.history(folder)[0].sha

    changes = vcs.commit_files_changed(folder, root_sha)

    assert {c.path for c in changes} == {"notes.md", "settings/settings.json"}
    assert all(c.change_type == "added" for c in changes)


def test_commit_files_changed_for_a_later_commit_diffs_against_its_own_parent(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "notes.md").write_text("edited\n", encoding="utf-8")
    (folder / "new_file.txt").write_text("new\n", encoding="utf-8")
    vcs.stage_all(folder)
    second_sha = vcs.commit(folder, "second commit")

    changes = {c.path: c.change_type for c in vcs.commit_files_changed(folder, second_sha)}

    assert changes == {"notes.md": "modified", "new_file.txt": "added"}


def test_commit_files_changed_rejects_an_unknown_sha(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)

    with pytest.raises(ValueError):
        vcs.commit_files_changed(folder, "not-a-real-sha")


def test_commit_file_diff_for_a_later_commit(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    (folder / "notes.md").write_text("edited\n", encoding="utf-8")
    vcs.stage_all(folder)
    second_sha = vcs.commit(folder, "second commit")

    old, new = vcs.commit_file_diff(folder, second_sha, "notes.md")

    assert old == "hi\n"
    assert new == "edited\n"


def test_commit_file_diff_for_the_root_commit_has_no_old_text(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    root_sha = vcs.history(folder)[0].sha

    old, new = vcs.commit_file_diff(folder, root_sha, "notes.md")

    assert old is None
    assert new == "hi\n"


def test_commit_file_diff_rejects_an_unknown_sha(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)

    with pytest.raises(ValueError):
        vcs.commit_file_diff(folder, "not-a-real-sha", "notes.md")


def test_create_branch_switches_to_the_new_branch(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)

    vcs.create_branch(folder, "feature")

    assert vcs.current_branch(folder) == "feature"
    assert set(vcs.list_branches(folder)) == {vcs.DEFAULT_BRANCH, "feature"}


def test_create_branch_rejects_a_duplicate_name(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.create_branch(folder, "feature")
    vcs.switch_branch(folder, vcs.DEFAULT_BRANCH)

    with pytest.raises(ValueError):
        vcs.create_branch(folder, "feature")


def test_create_branch_rejects_an_empty_name(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)

    with pytest.raises(ValueError):
        vcs.create_branch(folder, "  ")


def test_create_branch_sanitizes_the_name(tmp_path: Path) -> None:
    # PROMPT.md: "please make sure branches are saved non-capitalised and with only - or _ and no
    # spaces or special chars".
    folder = _project(tmp_path)
    vcs.init(folder)

    created = vcs.create_branch(folder, "Fix Bug #42!")

    assert created == "fix-bug-42"
    assert vcs.current_branch(folder) == "fix-bug-42"


def test_create_branch_rejects_a_name_that_sanitizes_to_empty(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)

    with pytest.raises(ValueError):
        vcs.create_branch(folder, "!!!")


def test_sanitize_branch_name_lowercases_collapses_whitespace_and_drops_special_chars() -> None:
    assert vcs.sanitize_branch_name("  Fix Bug   #42! ") == "fix-bug-42"
    assert vcs.sanitize_branch_name("already-ok_123") == "already-ok_123"


def test_create_branch_with_a_source_branches_off_that_ref_instead_of_head(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.create_branch(folder, "feature")
    (folder / "notes.md").write_text("feature content\n", encoding="utf-8")
    vcs.stage_all(folder)
    vcs.commit(folder, "feature change")
    vcs.switch_branch(folder, vcs.DEFAULT_BRANCH)

    vcs.create_branch(folder, "from-feature", source="feature")

    assert vcs.current_branch(folder) == "from-feature"
    assert (folder / "notes.md").read_text(encoding="utf-8") == "feature content\n"


def test_create_branch_with_an_unknown_source_raises(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)

    with pytest.raises(ValueError):
        vcs.create_branch(folder, "feature", source="no-such-branch")


def test_switch_branch_restores_files_from_that_branchs_last_snapshot(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.create_branch(folder, "feature")
    (folder / "notes.md").write_text("feature branch content\n", encoding="utf-8")
    vcs.stage_all(folder)
    vcs.commit(folder, "test change")

    vcs.switch_branch(folder, vcs.DEFAULT_BRANCH)

    assert (folder / "notes.md").read_text(encoding="utf-8") == "hi\n"
    assert vcs.current_branch(folder) == vcs.DEFAULT_BRANCH


def test_switch_branch_removes_files_added_only_on_the_other_branch(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.create_branch(folder, "feature")
    (folder / "new_on_feature.txt").write_text("only here\n", encoding="utf-8")
    vcs.stage_all(folder)
    vcs.commit(folder, "test change")

    vcs.switch_branch(folder, vcs.DEFAULT_BRANCH)

    assert not (folder / "new_on_feature.txt").exists()


def test_switch_branch_never_touches_generated_build_output(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    build_dir = folder / "build"
    build_dir.mkdir()
    generated = build_dir / "settings.autogenerated.json"
    generated.write_text("{}", encoding="utf-8")
    vcs.create_branch(folder, "feature")

    vcs.switch_branch(folder, vcs.DEFAULT_BRANCH)

    assert generated.exists()


def test_switch_branch_rejects_an_unknown_branch(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)

    with pytest.raises(ValueError):
        vcs.switch_branch(folder, "does-not-exist")


# -- delete_branch ----------------------------------------------------------------------------


def test_delete_branch_removes_a_branch_not_currently_checked_out(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.create_branch(folder, "feature")
    vcs.switch_branch(folder, vcs.DEFAULT_BRANCH)

    vcs.delete_branch(folder, "feature")

    assert vcs.list_branches(folder) == [vcs.DEFAULT_BRANCH]


def test_delete_branch_refuses_the_current_branch(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.create_branch(folder, "feature")  # switches to it

    with pytest.raises(ValueError):
        vcs.delete_branch(folder, "feature")


def test_delete_branch_refuses_the_last_branch(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)

    with pytest.raises(ValueError):
        vcs.delete_branch(folder, vcs.DEFAULT_BRANCH)


def test_delete_branch_rejects_an_unknown_name(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)

    with pytest.raises(ValueError):
        vcs.delete_branch(folder, "does-not-exist")


# -- merge_branch ---------------------------------------------------------------------------------


def test_merge_branch_fast_forwards_when_current_branch_has_no_new_commits(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.create_branch(folder, "feature")
    (folder / "notes.md").write_text("from feature\n", encoding="utf-8")
    vcs.stage_all(folder)
    feature_sha = vcs.commit(folder, "feature change")
    vcs.switch_branch(folder, vcs.DEFAULT_BRANCH)

    result_sha = vcs.merge_branch(folder, "feature")

    assert result_sha == feature_sha
    assert (folder / "notes.md").read_text(encoding="utf-8") == "from feature\n"
    assert vcs.current_branch(folder) == vcs.DEFAULT_BRANCH


def test_merge_branch_creates_a_two_parent_commit_for_a_true_merge(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.create_branch(folder, "feature")
    (folder / "feature.txt").write_text("from feature\n", encoding="utf-8")
    vcs.stage_all(folder)
    feature_sha = vcs.commit(folder, "feature change")
    vcs.switch_branch(folder, vcs.DEFAULT_BRANCH)
    (folder / "notes.md").write_text("from main\n", encoding="utf-8")
    vcs.stage_all(folder)
    main_sha = vcs.commit(folder, "main change")

    result_sha = vcs.merge_branch(folder, "feature")

    snapshots = {s.sha: s for s in vcs.graph_history(folder)}
    assert sorted(snapshots[result_sha].parents) == sorted([main_sha, feature_sha])
    assert (folder / "notes.md").read_text(encoding="utf-8") == "from main\n"
    assert (folder / "feature.txt").read_text(encoding="utf-8") == "from feature\n"


def test_merge_branch_clears_the_staging_area(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.create_branch(folder, "feature")
    (folder / "feature.txt").write_text("from feature\n", encoding="utf-8")
    vcs.stage_all(folder)
    vcs.commit(folder, "feature change")
    vcs.switch_branch(folder, vcs.DEFAULT_BRANCH)
    (folder / "notes.md").write_text("from main\n", encoding="utf-8")
    vcs.stage_all(folder)
    vcs.commit(folder, "main change")

    vcs.merge_branch(folder, "feature")

    assert vcs.staged_paths(folder) == set()


def test_merge_branch_raises_on_a_real_conflict(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.create_branch(folder, "feature")
    (folder / "notes.md").write_text("from feature\n", encoding="utf-8")
    vcs.stage_all(folder)
    vcs.commit(folder, "feature change")
    vcs.switch_branch(folder, vcs.DEFAULT_BRANCH)
    (folder / "notes.md").write_text("from main\n", encoding="utf-8")
    vcs.stage_all(folder)
    vcs.commit(folder, "main change")

    with pytest.raises(vcs.MergeConflictError) as excinfo:
        vcs.merge_branch(folder, "feature")

    assert excinfo.value.paths == ["notes.md"]


def test_merge_branch_rejects_merging_the_current_branch_into_itself(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)

    with pytest.raises(ValueError):
        vcs.merge_branch(folder, vcs.DEFAULT_BRANCH)


def test_merge_branch_rejects_an_unknown_source_branch(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)

    with pytest.raises(ValueError):
        vcs.merge_branch(folder, "does-not-exist")


# -- diff ---------------------------------------------------------------------------------------


def test_diff_between_branches_reports_modified_added_and_matches_content(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.create_branch(folder, "feature")
    (folder / "notes.md").write_text("hi\nmore\n", encoding="utf-8")
    (folder / "new_file.txt").write_text("new\n", encoding="utf-8")
    vcs.stage_all(folder)
    vcs.commit(folder, "test change")
    vcs.switch_branch(folder, vcs.DEFAULT_BRANCH)

    diffs = vcs.diff(folder, vcs.DEFAULT_BRANCH, "feature")

    by_path = {d.path: d for d in diffs}
    assert set(by_path) == {"notes.md", "new_file.txt"}
    assert by_path["notes.md"].change_type == "modified"
    assert "+more" in by_path["notes.md"].diff_text
    assert by_path["new_file.txt"].change_type == "added"


def test_diff_reports_a_removed_file(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.create_branch(folder, "feature")
    (folder / "notes.md").unlink()
    vcs.stage_all(folder)
    vcs.commit(folder, "test change")

    diffs = vcs.diff(folder, vcs.DEFAULT_BRANCH, "feature")

    assert len(diffs) == 1
    assert diffs[0].path == "notes.md"
    assert diffs[0].change_type == "removed"


def test_diff_is_empty_for_identical_snapshots(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.create_branch(folder, "feature")

    assert vcs.diff(folder, vcs.DEFAULT_BRANCH, "feature") == []


def test_diff_between_two_stamps(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    first = vcs.stamp(folder, "v1")
    (folder / "notes.md").write_text("changed\n", encoding="utf-8")
    second = vcs.stamp(folder, "v2")

    diffs = vcs.diff(folder, first, second)

    assert [d.path for d in diffs] == ["notes.md"]
    assert diffs[0].change_type == "modified"


def test_diff_treats_undecodable_bytes_as_binary(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    vcs.create_branch(folder, "feature")
    (folder / "image.bin").write_bytes(b"\xff\xfe\x00\x01")
    vcs.stage_all(folder)
    vcs.commit(folder, "test change")

    diffs = vcs.diff(folder, vcs.DEFAULT_BRANCH, "feature")

    assert diffs[0].diff_text == "Binary file added."


def test_diff_rejects_an_unknown_ref(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)

    with pytest.raises(ValueError):
        vcs.diff(folder, vcs.DEFAULT_BRANCH, "does-not-exist")


# -- restore_snapshot -----------------------------------------------------------------------------


def test_restore_snapshot_brings_back_an_old_stamps_content(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    first = vcs.stamp(folder, "v1")
    (folder / "notes.md").write_text("changed\n", encoding="utf-8")
    vcs.stamp(folder, "v2")

    vcs.restore_snapshot(folder, first)

    assert (folder / "notes.md").read_text(encoding="utf-8") == "hi\n"


def test_restore_snapshot_records_a_new_plain_commit_rather_than_rewriting_history(
    tmp_path: Path,
) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    first = vcs.stamp(folder, "v1")
    (folder / "notes.md").write_text("changed\n", encoding="utf-8")
    second = vcs.stamp(folder, "v2")
    before = len(vcs.history(folder))

    vcs.restore_snapshot(folder, first)

    after = vcs.history(folder)
    assert len(after) == before + 1
    assert after[0].is_stamp is False  # the restore itself is a plain, non-stamped commit
    assert after[0].message == f"Restored {first[:8]}"
    # both prior stamps are still there, untouched -- history only ever gained an entry.
    assert {s.sha for s in after if s.is_stamp} == {first, second}


def test_restore_snapshot_is_a_no_op_when_it_already_matches_head(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)
    sha = vcs.stamp(folder, "v1")
    before = len(vcs.history(folder))

    vcs.restore_snapshot(folder, sha)

    assert len(vcs.history(folder)) == before


def test_restore_snapshot_rejects_an_unknown_sha(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    vcs.init(folder)

    with pytest.raises(ValueError):
        vcs.restore_snapshot(folder, "not-a-real-sha")


def test_the_notepad_is_never_versioned_or_restored(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    (folder / "Notes.txt").write_text("private\n", encoding="utf-8")
    vcs.init(folder)
    first = vcs.history(folder)[-1].sha
    (folder / "Notes.txt").write_text("changed\n", encoding="utf-8")

    assert vcs.uncommitted_changes(folder) == []
    vcs.restore_snapshot(folder, first)
    assert (folder / "Notes.txt").read_text(encoding="utf-8") == "changed\n"


def test_each_snapshot_knows_the_env_it_was_built_with(tmp_path: Path) -> None:
    folder = _project(tmp_path)
    (folder / "script" / "env").mkdir(parents=True)
    (folder / "script" / "env" / "active_env.txt").write_text("development\n", encoding="utf-8")
    vcs.init(folder)
    (folder / "script" / "env" / "active_env.txt").write_text("release\n", encoding="utf-8")
    vcs.stage(folder, ["script/env/active_env.txt"])
    vcs.commit(folder, "use release")

    newest, first = vcs.history(folder)

    assert (newest.env, first.env) == ("release", "development")
    assert [s.env for s in vcs.graph_history(folder)] == ["release", "development"]
    assert vcs.env_at(folder, first.sha) == "development"
