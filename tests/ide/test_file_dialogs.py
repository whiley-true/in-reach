from PyQt6.QtWidgets import QFileDialog, QWidget

from in_reach.ide import file_dialogs


def test_center_on_parent_screen_centers_the_dialog_on_the_parents_screen(qtbot) -> None:
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.show()
    dialog = QFileDialog(parent)
    qtbot.addWidget(dialog)

    file_dialogs._center_on_parent_screen(dialog, parent)

    expected = parent.screen().availableGeometry().center()
    actual = dialog.frameGeometry().center()
    assert abs(actual.x() - expected.x()) <= 1
    assert abs(actual.y() - expected.y()) <= 1


def test_center_on_parent_screen_is_a_no_op_with_no_parent(qtbot) -> None:
    dialog = QFileDialog()
    qtbot.addWidget(dialog)

    file_dialogs._center_on_parent_screen(dialog, None)  # should not raise


def test_get_existing_directory_returns_empty_string_when_cancelled(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(QFileDialog, "exec", lambda self: QFileDialog.DialogCode.Rejected)
    parent = QWidget()
    qtbot.addWidget(parent)

    assert file_dialogs.get_existing_directory(parent, "Pick a folder") == ""


def test_get_existing_directory_uses_a_non_native_dialog(qtbot, monkeypatch) -> None:
    # PROMPT.md: "please make sure file explorers always open on the same screen as the ide is
    # running on" -- the native common dialog remembers its own last-used screen independent of
    # the parent window, so only Qt's own dialog (which this module explicitly positions) can
    # guarantee that.
    seen = {}

    def fake_exec(self):
        seen["native"] = self.testOption(QFileDialog.Option.DontUseNativeDialog)
        return QFileDialog.DialogCode.Rejected

    monkeypatch.setattr(QFileDialog, "exec", fake_exec)
    parent = QWidget()
    qtbot.addWidget(parent)

    file_dialogs.get_existing_directory(parent, "Pick a folder")

    assert seen["native"] is True


def test_get_save_file_name_returns_empty_tuple_when_cancelled(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(QFileDialog, "exec", lambda self: QFileDialog.DialogCode.Rejected)
    parent = QWidget()
    qtbot.addWidget(parent)

    assert file_dialogs.get_save_file_name(parent, "Save As") == ("", "")


def test_get_open_file_name_returns_empty_tuple_when_cancelled(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(QFileDialog, "exec", lambda self: QFileDialog.DialogCode.Rejected)
    parent = QWidget()
    qtbot.addWidget(parent)

    assert file_dialogs.get_open_file_name(parent, "Select file") == ("", "")
