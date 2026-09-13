from in_reach.app.vcs import FileDiff
from in_reach.ide.diff_dialog import DiffDialog


def test_lists_every_changed_file_with_a_change_type_prefix(qtbot) -> None:
    diffs = [
        FileDiff(path="a.txt", change_type="modified", diff_text="--- a\n+++ b\n"),
        FileDiff(path="b.txt", change_type="added", diff_text="+hi\n"),
        FileDiff(path="c.txt", change_type="removed", diff_text="-bye\n"),
    ]
    dialog = DiffDialog(None, title="main vs. feature", diffs=diffs)
    qtbot.addWidget(dialog)

    labels = [dialog.file_list.item(i).text() for i in range(dialog.file_list.count())]
    assert labels == ["M a.txt", "+ b.txt", "- c.txt"]


def test_selecting_a_file_shows_its_own_diff_text(qtbot) -> None:
    diffs = [
        FileDiff(path="a.txt", change_type="modified", diff_text="diff for a"),
        FileDiff(path="b.txt", change_type="modified", diff_text="diff for b"),
    ]
    dialog = DiffDialog(None, title="t", diffs=diffs)
    qtbot.addWidget(dialog)

    dialog.file_list.setCurrentRow(1)

    assert dialog.diff_text.toPlainText() == "diff for b"


def test_defaults_to_showing_the_first_files_diff(qtbot) -> None:
    diffs = [FileDiff(path="a.txt", change_type="modified", diff_text="diff for a")]
    dialog = DiffDialog(None, title="t", diffs=diffs)
    qtbot.addWidget(dialog)

    assert dialog.diff_text.toPlainText() == "diff for a"


def test_no_differences_shows_a_placeholder_message(qtbot) -> None:
    dialog = DiffDialog(None, title="t", diffs=[])
    qtbot.addWidget(dialog)

    assert dialog.file_list.count() == 0
    assert "no differences" in dialog.diff_text.toPlainText()


def test_window_title_matches_the_given_title(qtbot) -> None:
    dialog = DiffDialog(None, title="v1.0 vs. v2.0", diffs=[])
    qtbot.addWidget(dialog)

    assert dialog.windowTitle() == "v1.0 vs. v2.0"
