from pathlib import Path

from in_reach.app import vcs
from in_reach.ide.diff_dialog import DiffDialog
from in_reach.ide.diff_view import DiffViewWidget


def _project_with_a_and_b_changed(tmp_path: Path) -> Path:
    folder = tmp_path / "abcd1234"
    folder.mkdir()
    (folder / "a.txt").write_text("a original\n", encoding="utf-8")
    (folder / "b.txt").write_text("b original\n", encoding="utf-8")
    vcs.init(folder)
    vcs.create_branch(folder, "feature")
    (folder / "a.txt").write_text("a changed\n", encoding="utf-8")
    (folder / "b.txt").write_text("b changed\n", encoding="utf-8")
    vcs.stage_all(folder)
    vcs.commit(folder, "change a and b")
    vcs.switch_branch(folder, vcs.DEFAULT_BRANCH)
    return folder


def test_lists_every_changed_file_with_a_change_type_prefix(qtbot, tmp_path: Path) -> None:
    folder = _project_with_a_and_b_changed(tmp_path)
    diffs = vcs.diff(folder, vcs.DEFAULT_BRANCH, "feature")

    dialog = DiffDialog(None, title="main vs. feature", folder=folder, ref_a=vcs.DEFAULT_BRANCH, ref_b="feature", diffs=diffs)
    qtbot.addWidget(dialog)

    labels = [dialog.file_list.item(i).text() for i in range(dialog.file_list.count())]
    assert labels == ["M a.txt", "M b.txt"]


def test_selecting_a_file_shows_its_own_diff_view(qtbot, tmp_path: Path) -> None:
    folder = _project_with_a_and_b_changed(tmp_path)
    diffs = vcs.diff(folder, vcs.DEFAULT_BRANCH, "feature")
    dialog = DiffDialog(None, title="t", folder=folder, ref_a=vcs.DEFAULT_BRANCH, ref_b="feature", diffs=diffs)
    qtbot.addWidget(dialog)

    dialog.file_list.setCurrentRow(1)

    assert isinstance(dialog._diff_view, DiffViewWidget)
    assert dialog._diff_view.rel_path == "b.txt"
    assert dialog._diff_view.old_pane.toPlainText() == "b original"
    assert dialog._diff_view.new_pane.toPlainText() == "b changed"


def test_defaults_to_showing_the_first_files_diff(qtbot, tmp_path: Path) -> None:
    folder = _project_with_a_and_b_changed(tmp_path)
    diffs = vcs.diff(folder, vcs.DEFAULT_BRANCH, "feature")
    dialog = DiffDialog(None, title="t", folder=folder, ref_a=vcs.DEFAULT_BRANCH, ref_b="feature", diffs=diffs)
    qtbot.addWidget(dialog)

    assert dialog._diff_view.rel_path == "a.txt"
    assert dialog._diff_view.old_pane.toPlainText() == "a original"
    assert dialog._diff_view.new_pane.toPlainText() == "a changed"


def test_no_differences_shows_a_placeholder_message(qtbot, tmp_path: Path) -> None:
    dialog = DiffDialog(None, title="t", folder=tmp_path, ref_a="main", ref_b="main", diffs=[])
    qtbot.addWidget(dialog)

    assert dialog.file_list.count() == 0
    assert dialog._empty_label.isHidden() is False
    assert dialog._diff_view is None


def test_window_title_matches_the_given_title(qtbot, tmp_path: Path) -> None:
    dialog = DiffDialog(None, title="v1.0 vs. v2.0", folder=tmp_path, ref_a="main", ref_b="main", diffs=[])
    qtbot.addWidget(dialog)

    assert dialog.windowTitle() == "v1.0 vs. v2.0"
