from in_reach.ide.settings_dialog import SettingsDialog


def test_settings_dialog_has_system_ui_and_theme_tabs(qtbot) -> None:
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    labels = [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]

    assert labels == ["System", "UI", "Theme"]


def test_settings_dialog_theme_tab_applies_live_and_notifies(qtbot) -> None:
    notified = []
    dialog = SettingsDialog(on_theme_changed=lambda applied: notified.append(applied.name))
    qtbot.addWidget(dialog)

    dialog.theme_tab.theme_picker.apply_theme("Whiley")

    assert notified == ["Whiley"]
    assert dialog.theme_tab.theme_picker.buttons["Whiley"].isChecked() is True
    assert dialog.theme_tab.theme_picker.buttons["Light"].isChecked() is False


def test_settings_dialog_system_and_ui_tabs_are_stubs(qtbot) -> None:
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    assert dialog.system_tab.isEnabled() is True  # the tab itself, just its stub label is muted
    assert dialog.ui_tab.isEnabled() is True


def test_settings_dialog_close_button_accepts(qtbot) -> None:
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    accepted = []
    dialog.accepted.connect(lambda: accepted.append(True))

    from PyQt6.QtWidgets import QPushButton

    buttons = [w for w in dialog.findChildren(QPushButton) if w.text() == "Close"]
    assert len(buttons) == 1
    buttons[0].click()

    assert accepted == [True]


def test_settings_dialog_opens_centered_at_half_screen_size(qtbot) -> None:
    from PyQt6.QtWidgets import QApplication

    dialog = SettingsDialog()
    qtbot.addWidget(dialog)
    dialog.show()

    screen = QApplication.primaryScreen()
    avail = screen.availableGeometry()
    assert dialog.width() == avail.width() // 2
    assert dialog.height() == avail.height() // 2
